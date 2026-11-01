"""
The app probe and own-port mode.

The probe asks a running app how it wants to be served. Here it asks small
stand-in servers that each behave like one kind of real app (measured in the
sandbox: yarr, Memos, Radicale, Jupyter, Node-RED, Syncthing), so every answer
it can give is exercised, and the nginx text for own-port mode is checked in a
temp directory. No browser; the real-nginx runs are in docs/development-log.md.
"""

import http.server
import os
import re
import sys
import tempfile
import threading

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import appprobe  # noqa: E402
import appprovision  # noqa: E402

PATCHED = ["PORT_MAP_DIR", "POLICY_DIR", "NGINX_APPS_DIR", "NGINX_PORTS_DIR", "NGINX_SITE_DIRS", "NGINX_MAPS_FILE"]


def _page(*tags):
    return "<!doctype html><html><head><title>t</title></head><body>" + "".join(tags) + "</body></html>"


class StandIn:
    """A tiny app. `routes` maps a path to (status, headers, body); the handler may also react to headers."""

    def __init__(self, routes, respond=None):
        outer = self
        self.seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.seen.append((self.path, dict(self.headers)))
                made = respond(self) if respond else None
                status, headers, body = made or routes.get(self.path.split("?")[0], (404, {}, "not found"))
                data = body.encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


HTML = {"Content-Type": "text/html"}
JS = {"Content-Type": "text/javascript"}


def _probe(r, label, routes, expect_mode, respond=None, path="/", must_have=None):
    app = StandIn(routes, respond)
    try:
        result = appprobe.probe(app.port, path)
    finally:
        app.close()
    ok = result["mode"] == expect_mode
    r.check(f"probe: {label} -> {expect_mode}", ok, (result["mode"], result["reason"]))
    return result


def run(browser, r):
    # ---- The pure parts. ------------------------------------------------
    c = appprobe.classify
    r.check("probe: classify tells rooted, relative, absolute-to-this-machine and harmless apart",
            [c("/x"), c("x/y"), c("./x"), c("http://127.0.0.1:8080/"), c("https://cdn.example.org/a.js"), c("//cdn/a.js"), c("#top"), c("data:,"), c("")]
            == ["rooted", "relative", "relative", "absolute", "other", "other", "other", "other", "other"])
    page = _page('<script src="/a.js"></script>', '<a href="/click">x</a>', '<link rel="stylesheet" href=\'b.css\'>',
                 '<base href="http://127.0.0.1/">', '<form action="/post"></form>')
    kinds = {v: k for k, v in appprobe.refs_in(page)}
    r.check("probe: a clicked link is told apart from what loads with the page", kinds["/click"] == "link" and kinds["/a.js"] == "attr" and kinds["http://127.0.0.1/"] == "base")
    r.check("probe: only what loads with the page counts as rooted by default",
            sorted(appprobe.rooted_refs(page)) == ["/a.js", "/post", "http://127.0.0.1/"]
            and "/click" in appprobe.rooted_refs(page, clicked=True))
    r.check("probe: scripts are read for requests, not for every string",
            appprobe.rooted_in_script('fetch("/api/v1/x"); import("/a.js"); var re = "/not/a/url ok"; x.open("GET","/rest/y")') == ["/a.js", "/api/v1/x", "/rest/y"],
            appprobe.rooted_in_script('fetch("/api/v1/x"); import("/a.js"); var re = "/not/a/url ok"; x.open("GET","/rest/y")'))

    d = appprobe.decide
    r.check("probe: decide, relative page is strip", d([], [], [], 0, 404, [], 0)[0] == "strip")
    r.check("probe: decide, prefixed once told the mount point is script-name", d(["/a"], [], ["/ddprobe/a"], 1, 404, [], 0)[0] == "script-name")
    r.check("probe: decide, answering at the prefix itself is keep", d(["/a"], [], ["/a"], 0, 200, ["/ddprobe/a"], 1)[0] == "keep")
    r.check("probe: decide, otherwise own-port", d(["/a"], [], ["/a"], 0, 404, [], 0)[0] == "own-port")

    # ---- Stand-in apps, one per behaviour. ------------------------------
    relative = {"/": (200, HTML, _page('<link rel="stylesheet" href="./static/app.css">', '<script src="./static/app.js"></script>')),
                "/static/app.css": (200, {"Content-Type": "text/css"}, "body{}"), "/static/app.js": (200, JS, "var x=1;")}
    res = _probe(r, "an app whose every link is relative (yarr)", relative, "strip")
    r.check("probe: and it says what it could not see", any("run time" in n for n in res["notes"]), res["notes"])

    rooted = {"/": (200, HTML, _page('<script type="module" src="/assets/index.js"></script>', '<link href="/logo.webp">')),
              "/assets/index.js": (200, JS, 'fetch("/api/v1/sse");')}
    res = _probe(r, "an app whose links start at the site root (Memos)", rooted, "own-port")
    r.check("probe: the report names the links and gives a port and the firewall reminder",
            "--prefix-mode own-port --public-port" in appprobe.render_report("memos", 1, res) and "firewall" in appprobe.render_report("memos", 1, res))

    def script_aware(handler):
        prefix = handler.headers.get("X-Script-Name", "")
        if handler.path == "/":
            return (200, HTML, _page(f'<link href="{prefix}/.web/style.css">', f'<script src="{prefix}/.web/app.js"></script>'))
    _probe(r, "an app that writes its own prefix when told the mount point (Radicale)", {}, "script-name", respond=script_aware)

    def keeps_prefix(handler):
        if handler.path.startswith(appprobe.PROBE_PREFIX + "/"):
            return (200, HTML, _page(f'<script src="{appprobe.PROBE_PREFIX}/app.js"></script>'))
        if handler.path == "/":
            return (200, HTML, _page('<script src="/app.js"></script>'))
    _probe(r, "an app that answers at the prefix itself", {}, "keep", respond=keeps_prefix)

    based = {"/": (404, HTML, _page('<link href="/jupyter/static/a.css">', '<script src="/jupyter/static/a.js"></script>')),
             "/jupyter/": (200, HTML, _page('<script src="/jupyter/static/a.js"></script>')),
             "/jupyter/static/a.js": (200, JS, ""), "/jupyter/static/a.css": (200, {"Content-Type": "text/css"}, "")}
    res = _probe(r, "an app already given a base path (Jupyter)", based, "keep")
    r.check("probe: and it says which base path to register", any("--url-prefix /jupyter/" in n for n in res["notes"]), res["notes"])

    bare404 = {"/": (404, HTML, "not found")}
    res = _probe(r, "an app that shows nothing at / (Node-RED with httpRoot)", bare404, None)
    r.check("probe: and it says to probe where the app lives", "probe the path" in res["reason"], res["reason"])
    at_root = {"/nodered/": (200, HTML, _page('<script src="red/red.js"></script>')), "/nodered/red/red.js": (200, JS, "")}
    _probe(r, "the same app probed at its own path", at_root, "keep", path="/nodered/")

    page_ok = {"/": (200, HTML, _page('<script src="app.js"></script>')),
               "/app.js": (200, JS, 'fetch("/api/a"); fetch("/api/b"); fetch("/api/c");')}
    _probe(r, "a relative page whose scripts request three root paths", page_ok, "own-port")
    one = {"/": (200, HTML, _page('<script src="app.js"></script>', '<a href="/rest/debug">debug</a>')),
           "/app.js": (200, JS, 'fetch("/foo");')}
    res = _probe(r, "a relative page with one stray link and one stray example (Syncthing)", one, "strip")
    r.check("probe: and the stray script path is mentioned, not acted on", any("/foo" in n for n in res["notes"]), res["notes"])

    # ---- Habits that bite later. -----------------------------------------
    def fussy(handler):
        if handler.headers.get("Host", "").startswith("probe.invalid"):
            return (403, HTML, "invalid host")
        if handler.path == "/":
            return (401, {"WWW-Authenticate": 'Basic realm="Files"', "Content-Type": "text/html",
                          "Set-Cookie": "sessionid=abc; Path=/"}, _page('<script src="app.js"></script>'))
    res = _probe(r, "an app with its own login, a generic cookie and a host check", {}, "strip", respond=fussy)
    text = " ".join(res["warnings"] + res["notes"])
    r.check("probe: it warns about the Host check", "Host header" in text, text)
    r.check("probe: it warns about a cookie other apps may share", "sessionid" in text, text)
    r.check("probe: it explains its own HTTP login and X-Remote-User", "Basic realm" in text and "X-Remote-User" in text, text)

    res = appprobe.probe(1)  # nothing listens on port 1
    r.check("probe: nothing listening is reported, not a crash", res["reachable"] is False and "Start the app" in appprobe.render_report("x", 1, res))

    free = appprobe.suggest_public_port({9441, 9442})
    r.check("probe: the suggested public port skips the ones already registered", free is not None and free not in (9441, 9442) and free >= 9441, free)

    # ---- Registering asks the app. ---------------------------------------
    r.check("register: nothing to decide from an unreachable app or one with nothing to judge",
            appprobe.registration_from_probe({"reachable": False}) is None
            and appprobe.registration_from_probe({"reachable": True, "mode": None}) is None)
    r.check("register: strip and keep need no port, own-port gets a free one that is not taken",
            appprobe.registration_from_probe({"reachable": True, "mode": "strip", "url_prefix": None})["public_port"] is None
            and appprobe.registration_from_probe({"reachable": True, "mode": "keep", "url_prefix": "/jupyter/"})["url_prefix"] == "/jupyter/"
            and appprobe.registration_from_probe({"reachable": True, "mode": "own-port", "url_prefix": None}, {9441})["public_port"] not in (None, 9441))
    import importlib.util
    import types
    for mod in ("cleanup", "userconfig", "version"):
        importlib.import_module(mod)
    spec = importlib.util.spec_from_file_location("dd_provision_cli", os.path.join(h.ROOT, "tools", "dwarven-provision.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    cli._taken_public_ports = lambda: set()
    import contextlib
    import io

    def choose(app_routes, respond=None, port_given=True, url_prefix=None):
        stand = StandIn(app_routes, respond)
        try:
            args = types.SimpleNamespace(app="diva", probe_port=stand.port if port_given else None, probe_path="/",
                                         url_prefix=url_prefix)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                got = cli._choose_prefix_mode(args, url_prefix or "/diva/")
            return got, out.getvalue()
        finally:
            stand.close()
    got, said = choose(rooted)
    r.check("register: without --prefix-mode a running root-loving app is registered own-port with a free port, and it says so",
            got[0] == "own-port" and got[1] >= 9441 and "chosen by asking the running app" in said, (got, said[-120:]))
    got, said = choose(relative)
    r.check("register: a relative-links app is registered strip", got == ("strip", None, "/diva/"), got)
    got, said = choose(based)
    r.check("register: an app with its own base path is registered keep, with that path as the url prefix", got == ("keep", None, "/jupyter/"), got)
    got, said = choose(based, url_prefix="/mine/")
    r.check("register: an explicit --url-prefix is never replaced", got[2] == "/mine/", got)
    got, said = choose(relative, port_given=False)
    r.check("register: nothing running means the default, and the later command is named",
            got == ("strip", None, "/diva/") and "install.sh probe --app diva" in said, (got, said))

    # ---- Own-port nginx text. --------------------------------------------
    saved = {n: getattr(appprovision, n) for n in PATCHED}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            d_ = lambda *p: os.path.join(tmp, *p)
            appprovision.PORT_MAP_DIR = d_("ports")
            appprovision.POLICY_DIR = d_("policies")
            appprovision.NGINX_APPS_DIR = d_("apps")
            appprovision.NGINX_PORTS_DIR = d_("portservers")
            appprovision.NGINX_MAPS_FILE = d_("maps.conf")
            site_dir = d_("sites")
            os.makedirs(site_dir)
            appprovision.NGINX_SITE_DIRS = (site_dir,)

            loc = appprovision.location_content("diva", "/diva/", "own-port", 9441)
            r.check("own-port: the main site only points at the port, with no proxying", "return 302 $scheme://$host:9441/;" in loc and "proxy_pass" not in loc)
            strip = appprovision.location_content("plain", "/plain/")
            r.check("own-port: the other modes are untouched", "rewrite ^/plain/(.*)$ /$1 break;" in strip and "proxy_pass http://127.0.0.1:$plain_port;" in strip)

            plain_site = "server {\n    listen 80;\n    listen [::]:80;\n    include /etc/nginx/dwarvendash-gate.conf;\n}\n"
            open(os.path.join(site_dir, "default"), "w").write(plain_site)
            srv = appprovision.port_server_content("diva", 9441)
            r.check("own-port: on a plain HTTP site the port listens plain, on IPv4 and IPv6",
                    "listen 9441;" in srv and "listen [::]:9441;" in srv and "ssl" not in srv, srv)
            tls_site = ("server {\n    listen 443 ssl;\n    ssl_certificate     /c/full.pem;\n    ssl_certificate_key /c/key.pem;\n"
                        "    ssl_protocols TLSv1.2 TLSv1.3;\n    include /etc/nginx/dwarvendash-gate.conf;\n}\n")
            open(os.path.join(site_dir, "default"), "w").write(tls_site)
            srv = appprovision.port_server_content("diva", 9441)
            r.check("own-port: on a TLS site the port uses the same certificate and protocols",
                    "listen 9441 ssl;" in srv and "ssl_certificate     /c/full.pem;".replace("     ", " ") in srv.replace("     ", " ")
                    and "ssl_certificate_key /c/key.pem;" in srv and "ssl_protocols TLSv1.2 TLSv1.3;" in srv and "[::]" not in srv, srv)
            r.check("own-port: the port has the shared sign-in wall and sends the app the request untouched",
                    f"include {appprovision.NGINX_GATE_FILE};" in srv and "rewrite" not in srv and "proxy_redirect" not in srv
                    and "proxy_pass http://127.0.0.1:$diva_port;" in srv and "error_page 401 = @auth_denied;" in srv)
            common = appprovision._proxy_common("diva")
            squeezed = lambda t: re.sub(r"\s+", " ", t)
            r.check("own-port: it gets exactly the headers every other mode gets (one copy)",
                    squeezed(common) in squeezed(srv) and squeezed(common) in squeezed(strip.replace("plain", "diva")))
            r.check("own-port: an unprovisioned user gets a clean 403, as in the other modes",
                    "location @diva_not_provisioned" in srv and "Not provisioned for diva" in srv)

            r.check("own-port: first write creates the main-site file and the port server", appprovision.ensure_location_block("diva", "/diva/", "own-port", 9441) is True
                    and os.path.isfile(d_("apps", "diva.conf")) and os.path.isfile(d_("portservers", "diva.conf")))
            r.check("own-port: an unchanged second write does nothing", appprovision.ensure_location_block("diva", "/diva/", "own-port", 9441) is False)
            r.check("own-port: changing the port rewrites both", appprovision.ensure_location_block("diva", "/diva/", "own-port", 9450) is True
                    and "9450" in open(d_("portservers", "diva.conf")).read() and "9450" in open(d_("apps", "diva.conf")).read())
            r.check("own-port: going back to another mode removes the port server",
                    appprovision.ensure_location_block("diva", "/diva/", "strip") is True and not os.path.exists(d_("portservers", "diva.conf")))
            appprovision.ensure_location_block("diva", "/diva/", "own-port", 9441)
            r.check("own-port: removing the app removes both files", appprovision._remove_location_block("diva") is True
                    and not os.path.exists(d_("portservers", "diva.conf")) and not os.path.exists(d_("apps", "diva.conf")))

            bad = []
            for port in (None, 80, 70000, "9441"):
                try:
                    appprovision.register_app_policy("diva", 50000, "/diva/", "x {port}", prefix_mode="own-port", public_port=port)
                    bad.append(port)
                except ValueError:
                    pass
            r.check("own-port: registering needs a real port above 1023", not bad, bad)
            refused = []
            for call in (lambda: appprovision.location_content("diva", "/diva/", "own-port", None),
                         lambda: appprovision.port_server_content("diva", None),
                         lambda: appprovision.ensure_location_block("diva", "/diva/", "own-port")):
                try:
                    call()
                    refused.append("wrote")
                except ValueError:
                    pass
            r.check("own-port: no nginx text is ever written with a missing port", not refused and not os.path.exists(d_("portservers", "diva.conf")), refused)
            path = appprovision.register_app_policy("diva", 50000, "/diva/", "x {port}", prefix_mode="own-port", public_port=9441)
            policy = appprovision.get_app_policy("diva")
            r.check("own-port: the policy records the mode and the port", policy["prefix_mode"] == "own-port" and policy["public_port"] == 9441 and os.path.isfile(path), policy)
    finally:
        for n, v in saved.items():
            setattr(appprovision, n, v)

    # ---- The shipped nginx files. ----------------------------------------
    gate = open(os.path.join(h.ROOT, "nginx", "dwarvendash-gate.conf")).read()
    r.check("own-port: the shared sign-in wall has the check, login, logout and the denied handler",
            all(x in gate for x in ("location = /internal-auth-check", "location = /login", "location = /logout", "location @auth_denied", "auth_request /internal-auth-check;", "dwarvendash-authfail.log")))
    for name in ("dwarvendash-http.conf", "dwarvendash-https.conf"):
        text = open(os.path.join(h.ROOT, "nginx", name)).read()
        r.check(f"own-port: {name} includes the wall once and the port servers at the end",
                text.count("include /etc/nginx/dwarvendash-gate.conf;") == 1 and text.rstrip().endswith("include /etc/nginx/dwarvendash-ports/*.conf;")
                and "location @auth_denied" not in text)
    install = open(os.path.join(h.ROOT, "install.sh")).read()
    r.check("own-port: the installer puts the shared wall in place before it validates nginx",
            install.index("nginx/dwarvendash-gate.conf\" \"${NGINX_DIR}/dwarvendash-gate.conf\"") < install.index("log \"Installing nginx config for"))

    # ---- The installer asks before replacing an nginx config it did not just write. ----
    import subprocess
    work = tempfile.mkdtemp(prefix="dd-ng-")
    target = os.path.join(work, "default")
    funcs = subprocess.run(
        ["awk", '/^(interrogate_existing_setup|get_ssl_cert_path|get_ssl_key_path|render_template)\\(\\) \\{/{p=1} p{print} p&&/^}/{p=0}',
         os.path.join(h.ROOT, "install.sh")], capture_output=True, text=True).stdout
    script = ("log(){ :; }; is_stock_file(){ cmp -s \"$1\" \"$2\"; }; SCRIPT_DIR=%s\nNGINX_TARGET=%s\n%s\nEFFECTIVE_DOMAIN=_\nTEMPLATE=%s/nginx/dwarvendash-http.conf\n"
              % (h.ROOT, target, funcs, h.ROOT))

    def state(content=None, render=False, edit=None):
        if os.path.exists(target):
            os.remove(target)
        if render:
            subprocess.run(["bash", "-c", script + "render_template $TEMPLATE " + target], check=True)
        if content is not None:
            open(target, "w").write(content)
        if edit:
            text = open(target).read()
            open(target, "w").write(edit(text))
        return subprocess.run(["bash", "-c", script + "interrogate_existing_setup"], capture_output=True, text=True).stdout.strip().splitlines()[-1]

    r.check("installer: no config is 'missing'", state() == "missing")
    r.check("installer: exactly what it would write is 'current', no question", state(render=True) == "current")
    r.check("installer: its own config edited since is 'ours-changed', so it asks",
            state(render=True, edit=lambda t: t + "# mine\n") == "ours-changed")
    r.check("installer: its own older layout (no shared wall) is 'ours-changed', so it asks",
            state(render=True, edit=lambda t: t.replace("include /etc/nginx/dwarvendash-gate.conf;", "")) == "ours-changed")
    r.check("installer: somebody else's config is 'customized', so it asks", state("server { listen 80; }\n") == "customized")
    case = install[install.index("case \"${STATE}\" in"):]
    r.check("installer: customized and ours-changed share one asking branch, and 'ours-changed' has no branch before it",
            "customized|ours-changed)" in case and case.count("ours-changed)") == 1)

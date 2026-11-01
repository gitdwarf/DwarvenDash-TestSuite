"""
What the generated nginx routing does to the traffic of an app.

Each of these was a real failure measured against real apps behind real
nginx: WebSocket apps answered 426 (no upgrade headers), a 5 MB upload was
a 413 (nginx's 1 MB default, also applied to the login check), and the
app received the person's system password in an Authorization header.
No browser, no nginx: the text DwarvenDash writes is checked, in a temp
directory. The real-nginx runs are in docs/development-log.md.
"""

import os
import re
import sys
import tempfile

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import appprovision  # noqa: E402

PATCHED = ["PORT_MAP_DIR", "POLICY_DIR", "NGINX_APPS_DIR", "NGINX_MAPS_FILE"]
OLD_STYLE = ("location /oldapp/ {\n    proxy_pass http://127.0.0.1:$oldapp_port;\n"
             "    proxy_http_version 1.1;\n}\n")


def _auth_block(name):
    text = h.effective_nginx(name)
    start = text.index("location = /internal-auth-check")
    return text[start:text.index("}", start)]


def run(browser, r):
    saved = {n: getattr(appprovision, n) for n in PATCHED}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            d = lambda *p: os.path.join(tmp, *p)
            appprovision.PORT_MAP_DIR = d("ports")
            appprovision.POLICY_DIR = d("policies")
            appprovision.NGINX_APPS_DIR = d("apps")
            appprovision.NGINX_MAPS_FILE = d("maps.conf")

            text = appprovision.location_content("papp", "/papp/")
            r.check("proxy: WebSocket upgrade headers are sent to the app",
                    "proxy_set_header Upgrade $http_upgrade;" in text
                    and "proxy_set_header Connection $dd_connection_upgrade;" in text)
            r.check("proxy: uploads are not capped by nginx's 1 MB default and are streamed",
                    "client_max_body_size 0;" in text and "proxy_request_buffering off;" in text)
            r.check("proxy: the app's Authorization header comes from a map, never the person's password",
                    "proxy_set_header Authorization $dd_app_authorization;" in text)
            r.check("proxy: the session cookie is taken out of the Cookie header the app gets",
                    "proxy_set_header Cookie $dd_app_cookie;" in text)
            r.check("proxy: an app location still sends a browser to log in (its own error_page replaces the server's)",
                    "error_page 401 = @auth_denied;" in text)
            r.check("proxy: the stock configs define the @auth_denied it points at",
                    all("location @auth_denied" in h.effective_nginx(n)
                        for n in ("dwarvendash-http.conf", "dwarvendash-https.conf")))
            keep = appprovision.location_content("papp", "/papp/", "keep")
            r.check("proxy: keep mode leaves the prefix on the request and the redirects alone",
                    "rewrite" not in keep and "proxy_redirect" not in keep and "X-Script-Name" not in keep)
            sn = appprovision.location_content("papp", "/papp/", "script-name")
            r.check("proxy: script-name mode strips the prefix, names the mount point, leaves redirects alone",
                    "rewrite ^/papp/(.*)$ /$1 break;" in sn and "proxy_set_header X-Script-Name /papp;" in sn
                    and "proxy_set_header X-Forwarded-Prefix /papp;" in sn and "proxy_redirect" not in sn)
            r.check("proxy: the default mode is unchanged and sends no prefix headers",
                    "rewrite ^/papp/(.*)$ /$1 break;" in text and "proxy_redirect" in text and "X-Script-Name" not in text)
            try:
                appprovision.register_app_policy("papp", 1, "/papp/", "/bin/true {port}", prefix_mode="nonsense")
                refused = False
            except ValueError:
                refused = True
            r.check("proxy: an unknown prefix mode is refused at registration, not written", refused)
            r.check("proxy: the verified user is passed to apps that can trust a proxy, replacing any client copy",
                    "proxy_set_header X-Remote-User $auth_user;" in text
                    and "proxy_set_header X-Forwarded-User $auth_user;" in text)
            r.check("proxy: the routing is still intact (rewrite, per-user port, redirects)",
                    "rewrite ^/papp/(.*)$ /$1 break;" in text and "proxy_pass http://127.0.0.1:$papp_port;" in text
                    and "proxy_redirect" in text)

            # ---- {port} and {home} in a registered start command. ------------
            out = appprovision.render_exec_template("/bin/app --port={port} --data={home}/d", 41234, "root")
            r.check("proxy: {port} and {home} are filled in for the user",
                    out == "/bin/app --port=41234 --data=/root/d", out)
            r.check("proxy: a user with no account gets a harmless home, not a crash",
                    appprovision.render_exec_template("{home}", 1, "no-such-user-xyz") == "/")
            r.check("proxy: an older template with only {port} still works",
                    appprovision.render_exec_template("/bin/app --port={port}", 7, "root") == "/bin/app --port=7")

            # ---- The shared map the upgrade header needs. -------------------
            r.check("proxy: the upgrade map is added", appprovision.ensure_shared_maps() is True)
            r.check("proxy: and only once", appprovision.ensure_shared_maps() is False
                    and open(d("maps.conf")).read().count("$dd_connection_upgrade") == 1)

            # ---- Provisioning wires it all together. ------------------------
            appprovision.subprocess.run, real = (lambda *a, **k: __import__("subprocess").CompletedProcess(a, 0, "", "")), appprovision.subprocess.run
            try:
                os.makedirs(d("rc.d"), exist_ok=True)
                saved_rc = (appprovision.SYSVINIT_RC_DIR, appprovision.RC_LOCAL_PATH, appprovision.SYSTEMD_UNIT_DIR)
                appprovision.SYSVINIT_RC_DIR, appprovision.RC_LOCAL_PATH, appprovision.SYSTEMD_UNIT_DIR = d("rc.d"), d("rc.d", "rc.local"), d("sd")
                os.makedirs(d("sd"), exist_ok=True)
                appprovision.provision_app_for_user("papp", 40100, "/papp/", "alice", 1001, "/bin/true --port={port}")
                maps = open(d("maps.conf")).read()
                r.check("proxy: provisioning brings the map, so the location never names a missing variable",
                        "$dd_connection_upgrade" in maps and "$papp_port" in maps)
            finally:
                appprovision.subprocess.run = real
                appprovision.SYSVINIT_RC_DIR, appprovision.RC_LOCAL_PATH, appprovision.SYSTEMD_UNIT_DIR = saved_rc

            # ---- A file written by an older version is brought up to date. ---
            os.makedirs(d("apps"), exist_ok=True)
            open(d("apps", "oldapp.conf"), "w").write(OLD_STYLE)
            r.check("proxy: an older location file is rewritten", appprovision.ensure_location_block("oldapp", "/oldapp/") is True)
            new = open(d("apps", "oldapp.conf")).read()
            r.check("proxy: and now has the fixes", "$dd_app_authorization" in new and "client_max_body_size 0;" in new)
            r.check("proxy: a current file is left alone", appprovision.ensure_location_block("oldapp", "/oldapp/") is False)

            # ---- The stock nginx configs. -----------------------------------
            for name in ("dwarvendash-http.conf", "dwarvendash-https.conf"):
                block = _auth_block(name)
                r.check(f"proxy: {name} lifts the size limit on the login check too",
                        "client_max_body_size 0;" in block, "the login check inherits nginx's 1 MB default otherwise")
                body = h.effective_nginx(name)
                r.check(f"proxy: {name} keeps the failed-login log (map, format, log line)",
                        "$dd_login_failed" in body and "log_format dwarvendash_authfail" in body
                        and re.search(r"access_log\s+\S*dwarvendash-authfail\.log\s+dwarvendash_authfail\s+if=\$dd_login_failed;", body) is not None)
    finally:
        for n, v in saved.items():
            setattr(appprovision, n, v)

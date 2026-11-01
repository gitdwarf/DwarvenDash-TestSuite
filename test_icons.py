"""
App icons.

Part one is no browser: appicon against throwaway loopback servers that
play the part of an app (icon named in the page, plain /favicon.ico,
no icon at all, an icon link pointing at another host, a redirect off
the host, an oversized file). Part two drives the real dashboard with a
fake app instance and checks the launcher shows its icon, falls back to
a letter tile, and that the route cannot be aimed at someone else's port.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dd_harness as h

import sys
sys.path.insert(0, h.APP_DIR)
import appicon  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82")
ICO = b"\x00\x00\x01\x00" + b"\x00" * 20


def _app(routes):
    """A loopback server answering {path: (status, content_type, body, extra_headers)}."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            status, ctype, body, extra = routes.get(self.path.split("?")[0], (404, "text/plain", b"", {}))
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _page(link):
    return (200, "text/html", f"<html><head>{link}</head><body>x</body></html>".encode(), {})


def run(browser, r):
    # ---- parsing
    r.check("icons: finds a plain icon link", appicon.find_icon_href('<link rel="icon" href="/a.png">') == "/a.png")
    r.check("icons: finds shortcut icon", appicon.find_icon_href('<link rel="Shortcut  Icon" href="b.ico">') == "b.ico")
    r.check("icons: prefers icon over apple-touch-icon",
            appicon.find_icon_href('<link rel="apple-touch-icon" href="t.png"><link rel="icon" href="i.png">') == "i.png")
    r.check("icons: no icon link gives None", appicon.find_icon_href("<html><link rel='stylesheet' href='x.css'></html>") is None)
    r.check("icons: broken markup does not raise", appicon.find_icon_href("<link rel=icon href=") is None)

    # ---- fetching
    def lookup(routes, key):
        srv, port = _app(routes)
        try:
            appicon._cache.clear()
            return appicon.get_app_icon(key, port)
        finally:
            srv.shutdown()

    got = lookup({"/": _page('<link rel="icon" href="/images/app.png">'), "/images/app.png": (200, "image/png", PNG, {})}, "a")
    r.check("icons: icon named in the page is fetched", got == (PNG, "image/png"), got and got[1])
    got = lookup({"/": _page('<link rel="icon" href="rel/i.png">'), "/rel/i.png": (200, "image/png", PNG, {})}, "b")
    r.check("icons: relative icon link resolves", got and got[0] == PNG)
    got = lookup({"/": (200, "text/html", b"<html></html>", {}), "/favicon.ico": (200, "application/octet-stream", ICO, {})}, "c")
    r.check("icons: falls back to /favicon.ico, octet-stream accepted when it is really an icon",
            got == (ICO, "image/x-icon"), got)
    r.check("icons: no icon anywhere gives None", lookup({"/": (200, "text/html", b"<html></html>", {})}, "d") is None)
    r.check("icons: an HTML page pretending to be the icon is refused",
            lookup({"/": _page('<link rel="icon" href="/x.png">'), "/x.png": (200, "text/html", b"<html>login</html>", {})}, "e") is None)
    r.check("icons: an icon link pointing at another host is ignored, favicon.ico used instead",
            lookup({"/": _page('<link rel="icon" href="http://example.invalid/i.png">'),
                    "/favicon.ico": (200, "image/x-icon", ICO, {})}, "f") == (ICO, "image/x-icon"))
    other, other_port = _app({"/steal.png": (200, "image/png", PNG, {})})
    try:
        got = lookup({"/": _page('<link rel="icon" href="/go">'),
                      "/go": (302, "text/plain", b"", {"Location": f"http://127.0.0.1:{other_port}/steal.png"})}, "g")
        r.check("icons: a redirect to a different port is not followed", got is None, got and got[1])
    finally:
        other.shutdown()
    got = lookup({"/": _page('<link rel="icon" href="/login">'), "/login": (302, "text/plain", b"", {"Location": "/real.png"}),
                  "/real.png": (200, "image/png", PNG, {})}, "h")
    r.check("icons: a redirect on the same host is followed", got and got[0] == PNG)
    r.check("icons: an oversized icon is refused",
            lookup({"/": (200, "text/html", b"", {}), "/favicon.ico": (200, "image/png", b"x" * (appicon.MAX_ICON_BYTES + 10), {})}, "i") is None)
    r.check("icons: a dead port gives None quickly", appicon.get_app_icon("dead", 1) is None)

    # ---- cache: a miss is remembered, then retried after its time is up
    srv, port = _app({"/": (200, "text/html", b"", {})})
    appicon._cache.clear()
    clock = [1000.0]
    now = lambda: clock[0]
    appicon.get_app_icon("cache", port, now)
    srv.shutdown()
    srv2, _ = None, None
    r.check("icons: a miss is cached", ("cache", port) in appicon._cache and appicon._cache[("cache", port)][1] is None)
    clock[0] += appicon.MISS_TTL + 1
    r.check("icons: a miss expires", appicon._cache[("cache", port)][0] < now())

    # ---- the real dashboard
    app_srv, app_port = _app({"/": _page('<link rel="icon" href="/fav.png">'), "/fav.png": (200, "image/png", PNG, {})})
    other_srv, other_port = _app({"/": (200, "text/html", b"", {}), "/favicon.ico": (200, "image/x-icon", ICO, {})})
    try:
        real_dir = h.PORT_MAP_DIR
        try:
            for app, user_port in (("iconapp", app_port), ("plainapp", other_port)):
                with open(os.path.join(real_dir, f"{app}.map"), "w") as f:
                    f.write(f"{h.TEST_USER} {user_port};\nsomeoneelse {other_port};\n")
            h.reset_user_config()
            cfg_path = h.user_config_path()
            os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
            with open(cfg_path, "w") as f:
                json.dump({"launcher": [{"group": "Apps", "links": [
                    {"title": "iconapp", "url": "/iconapp/", "type": "app"},
                    {"title": "noicon", "url": "/noicon/", "type": "app"},
                    {"title": "Site", "url": "https://example.com", "type": "bookmark"}]}]}, f)

            def get(path, user=h.TEST_USER):
                req = h.request(path, user=user if user else False)
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        return resp.status, resp.headers.get_content_type(), resp.read()
                except urllib.error.HTTPError as e:
                    return e.code, "", b""

            status, ctype, body = get("/app-icon/iconapp")
            r.check("icons: route serves the app's own icon", (status, ctype, body) == (200, "image/png", PNG), (status, ctype))
            status, ctype, body = get("/app-icon/plainapp")
            r.check("icons: route falls back to favicon.ico", (status, body) == (200, ICO), status)
            r.check("icons: an app this user has no instance of gives 204", get("/app-icon/noicon")[0] == 204)
            r.check("icons: no credentials gives 401, not someone's icon", get("/app-icon/iconapp", user=None)[0] == 401)
            r.check("icons: another user's name cannot reach this user's port",
                    get("/app-icon/iconapp", user="nobody-here")[0] == 204)
            for bad in ("../x", "a/b", "a%2f..%2fb", "", "a%20b"):
                r.check(f"icons: odd app name {bad!r} gives 204 or 404", get("/app-icon/" + bad)[0] in (204, 404), bad)

            page = h.new_page(browser)
            h.open_dashboard(page, settle=1.5)
            time.sleep(1)
            r.check("icons: launcher shows the app's real icon",
                    page.locator('.launcher-link-item:has-text("iconapp") a img.link-icon').count() == 1)
            r.check("icons: an app with no icon shows a letter tile, no broken image",
                    page.locator('.launcher-link-item:has-text("noicon") a .link-icon-tile').count() == 1
                    and page.locator('.launcher-link-item:has-text("noicon") a img').count() == 0)
            r.check("icons: bookmark shows a letter tile", page.locator('.launcher-link-item:has-text("Site") a .link-icon-tile').count() == 1)
            r.check("icons: the link text is still just the title",
                    page.eval_on_selector_all(".launcher-link-item a", "e => e.map(x => x.textContent)") == ["iconapp", "noicon", "Site"])
            tile_letter = page.eval_on_selector('.launcher-link-item:has-text("noicon") .link-icon-tile',
                                                "e => getComputedStyle(e, '::before').content")
            r.check("icons: tile draws the first letter", tile_letter == '"N"', tile_letter)
            loaded = page.eval_on_selector('.launcher-link-item:has-text("iconapp") img', "e => e.naturalWidth")
            r.check("icons: the icon actually decoded", loaded > 0, loaded)
            h.shot(page, "icons_01_launcher")
            h.finish_page(r, page, "icons")
            page.context.close()
        finally:
            for n in ("iconapp.map", "plainapp.map"):
                if os.path.exists(os.path.join(real_dir, n)):
                    os.remove(os.path.join(real_dir, n))
    finally:
        app_srv.shutdown()
        other_srv.shutdown()

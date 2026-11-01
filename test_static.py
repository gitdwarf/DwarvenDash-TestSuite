"""
Static file serving: only files inside static/ are ever served.

The regression: the guard was a bare string prefix test, so a sibling
directory whose name merely STARTS with "static" passed it. The probe
directory below is exactly that, created for the test and removed after.
"""

import os
import shutil
import urllib.error
import urllib.request

import dd_harness as h


def _get(path):
    try:
        with urllib.request.urlopen(h.request(path), timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def run(browser, r):
    probe = os.path.join(h.APP_DIR, "static-probe")
    os.makedirs(probe, exist_ok=True)
    try:
        with open(os.path.join(probe, "secret.txt"), "w") as f:
            f.write("not for the web")
        status, body = _get("/../static-probe/secret.txt")
        r.check("static: a sibling directory sharing the 'static' prefix is not served", status == 403 and b"not for" not in body, status)
        r.check("static: a file outside static/ is not served", _get("/../server.py")[0] in (403, 404))
        r.check("static: a normal asset is served", _get("/style.css")[0] == 200)
        import urllib.request as _u
        with _u.urlopen(h.request("/widgets.js"), timeout=5) as resp:
            r.check("static: scripts are revalidated on every load, so an update is never masked by a stale copy",
                    resp.headers.get("Cache-Control") == "no-cache", resp.headers.get("Cache-Control"))
        r.check("static: a missing asset is 404", _get("/nothing-here.js")[0] == 404)
    finally:
        shutil.rmtree(probe, ignore_errors=True)

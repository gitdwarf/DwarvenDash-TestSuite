"""
Who you are is proven by credentials, never by a header.

Any local account can open a connection to the dashboard's port and write
whatever headers it likes, so a header proves nothing. The server asks the
PAM helper whether the Authorization header is genuine. Here a stand-in for
that helper answers (see dd_harness). No browser: plain requests.
"""

import json
import sys
import time
import urllib.error
import urllib.request

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import identity  # noqa: E402


def _status(path, user=None, headers=None, data=None, method=None):
    req = h.request(path, user=user, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def run(browser, r):
    h.reset_user_config()
    mine = {"theme": "forge"}
    code, _, _ = _status("/config.json", data=json.dumps(mine).encode(), method="POST")
    r.check("identity: real credentials may save a config", code == 200, code)

    code, _, body = _status("/config.json")
    r.check("identity: real credentials read their own config", code == 200 and json.loads(body).get("theme") == "forge")

    # ---- No credentials, no entry, on every kind of request. --------------
    for path in ("/", "/config.json", "/events", "/version.json", "/app-icon/x", "/available-apps"):
        code, headers, _ = _status(path, user=False)
        r.check(f"identity: GET {path} without credentials is refused", code == 401, code)
    code, headers, _ = _status("/config.json", user=False, data=b"{}", method="POST")
    r.check("identity: POST without credentials is refused", code == 401, code)
    r.check("identity: the refusal asks a browser to log in", "Basic" in (headers.get("WWW-Authenticate") or ""))

    # ---- The old way in: a header anyone can write. -----------------------
    code, _, _ = _status("/config.json", user=False, headers={"X-Authenticated-User": h.TEST_USER})
    r.check("identity: a forged X-Authenticated-User alone gets nowhere", code == 401, code)
    code, _, _ = _status("/config.json", user=False, headers={"X-Authenticated-User": h.TEST_USER},
                         data=b'{"theme":"chalk"}', method="POST")
    r.check("identity: a forged header cannot write someone's config", code == 401, code)
    r.check("identity: and nothing was written", h.read_user_config().get("theme") == "forge")

    # ---- Real credentials win over a header naming someone else. ----------
    code, _, body = _status("/config.json", headers={"X-Authenticated-User": "root"})
    r.check("identity: a header naming someone else changes nothing",
            code == 200 and json.loads(body).get("theme") == "forge")

    # ---- Wrong password. ---------------------------------------------------
    code, _, _ = _status("/config.json", headers=h.auth_header(h.TEST_USER, "wrong"))
    r.check("identity: a wrong password is refused", code == 401, code)

    # ---- Cache: successes are remembered briefly, failures never. ---------
    time.sleep(h.AUTH_CACHE_SECONDS + 0.5)
    h.AUTH_CALLS.clear()
    _status("/version.json", user="cachetest")
    _status("/version.json", user="cachetest")
    r.check("identity: a good answer is remembered for the next request", len(h.AUTH_CALLS) == 1, h.AUTH_CALLS)
    time.sleep(h.AUTH_CACHE_SECONDS + 0.5)
    _status("/version.json", user="cachetest")
    r.check("identity: and asked again once it has expired", len(h.AUTH_CALLS) == 2, h.AUTH_CALLS)
    h.AUTH_CALLS.clear()
    for _ in range(2):
        _status("/version.json", headers=h.auth_header("cachetest", "wrong"))
    r.check("identity: a refusal is never remembered", len(h.AUTH_CALLS) == 2, h.AUTH_CALLS)
    h.AUTH_CALLS.clear()
    _status("/version.json", user="cachetest")
    _status("/version.json", headers=h.auth_header("cachetest", "wrong"))
    r.check("identity: a good login does not vouch for a different password", h.AUTH_CALLS[-1:] == [None], h.AUTH_CALLS)

    # ---- Fails closed when the helper cannot be reached. ------------------
    saved = identity.AUTHCHECK_BASE
    identity.AUTHCHECK_BASE = "http://127.0.0.1:1"
    try:
        r.check("identity: an unreachable helper means no entry, never open",
                identity.verified_user(h.auth_header("neverseen")) is None)
    finally:
        identity.AUTHCHECK_BASE = saved
    r.check("identity: no header is no identity", identity.verified_user(None) is None and identity.verified_user({}) is None)

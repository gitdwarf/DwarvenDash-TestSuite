"""
The login form and its session cookie.

The pieces, bottom up: the session store and the small functions around it
(session.py), the page (loginpage.py), the real login helper over HTTP
(authcheck.py, with only PAM and the group check replaced, see dd_harness),
the dashboard accepting the cookie, the nginx templates and the maps they
rely on, the fail2ban filter, and the Log out button in a real page.

What a real nginx does with the maps and deny rules is run by hand against
the real stack, the results are in docs/development-log.md. Here the text is
checked, and the cookie-removal patterns are run as regular expressions on
real cookie strings.
"""

import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import sys
import urllib.error
import urllib.parse
import urllib.request

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import appprovision  # noqa: E402
import authcheck  # noqa: E402
import loginpage  # noqa: E402
import session  # noqa: E402
import userprovision  # noqa: E402

HELPER = f"http://127.0.0.1:{h.AUTH_PORT}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _call(base, method, path, headers=None, data=None):
    """(status, headers, body) without following redirects."""
    req = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
    try:
        with _opener.open(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _login(username, password, next_path=None, extra=None):
    fields = {"username": username, "password": password}
    if next_path is not None:
        fields["next"] = next_path
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    headers.update(extra or {})
    return _call(HELPER, "POST", "/login", headers, urllib.parse.urlencode(fields).encode())


def _cookie_of(headers):
    value = headers.get("Set-Cookie") or ""
    m = re.match(rf"{session.COOKIE_NAME}=([^;]*)", value)
    return m.group(1) if m else None


def _store_checks(r):
    now = [1000.0]
    store = session.SessionStore(ttl_seconds=60, clock=lambda: now[0], per_user_limit=3)
    t = store.create("alice")
    r.check("login: a new session belongs to its user", store.lookup(t) == "alice")
    r.check("login: tokens are long and never repeat", len(t) >= 40 and len({store.create("bob") for _ in range(3)}) == 3)
    r.check("login: an unknown, empty or missing token is nobody",
            store.lookup("nope") is None and store.lookup("") is None and store.lookup(None) is None)
    now[0] += 61
    r.check("login: a session ends when its time is up", store.lookup(t) is None)
    t2 = store.create("alice")
    store.revoke(t2)
    r.check("login: logout revokes the session at once", store.lookup(t2) is None)
    first = store.create("carol")
    for _ in range(3):
        store.create("carol")
    r.check("login: one person cannot hold more than the limit, the oldest goes",
            store.lookup(first) is None and len([1 for k in store._sessions.values() if k[0] == "carol"]) == 3)

    cookie = f"a=1; {session.COOKIE_NAME}=TOKEN123; b=2"
    r.check("login: the token is found among other cookies", session.token_from_cookie_header(cookie) == "TOKEN123")
    r.check("login: and nothing is found where there is nothing",
            session.token_from_cookie_header("") is None and session.token_from_cookie_header(None) is None
            and session.token_from_cookie_header("a=1") is None and session.token_from_cookie_header(";;==;") is None
            and session.token_from_cookie_header(f"x{session.COOKIE_NAME}=1") is None)

    plain = session.set_cookie_header("T", 3600, secure=False)
    r.check("login: the cookie is HttpOnly, SameSite=Lax, for the whole site, with a lifetime",
            all(x in plain for x in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=3600")) and "Secure" not in plain, plain)
    r.check("login: and Secure when the site is served over HTTPS", "Secure" in session.set_cookie_header("T", 3600, secure=True))
    r.check("login: clearing it sets a lifetime of zero", "Max-Age=0" in session.clear_cookie_header(False))

    safe = {"/": "/", "/radicale/alice/?a=1&b=2": "/radicale/alice/?a=1&b=2", "/x#frag": "/x#frag",
            "//evil.example/": "/", "https://evil.example/": "/", "/\\evil.example": "/", "": "/", None: "/",
            "/a\nSet-Cookie: x=1": "/", "/login": "/", "/login?next=/": "/", "/logout": "/", "relative": "/",
            "/" + "a" * 3000: "/"}
    bad = {k: session.safe_next(k) for k, v in safe.items() if session.safe_next(k) != v}
    r.check("login: after login only ever somewhere on this site (no open redirect, no header injection, no login loop)",
            not bad, bad)


def _page_checks(r):
    page = loginpage.render("/x?a=1&b=2", failed=False).decode()
    r.check("login: the page has a username and password field a password manager recognises",
            'autocomplete="username"' in page and 'autocomplete="current-password"' in page and 'type="password"' in page)
    r.check("login: it posts to /login and carries where to go afterwards",
            'method="post" action="/login"' in page and 'name="next" value="/x?a=1&amp;b=2"' in page)
    r.check("login: no error shown on a first visit, one on a failure",
            "login-error" not in page and "login-error" in loginpage.render("/", failed=True).decode())
    evil = loginpage.render('"><script>alert(1)</script>').decode()
    r.check("login: where to go is escaped, it came from a URL", "<script>alert" not in evil and "&lt;script&gt;" in evil)
    note = lambda lang: re.search(r'class="note">(\w+) accounts only', loginpage.render("/", accept_language=lang).decode()).group(1)
    r.check("login: it says Authorised or Authorized by the browser's language, Authorised when there is none",
            [note(l) for l in ("", "en-AU", "en-GB,en;q=0.9", "en-US,en;q=0.9", "en_us", "en-CA", "fr-CA", "de", "en-PH;q=0.8")]
            == ["Authorised", "Authorised", "Authorised", "Authorized", "Authorized", "Authorized", "Authorized", "Authorised", "Authorized"],
            [note(l) for l in ("", "en-AU", "en-GB,en;q=0.9", "en-US,en;q=0.9", "en_us", "en-CA", "fr-CA", "de", "en-PH;q=0.8")])
    r.check("login: the helper hands the browser's language to the page",
            b"Authorized accounts only" in _call(HELPER, "GET", "/login", {"Accept-Language": "en-US"})[2]
            and b"Authorised accounts only" in _call(HELPER, "GET", "/login", {"Accept-Language": "en-AU"})[2])
    r.check("login: it loads nothing and runs no script",
            "<script" not in page and "http://" not in page.replace("http://www.w3.org", "") and "https://" not in page)


def _helper_checks(r):
    status, headers, body = _call(HELPER, "GET", "/login")
    r.check("login: GET /login is the form, with a policy that stops framing and any outside load",
            status == 200 and b'id="login-form"' in body and "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")
            and headers.get("Cache-Control") == "no-store", (status, dict(headers)))

    status, headers, body = _login(h.TEST_USER, "wrong")
    r.check("login: a wrong password is a 401 with the form and a message, and no cookie",
            status == 401 and b"login-error" in body and "Set-Cookie" not in headers, status)
    status, headers, body = _login("", "")
    r.check("login: an empty form is refused the same way", status == 401 and "Set-Cookie" not in headers, status)
    status, _, _ = _call(HELPER, "POST", "/login", {"Content-Type": "application/x-www-form-urlencoded"}, b"x" * 5000)
    r.check("login: an oversized form is refused", status == 413, status)

    status, headers, _ = _login(h.TEST_USER, h.AUTH_PASSWORD)
    token = _cookie_of(headers)
    r.check("login: the right password is a redirect to the dashboard with a session cookie",
            status == 303 and headers.get("Location") == "/" and token and len(token) >= 40, (status, dict(headers)))
    r.check("login: not marked Secure over plain HTTP", "Secure" not in headers.get("Set-Cookie", ""))
    _, headers_tls, _ = _login(h.TEST_USER, h.AUTH_PASSWORD, extra={"X-Forwarded-Proto": "https"})
    r.check("login: marked Secure when nginx says it served HTTPS", "Secure" in headers_tls.get("Set-Cookie", ""))

    target = "/radicale/alice/?a=1&b=2"
    _, headers_n, _ = _login(h.TEST_USER, h.AUTH_PASSWORD, next_path=target)
    r.check("login: it lands where the person was going", headers_n.get("Location") == target, headers_n.get("Location"))
    _, headers_e, _ = _login(h.TEST_USER, h.AUTH_PASSWORD, next_path="//evil.example/")
    r.check("login: and never on another site", headers_e.get("Location") == "/", headers_e.get("Location"))
    status, headers_g, body_g = _call(HELPER, "GET", "/login?next=/a/b?c=1&d=2")
    r.check("login: the form carries the target as nginx wrote it, ? and & included",
            status == 200 and b'name="next" value="/a/b?c=1&amp;d=2"' in body_g, body_g[-300:])

    cookie = {"Cookie": f"{session.COOKIE_NAME}={token}"}
    status, headers, _ = _call(HELPER, "GET", "/check", cookie)
    r.check("login: the helper knows the cookie's owner, and that it was a cookie",
            status == 200 and headers.get("X-Authenticated-User") == h.TEST_USER and headers.get("X-Auth-Method") == "cookie",
            (status, dict(headers)))
    status, headers, _ = _call(HELPER, "GET", "/check", {**cookie, "Authorization": "Bearer an-apps-own-token"})
    r.check("login: an app's own Authorization header does not matter once the cookie is good",
            status == 200 and headers.get("X-Auth-Method") == "cookie", status)
    status, headers, _ = _call(HELPER, "GET", "/check", {**cookie, **h.auth_header("someoneelse")})
    r.check("login: the cookie decides who it is, not a Basic header beside it",
            headers.get("X-Authenticated-User") == h.TEST_USER, headers.get("X-Authenticated-User"))
    status, headers, _ = _call(HELPER, "GET", "/check", h.auth_header(h.TEST_USER))
    r.check("login: Basic still works for scripts and DAV clients, and is reported as Basic",
            status == 200 and headers.get("X-Auth-Method") == "basic", (status, dict(headers)))
    # A browser (it says so with Sec-Fetch-Mode) proves who it is by cookie alone. Its
    # Authorization header is the app's, so it is neither accepted nor tried as a password.
    tried = []
    real_password_ok = authcheck.password_ok
    authcheck.password_ok = lambda u, p: (tried.append(u), real_password_ok(u, p))[1]
    try:
        browser = {"Sec-Fetch-Mode": "cors"}
        status, _, _ = _call(HELPER, "GET", "/check", {**browser, **h.auth_header(h.TEST_USER)})
        r.check("login: a browser's Basic header is not a login, even with the right password", status == 401, status)
        status, _, _ = _call(HELPER, "GET", "/check", {**browser, **h.auth_header(h.TEST_USER, "an-apps-own-password")})
        r.check("login: and an app's own password is refused the same way", status == 401, status)
        r.check("login: neither was tried as a system password", tried == [], tried)
        status, headers, _ = _call(HELPER, "GET", "/check", {**browser, **cookie, **h.auth_header("radicaleuser", "apppass")})
        r.check("login: a browser with a good cookie gets in whatever Authorization it also sends",
                status == 200 and headers.get("X-Auth-Method") == "cookie", status)
        status, _, _ = _call(HELPER, "GET", "/check", {"Sec-Fetch-Mode": "navigate", "Cookie": f"{session.COOKIE_NAME}=stale", **h.auth_header("radicaleuser", "apppass")})
        r.check("login: a stale cookie plus an app's Basic is refused, and still not tried", status == 401 and tried == [], (status, tried))
        _call(HELPER, "GET", "/check", h.auth_header(h.TEST_USER, "wrong"))
        r.check("login: a script's Basic is still tried, so guessing it is still counted", tried == [h.TEST_USER], tried)
    finally:
        authcheck.password_ok = real_password_ok
    status, _, _ = _call(HELPER, "GET", "/check", {"Authorization": "Bearer nope"})
    r.check("login: a bearer token on its own is not a login", status == 401, status)
    status, _, _ = _call(HELPER, "GET", "/check", {"Cookie": f"{session.COOKIE_NAME}=forged-forged-forged"})
    r.check("login: a made-up cookie is refused", status == 401, status)
    status, _, _ = _call(HELPER, "GET", "/check", {"Cookie": f"{session.COOKIE_NAME}=forged", **h.auth_header(h.TEST_USER, "wrong")})
    r.check("login: a bad cookie with a bad password is refused", status == 401, status)

    status, _, _ = _call(HELPER, "POST", "/deprovision-app", {**cookie, "Content-Type": "application/json"}, b'{"app": "no-such-app-xyz"}')
    r.check("login: the provisioning endpoints accept the cookie as proof (refused for the app, not for the person)",
            status == 404, status)
    status, _, _ = _call(HELPER, "POST", "/deprovision-app", {"Content-Type": "application/json"}, b'{"app": "no-such-app-xyz"}')
    r.check("login: and refuse anyone with no proof", status == 401, status)

    status, headers, _ = _call(HELPER, "GET", "/login", cookie)
    r.check("login: the form for someone already signed in goes on to the dashboard", status == 303, status)

    # ---- the dashboard accepts the cookie, and says what it should when it does not.
    with urllib.request.urlopen(urllib.request.Request(h.URL + "config.json", headers=cookie), timeout=5) as resp:
        r.check("login: the dashboard itself accepts the session cookie alone", resp.status == 200)
    try:
        urllib.request.urlopen(urllib.request.Request(h.URL + "config.json", headers={"Cookie": f"{session.COOKIE_NAME}=forged"}), timeout=5)
        code, challenge = 200, None
    except urllib.error.HTTPError as e:
        code, challenge = e.code, e.headers.get("WWW-Authenticate")
    r.check("login: a dead session is a 401 that does not pop up a native password box", code == 401 and challenge is None, (code, challenge))

    # ---- Someone removed from the group is out at once, not when the session runs out.
    real = userprovision.user_in_group
    userprovision.user_in_group = lambda username, group=None: False
    try:
        status, _, _ = _call(HELPER, "GET", "/check", cookie)
    finally:
        userprovision.user_in_group = real
    r.check("login: leaving the group ends the session immediately", status == 401, status)

    # ---- Logout.
    status, headers, _ = _call(HELPER, "POST", "/logout", cookie)
    r.check("login: logout is a redirect to the form that clears the cookie",
            status == 303 and headers.get("Location") == "/login" and "Max-Age=0" in headers.get("Set-Cookie", ""), (status, dict(headers)))
    status, _, _ = _call(HELPER, "GET", "/check", cookie)
    r.check("login: and the old cookie no longer works, even if someone kept a copy", status == 401, status)
    status, _, _ = _call(HELPER, "GET", "/logout")
    r.check("login: logging out takes a POST, a link or image on another page cannot do it", status == 404, status)
    status, _, _ = _call(HELPER, "GET", "/nothing-here")
    r.check("login: unknown paths are 404", status == 404, status)


def _nginx_checks(r):
    for name in ("dwarvendash-http.conf", "dwarvendash-https.conf"):
        text = h.effective_nginx(name)
        r.check(f"login: {name} serves /login and /logout from the helper with no login required",
                all(re.search(rf"location = /{p} \{{\s+auth_request off;\s+proxy_pass http://127\.0\.0\.1:8091/{p};", text) for p in ("login", "logout")))
        r.check(f"login: {name} has the three outcomes for a request that is not signed in",
                re.search(r'map "\$http_sec_fetch_mode\|\$http_accept" \$dd_deny_kind \{', text)
                and "return 302 /login?next=$request_uri;" in text and "WWW-Authenticate" in text.split("location @auth_denied")[1])
        r.check(f"login: {name} passes the cookie to the check and records how the person signed in",
                "proxy_set_header Cookie $http_cookie;" in text and "auth_request_set $auth_method $upstream_http_x_auth_method;" in text)
        r.check(f"login: {name} logs failed form logins for fail2ban", '"~^401:::[^:]*:/login$" 1;' in text)
        _failed_login_map_checks(r, name, text)
        _deny_kind_checks(r, name, text)

    block = "\n".join(b for sig, b in appprovision.SHARED_MAPS if "dd_app_cookie" in sig)
    patterns = [m.replace("(?<", "(?P<") for m in re.findall(r'"~(.*?)"\s+', block)]
    values = re.findall(r'"~.*?"\s+(\S+?);', block)

    def stripped(cookie):
        # What nginx's map does: the first pattern that matches wins, none means unchanged.
        for pattern, value in zip(patterns, values):
            m = re.search(pattern, cookie)
            if m:
                g = m.groupdict()
                return re.sub(r"\$(\w+)", lambda x: g.get(x.group(1)) or "", value.strip('"'))
        return cookie
    cases = {"dwd_session=X": "", "a=1; dwd_session=X": "a=1", "dwd_session=X; b=2": "b=2",
             "a=1; dwd_session=X; b=2": "a=1; b=2", "a=1; b=2": "a=1; b=2", "xdwd_session=1; a=2": "xdwd_session=1; a=2",
             "dwd_session2=1": "dwd_session2=1", "a=dwd_session=1": "a=dwd_session=1"}
    bad = {c: stripped(c) for c, want in cases.items() if stripped(c) != want}
    r.check("login: the session cookie, and only it, is removed from what an app sees", len(patterns) == 2 and not bad, bad)

    pairs = dict(re.findall(r"\n\s+(\w+)\s+(\$?\S+?);", [b for sig, b in appprovision.SHARED_MAPS if "dd_app_authorization" in sig][0]))
    r.check("login: an app sees an Authorization header only after a cookie login",
            pairs.get("cookie") == "$http_authorization" and pairs.get("default") == '""', pairs)


def _deny_kind_checks(r, name, text):
    """
    Run the deny-kind map in a real nginx (a tiny server that answers with the variable) and ask it what each
    kind of unsigned request is. The case that was wrong: a browser over plain HTTP to an address or a name sends
    no Sec-Fetch-Mode (measured with Chromium), so a page navigation was offered the Basic box instead of the form.
    """
    block = re.search(r'map "\$http_sec_fetch_mode\|\$http_accept" \$dd_deny_kind \{.*?\n\}', text, re.S).group(0)
    work = tempfile.mkdtemp(prefix="dd-map-")
    port = 18093
    conf = os.path.join(work, "nginx.conf")
    open(conf, "w").write(f"pid {work}/nginx.pid;\nerror_log {work}/err.log;\nevents {{}}\nhttp {{\n"
                          f"access_log off;\n{block}\nserver {{ listen 127.0.0.1:{port}; location / {{ return 200 $dd_deny_kind; }} }}\n}}\n")
    proc = subprocess.Popen(["nginx", "-p", work, "-c", conf, "-g", "daemon off;"], stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        html = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        cases = {
            "a navigation over HTTPS (Sec-Fetch-Mode: navigate)": ({"Sec-Fetch-Mode": "navigate", "Accept": html}, "login"),
            "a navigation over plain HTTP (no Sec-Fetch-Mode, Accept asks for HTML)": ({"Accept": html}, "login"),
            "a script in a page (Sec-Fetch-Mode: cors)": ({"Sec-Fetch-Mode": "cors", "Accept": "*/*"}, "quiet"),
            "an image (Sec-Fetch-Mode: no-cors)": ({"Sec-Fetch-Mode": "no-cors", "Accept": "image/avif,image/*,*/*;q=0.8"}, "quiet"),
            "a navigation that also lists */* is still a navigation": ({"Sec-Fetch-Mode": "navigate", "Accept": "*/*"}, "login"),
            "curl (no Sec-Fetch-Mode, Accept */*)": ({"Accept": "*/*"}, "challenge"),
            "a DAV client (no Accept at all)": ({}, "challenge"),
            "a DAV client asking for XML": ({"Accept": "application/xml"}, "challenge"),
        }
        got = {}
        for label, (headers, want) in cases.items():
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers=dict({"Accept-Encoding": "identity"}, **headers))
            got[label] = (urllib.request.urlopen(req, timeout=5).read().decode(), want)
        r.check(f"login: {name} decides login, quiet 401 or Basic challenge by who is asking, in real nginx",
                all(g == w for g, w in got.values()), {k: v for k, v in got.items() if v[0] != v[1]})
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(work, ignore_errors=True)


def _failed_login_map_checks(r, name, text):
    """
    Evaluate the failed-login map the way nginx does (first matching pattern,
    else default) for each kind of request. The point is that an app's own
    Basic login, sent by a browser, is never a strike against the person.
    """
    block = re.search(r'map "([^"]+)" \$dd_login_failed \{(.*?)\n\}', text, re.S)
    key_fields = block.group(1).split(":")
    rules = [(re.compile(pat.replace("(?<", "(?P<")), val) for pat, val in re.findall(r'"~(.*?)"\s+(\d);', block.group(2))]

    def counted(status, auth_user, remote_user, fetch_mode, uri):
        values = {"$status": status, "$auth_user": auth_user, "$remote_user": remote_user,
                  "$http_sec_fetch_mode": fetch_mode, "$uri": uri}
        key = ":".join(values[f] for f in key_fields)
        return next((v for rx, v in rules if rx.search(key)), "0") == "1"

    cases = {
        "a script's wrong Basic password": (counted("401", "", "alice", "", "/x"), True),
        "a failed form login": (counted("401", "", "", "navigate", "/login"), True),
        "a browser's app login (fetch)": (counted("401", "", "radicaleuser", "cors", "/radicale/"), False),
        "a browser's app login (page load)": (counted("401", "", "radicaleuser", "navigate", "/radicale/"), False),
        "an anonymous browser being sent to the form": (counted("401", "", "", "navigate", "/x"), False),
        "a signed-in request": (counted("200", "alice", "alice", "", "/x"), False),
        "an app's own 401 after sign-in": (counted("401", "alice", "alice", "cors", "/app/"), False),
    }
    r.check(f"login: {name} counts script and form failures, never a browser's own app login",
            all(got == want for got, want in cases.values()), {k: g for k, (g, w) in cases.items() if g != w})


def _fail2ban_checks(r):
    text = open(os.path.join(h.ROOT, "fail2ban", "dwarvendash.conf")).read()
    lines = re.search(r"failregex\s*=(.*?)\nignoreregex", text, re.S).group(1).split("\n")
    regexes = [re.compile(l.strip().replace("<HOST>", r"(?P<host>\S+)")) for l in lines if l.strip()]
    log = {
        '203.0.113.5 - alice [11/Oct/2026:19:20:01 +0930] "GET /config.json HTTP/1.1" 401': True,
        '203.0.113.6 - - [11/Oct/2026:19:20:02 +0930] "POST /login HTTP/1.1" 401': True,
        '203.0.113.7 - - [11/Oct/2026:19:20:03 +0930] "POST /login?next=/x HTTP/2.0" 401': True,
        '203.0.113.8 - - [11/Oct/2026:19:20:04 +0930] "GET /config.json HTTP/1.1" 401': False,
        '203.0.113.9 - - [11/Oct/2026:19:20:05 +0930] "POST /other HTTP/1.1" 401': False,
        '203.0.113.9 - - [11/Oct/2026:19:20:06 +0930] "GET /login HTTP/1.1" 200': False,
    }
    got = {line: any(rx.search(line) for rx in regexes) for line in log}
    r.check("login: fail2ban counts a rejected Basic login and a failed form login, and nothing else",
            got == log, {k: v for k, v in got.items() if v != log[k]})


def run(browser, r):
    _store_checks(r)
    _page_checks(r)
    _helper_checks(r)
    _nginx_checks(r)
    _fail2ban_checks(r)

    # ---- The Log out button, in a real page. The routes /login and /logout belong
    # to nginx in production, so here they are answered by the test.
    h.reset_user_config()
    page = h.new_page(browser)
    seen = []
    page.route("**/logout", lambda route: (seen.append(route.request.method), route.fulfill(status=303, headers={"Location": "/login"}))[1])
    page.route("**/login", lambda route: route.fulfill(status=200, content_type="text/html", body="<title>sign in</title>signed out page"))
    h.open_dashboard(page)
    r.check("login: a Log out button sits in the title bar, beside Modify",
            page.locator("header.brand .brand-actions #logout-button").count() == 1 and page.locator("header.brand .brand-actions #launcher-modify-toggle").count() == 1)
    h.shot(page, "login_01_title_bar")
    page.click("#logout-button")
    page.wait_for_url("**/login")
    r.check("login: it ends the session with a POST to /logout and goes to the form", seen == ["POST"] and page.url.endswith("/login"), (seen, page.url))
    page.context.close()

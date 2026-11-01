"""
App status dots: optional, off by default, and only ever the user's own instances.

Fake apps are plain listening sockets that count connections, so the
checks can prove both directions: a listening instance shows as running,
a dead one as not running, and with the option off nothing connects at all.
"""

import json
import os
import socket
import threading
import time
import urllib.request

import dd_harness as h

import sys
sys.path.insert(0, h.APP_DIR)
import appprovision  # noqa: E402
import appstatus  # noqa: E402


class Listener:
    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.alive:
            try:
                conn, _ = self.sock.accept()
                self.connections += 1
                conn.close()
            except OSError:
                return

    def stop(self):
        self.alive = False
        self.sock.close()


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _first_event():
    req = h.request("/events")
    with urllib.request.urlopen(req, timeout=10) as resp:
        for line in resp:
            if line.startswith(b"data:"):
                return json.loads(line[5:])


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def run(browser, r):
    up, other, lost = Listener(), Listener(), _closed_port()
    try:
        # Unit level, against a patched port map directory.
        saved = appprovision.PORT_MAP_DIR
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            appprovision.PORT_MAP_DIR = tmp
            try:
                _write(os.path.join(tmp, "a.map"), f"me {up.port};\nyou {other.port};\n")
                _write(os.path.join(tmp, "b.map"), f"me {lost};\n")
                _write(os.path.join(tmp, "c.map"), f"you {other.port};\n")
                got = appstatus.instance_status("me")
                r.check("status: reports the user's own instances, up and down", got == {"a": True, "b": False}, got)
                r.check("status: another user's instance is never reported", "c" not in got and appstatus.instance_status("nobody") == {})
            finally:
                appprovision.PORT_MAP_DIR = saved

        # Real dashboard.
        _write(os.path.join(h.PORT_MAP_DIR, "upapp.map"), f"{h.TEST_USER} {up.port};\nsomeoneelse {up.port};\n")
        _write(os.path.join(h.PORT_MAP_DIR, "downapp.map"), f"{h.TEST_USER} {lost};\nsomeoneelse {up.port};\n")
        h.reset_user_config()
        cfg = h.user_config_path()
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        _write(cfg, json.dumps({"launcher": [{"group": "Apps", "links": [
            {"title": "upapp", "url": "/upapp/", "type": "app"},
            {"title": "downapp", "url": "/downapp/", "type": "app"},
            {"title": "Site", "url": "https://example.com", "type": "bookmark"}]}]}))

        page = h.new_page(browser)
        h.open_dashboard(page, settle=1)
        time.sleep(1)
        baseline = up.connections  # loading the page fetches icons, that is not status polling
        time.sleep(4)
        r.check("status: off by default, no dots", page.locator(".status-dot").count() == 0)
        r.check("status: off by default, the stream carries no app status", "apps" not in _first_event())
        r.check("status: off by default, nothing connects to the apps while the page sits open", up.connections == baseline, (baseline, up.connections))

        h.enter_modify(page)
        page.locator(".status-toggle input").check()
        time.sleep(3.5)
        r.check("status: dots on app buttons only, not bookmarks",
                page.eval_on_selector_all(".status-dot", "e => e.map(x => x.dataset.app)") == ["upapp", "downapp"])
        state = lambda app: page.eval_on_selector(f'.status-dot[data-app="{app}"]', "e => [e.className, e.title]")
        box = lambda app: page.eval_on_selector(f'.status-dot[data-app="{app}"]', "e => { const r = e.getBoundingClientRect(); return [r.width, r.height, getComputedStyle(e).backgroundImage]; }")
        up_box, down_box = box("upapp"), box("downapp")
        r.check("status: the dots are really visible (a few pixels across) and green vs red",
                up_box[0] >= 6 and up_box[1] >= 6 and up_box[2] != down_box[2], (up_box, down_box))
        r.check("status: a listening instance shows running", state("upapp") == ["status-dot up", "running"], state("upapp"))
        r.check("status: a dead instance shows not running, even if someone else's is up",
                state("downapp") == ["status-dot down", "not running"], state("downapp"))
        r.check("status: the link text is still just the title",
                page.eval_on_selector_all(".launcher-link-item a", "e => e.map(x => x.textContent)") == ["upapp", "downapp", "Site"])
        r.check("status: choice saved", h.read_user_config().get("app_status") is True)
        r.check("status: each lamp is a cell of its own after the app's button, not inside it",
                page.locator(".launcher-link-item a .status-dot").count() == 0 and page.locator(".launcher-link-item > .status-cell .status-dot").count() == 2)
        page.evaluate("setLayout({...normalizeLayout(currentConfig.layout), apps: 'list'})")
        time.sleep(1)
        cells = page.eval_on_selector_all(".status-cell", "e => e.map(x => Math.round(x.getBoundingClientRect().right))")
        names = page.eval_on_selector_all(".launcher-link-item a", "e => e.filter(x => x.parentNode.querySelector('.status-cell')).map(x => x.textContent)")
        r.check("status: in a list the lamps line up down the right, whatever the length of the names",
                len(set(cells)) == 1 and len(cells) == 2 and len(set(map(len, names))) == 2, (cells, names))
        h.shot(page, "status_03_list_cells")
        page.evaluate("setLayout({...normalizeLayout(currentConfig.layout), apps: 'flow'})")
        time.sleep(0.5)
        bare = page.eval_on_selector_all("button, select, label, input[type=text]", "e => e.filter(x => !(x.title || '').trim()).map(x => x.className || x.tagName)")
        r.check("status: every button, menu, toggle and field has a hover tip", bare == [], bare)
        tips = page.eval_on_selector_all(".status-style-btn", "e => e.map(x => [x.textContent, x.title])")
        r.check("status: the lamps and text choice is short on the button and spelled out on hover",
                [t[0] for t in tips] == ["Lamps", "Text"] and "green" in tips[0][1] and "U for running" in tips[1][1], tips)
        h.shot(page, "status_01_dots")

        # The letter version, for anyone who cannot tell red from green.
        page.locator(".status-style-btn", has_text="Text").click()
        time.sleep(1.5)
        letters = page.eval_on_selector_all(".status-dot", "e => e.map(x => [x.textContent, x.className, getComputedStyle(x).backgroundColor])")
        r.check("status: with letters on, a running app shows U and a stopped one D, no lamp",
                [l[0] for l in letters] == ["U", "D"] and all("letter" in l[1] and l[2] == "rgba(0, 0, 0, 0)" for l in letters), letters)
        r.check("status: letters saved", h.read_user_config().get("status_letters") is True)
        h.shot(page, "status_02_letters")
        page.locator(".status-style-btn", has_text="Lamps").click()
        time.sleep(1.5)
        r.check("status: letters off brings the lamps back and no text", page.eval_on_selector_all(".status-dot", "e => e.map(x => x.textContent)") == ["", ""])

        # A stream that stalls without an error: readings stop arriving, the watchdog opens it again.
        page.evaluate("() => { window.__es = 0; window.__mute = false; const R = window.EventSource; window.EventSource = class extends R { constructor(u) { super(u); window.__es++; }"
                      " set onmessage(fn) { super.onmessage = (e) => { if (!window.__mute) fn(e); }; } }; reconnectEvents(); }")
        time.sleep(2)
        n0 = page.evaluate("window.__es")
        r.check("status: with readings arriving the watchdog leaves the stream alone", page.evaluate("window.__es") == n0 == 1, n0)
        page.evaluate("window.__mute = true")
        time.sleep(7.5)
        r.check("status: after five silent seconds it opens the stream again", page.evaluate("window.__es") > n0, page.evaluate("window.__es"))
        page.evaluate("window.__mute = false")
        time.sleep(2.5)
        before = page.evaluate("Date.now() - lastReading")
        r.check("status: and the readings come in again afterwards", before < 3000, before)

        up.stop()
        time.sleep(3.5)
        r.check("status: an instance that stops turns red within a few seconds", state("upapp")[0] == "status-dot down", state("upapp"))

        page.reload()
        page.wait_for_selector("#meters .panel")
        time.sleep(3)
        r.check("status: dots are there after a reload, outside modify mode", page.locator(".status-dot").count() == 2)

        # Tapping a lamp resets it (the startup sequence, when that is on) and never opens the app.
        url = page.url
        page.locator('.status-dot[data-app="downapp"]').click()
        time.sleep(0.3)
        r.check("status: tapping a lamp changes nothing visible with the startup sweep off, and does not open the app",
                page.url == url and page.eval_on_selector('.status-dot[data-app="downapp"]', "e => e.className") == "status-dot down", page.url)
        page.evaluate("() => { window.__es = 0; const R = window.EventSource; window.EventSource = class extends R { constructor(u) { super(u); window.__es++; } }; }")
        page.locator('.status-dot[data-app="downapp"]').click()
        time.sleep(0.3)
        r.check("status: tapping a lamp reconnects the live stream", page.evaluate("window.__es") == 1, page.evaluate("window.__es"))
        page.evaluate("window.__old = Object.values(panelViews)[0].view; sweeping.add(Object.values(panelViews)[0].cfg.id)")
        page.locator("#meters .panel").first.click()
        time.sleep(0.5)
        r.check("status: tapping a panel reconnects, rebuilds its display from nothing and clears a stuck sweep",
                page.evaluate("[window.__es, Object.values(panelViews)[0].view !== window.__old, sweeping.size]") == [2, True, 0],
                page.evaluate("[window.__es, Object.values(panelViews)[0].view !== window.__old, sweeping.size]"))
        page.evaluate("currentConfig.startup_sweep = true")
        page.evaluate("""() => { window.__seq = []; const d = document.querySelector('.status-dot[data-app="downapp"]');
          new MutationObserver(() => { const c = d.className; if (window.__seq[window.__seq.length - 1] !== c) window.__seq.push(c); }).observe(d, {attributes: true}); }""")
        page.locator('.status-dot[data-app="downapp"]').click()
        time.sleep(2.0)
        seq = page.evaluate("window.__seq")
        r.check("status: with the sweep on a tap runs that lamp off, green, red, off, then its real state",
                seq[-5:] == ["status-dot", "status-dot up", "status-dot down", "status-dot", "status-dot down"] or seq == ["status-dot", "status-dot up", "status-dot down", "status-dot"], seq)
        r.check("status: and still did not open the app", page.url == url, page.url)
        page.locator("#meters .panel .panel-body, #meters .panel").first.click()
        time.sleep(0.2)
        r.check("status: tapping a panel runs its own startup sequence", page.evaluate("sweeping.size") == 1)
        time.sleep(4)
        r.check("status: and it ends on the real readings", page.evaluate("sweeping.size") == 0)
        page.evaluate("currentConfig.startup_sweep = false")

        h.enter_modify(page)
        page.locator(".status-toggle input").uncheck()
        time.sleep(1)
        r.check("status: switching off removes the dots", page.locator(".status-dot").count() == 0)
        r.check("status: off is saved", h.read_user_config().get("app_status") is False)
        h.finish_page(r, page, "status")
        page.context.close()
    finally:
        up.stop()
        other.stop()
        for n in ("upapp.map", "downapp.map"):
            if os.path.exists(os.path.join(h.PORT_MAP_DIR, n)):
                os.remove(os.path.join(h.PORT_MAP_DIR, n))

"""
Shared test harness for the DwarvenDash browser suite.

One job: everything that is not a test. Starting and stopping the
server, the throwaway system user it needs for saving config, the
browser, and result bookkeeping. Test modules import from here and
contain only checks.

Why a real system user: saving a config needs a real account (userconfig
resolves the home directory with pwd). So the suite creates a throwaway
account and removes it at the end. This needs root.

Who is calling: the server believes credentials, not headers. In
production it asks the PAM helper (authcheck.py) whether an Authorization
header is genuine. Here a small stand-in for that helper runs on a test
port and accepts any name with the password "test", so every request in
the suite carries real Basic credentials, exactly as a browser behind
nginx would, and the code path under test is the production one.
"""

import base64
import http.server
import json
import os
import pwd
import shutil
import subprocess
import tempfile
import sys
import threading
import time
import urllib.error
import urllib.request

import fakehost

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
PORT = int(os.environ.get("DD_TEST_PORT", "18090"))
URL = f"http://127.0.0.1:{PORT}/"
AUTH_PORT = int(os.environ.get("DD_TEST_AUTH_PORT", "18091"))
AUTH_PASSWORD = "test"
AUTH_CACHE_SECONDS = 2
TEST_USER = os.environ.get("DD_TEST_USER", "ddtest")
PORT_MAP_DIR = tempfile.mkdtemp(prefix="dd-ports-")
# The server reads its host numbers from this fake tree, see fakehost.py.
HOST_DIR = fakehost.build()
# The nvidia-smi the server runs. A test writes a script here to give the machine a GPU, and removes it to take it away.
SMI_DIR = tempfile.mkdtemp(prefix="dd-smi-")
FAKE_SMI = os.path.join(SMI_DIR, "nvidia-smi")
# The themes the server reads. A copy of the shipped ones, so a test can drop
# a file in and take it out again without touching the real directory.
THEME_DIR = tempfile.mkdtemp(prefix="dd-themes-")
SHIPPED_THEME_DIR = os.path.join(APP_DIR, "themes")
SHOT_DIR = os.environ.get("DD_TEST_SHOTS", os.path.join(ROOT, "tests", "screenshots"))

DEFAULT_PANELS = ["cpu-composite", "mem", "net", "disk"]
PANEL_EL = {
    "cpu-composite": "cpu-panel",
    "cpu-cores": "cpu-cores-panel",
    "mem": "mem-panel",
    "net": "net-panel",
    "disk": "disk-panel",
    "load": "load-panel",
    "cpu-freq": "cpu-freq-panel",
    "fans": "fans-panel",
    "temps": "temps-panel",
    "host": "host-panel",
    "gpu": "gpu-panel",
}
PANEL_LABEL = {
    "cpu-composite": "Composite-CPU",
    "cpu-cores": "Individual-Cores",
    "mem": "MEM",
    "net": "NET",
    "disk": "DISK",
    "load": "Backlog",
    "cpu-freq": "CPU-Freq",
    "fans": "FANS",
    "temps": "TEMPS",
    "host": "HOST",
    "gpu": "GPU",
}
CHART_CANVAS = {"cpu-composite": "cpu-canvas", "mem": "mem-canvas", "net": "net-canvas"}


class Results:
    """Collects PASS/FAIL lines. One place that knows how a check is reported."""

    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        tail = f" :: {detail}" if detail != "" else ""
        print(("PASS " if ok else "FAIL ") + name + tail, flush=True)
        return bool(ok)

    def failures(self):
        return [r for r in self.rows if not r[1]]


def effective_nginx(name):
    """A stock nginx site config as nginx reads it: the include of the shared sign-in wall replaced by the wall."""
    text = open(os.path.join(ROOT, "nginx", name)).read()
    gate = open(os.path.join(ROOT, "nginx", "dwarvendash-gate.conf")).read()
    return text.replace("include /etc/nginx/dwarvendash-gate.conf;", gate)


def user_config_path():
    return os.path.join(pwd.getpwnam(TEST_USER).pw_dir, ".config", "dwarvendash", "config.json")


def read_user_config():
    with open(user_config_path()) as f:
        return json.load(f)


def user_theme_css_path():
    return os.path.join(os.path.dirname(user_config_path()), "theme.css")


def reset_user_config():
    """Back to a never-configured user, so every module starts from defaults."""
    for path in (user_config_path(), user_theme_css_path()):
        if os.path.exists(path):
            os.remove(path)


def reset_themes():
    """The themes directory as shipped: the five files, nothing else."""
    shutil.rmtree(THEME_DIR, ignore_errors=True)
    shutil.copytree(SHIPPED_THEME_DIR, THEME_DIR)


def write_theme(filename, text):
    with open(os.path.join(THEME_DIR, filename), "w") as f:
        f.write(text)


def _require_root():
    if os.geteuid() != 0:
        sys.exit("The suite creates a throwaway system user, run it as root.")


def _create_user():
    try:
        pwd.getpwnam(TEST_USER)
        return False
    except KeyError:
        subprocess.run(["useradd", "-m", TEST_USER], check=True)
        return True


def _remove_user():
    subprocess.run(["userdel", "-r", TEST_USER], stderr=subprocess.DEVNULL)


AUTH_CALLS = []  # one entry per question the server asked the stand-in helper


sys.path.insert(0, APP_DIR)
import authcheck  # noqa: E402
import userprovision  # noqa: E402


class _TrackedAuth(authcheck.Handler):
    """The real login helper, only recording what it was asked (AUTH_CALLS)."""

    def _who(self):
        result = super()._who()
        if self.path == "/check":
            AUTH_CALLS.append(result[0])
        return result


def _stand_in_for_the_machine():
    """
    The helper's code is the production code. Only the three things that need a
    real system are replaced: PAM (any name with the password "test"), the
    group check (everyone is allowed) and first-time folder setup (nothing to
    set up). Done in this process, the helper runs here as a thread.
    """
    authcheck.password_ok = lambda username, password: password == AUTH_PASSWORD
    userprovision.user_in_group = lambda username, group=None: True
    userprovision.ensure_user_provisioned = lambda username: None


def auth_header(user=None, password=AUTH_PASSWORD):
    """The Authorization header a browser would send for this user."""
    token = base64.b64encode(f"{user or TEST_USER}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def request(path, user=None, data=None, method=None, headers=None, timeout=5):
    """A urllib Request carrying credentials. user=False sends none at all."""
    merged = {} if user is False else auth_header(user)
    merged.update(headers or {})
    return urllib.request.Request(URL.rstrip("/") + path, data=data, headers=merged, method=method)


def _wait_for_server(proc, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("server.py exited early, see its output")
        try:
            urllib.request.urlopen(URL, timeout=1).close()
            return
        except urllib.error.HTTPError:
            return  # it answered, even if only to ask for credentials
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("server.py did not answer in time")


class Environment:
    """Context manager: throwaway user + standalone server. Cleans up either way."""

    def __enter__(self):
        _require_root()
        self.created_user = _create_user()
        reset_user_config()
        reset_themes()
        _stand_in_for_the_machine()
        authcheck.SESSIONS = authcheck.session.SessionStore()
        self.auth = http.server.ThreadingHTTPServer(("127.0.0.1", AUTH_PORT), _TrackedAuth)
        threading.Thread(target=self.auth.serve_forever, daemon=True).start()
        env = dict(os.environ, DWARVENDASH_PORT=str(PORT), PYTHONDONTWRITEBYTECODE="1",
                   DWARVENDASH_PORT_MAP_DIR=PORT_MAP_DIR, DWARVENDASH_HOST_ROOT=HOST_DIR, DWARVENDASH_NVIDIA_SMI=FAKE_SMI,
                   DWARVENDASH_THEME_DIR=THEME_DIR,
                   DWARVENDASH_AUTHCHECK_URL=f"http://127.0.0.1:{AUTH_PORT}",
                   DWARVENDASH_AUTH_CACHE_SECONDS=str(AUTH_CACHE_SECONDS))
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(APP_DIR, "server.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _wait_for_server(self.proc)
        return self

    def __exit__(self, *exc):
        self.auth.shutdown()
        shutil.rmtree(PORT_MAP_DIR, ignore_errors=True)
        shutil.rmtree(THEME_DIR, ignore_errors=True)
        shutil.rmtree(SMI_DIR, ignore_errors=True)
        fakehost.destroy(HOST_DIR)
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if self.created_user:
            _remove_user()
        return False


BROWSERS = ("chromium", "firefox", "webkit")


def launch_browser(playwright):
    """
    DD_BROWSER picks the engine (chromium by default, or firefox, webkit).
    DD_BROWSER_PATH points at a Playwright build of it when Playwright cannot
    find its own; DD_CHROMIUM is the older name for the same thing.
    """
    name = os.environ.get("DD_BROWSER", "chromium")
    if name not in BROWSERS:
        sys.exit(f"DD_BROWSER must be one of {BROWSERS}, not {name!r}")
    exe = os.environ.get("DD_BROWSER_PATH") or (os.environ.get("DD_CHROMIUM") if name == "chromium" else None)
    if not exe and name == "chromium" and os.path.exists("/opt/pw-browsers/chromium"):
        exe = "/opt/pw-browsers/chromium"
    kwargs = {"executable_path": exe} if exe else {}
    return getattr(playwright, name).launch(**kwargs)


def new_page(browser, width=1200, height=1000, color_scheme=None, locale="en-AU"):
    """A page acting as TEST_USER, with console errors and failed requests recorded."""
    kwargs = {"viewport": {"width": width, "height": height}, "locale": locale,
              "extra_http_headers": auth_header(TEST_USER)}
    if color_scheme:
        kwargs["color_scheme"] = color_scheme
    ctx = browser.new_context(**kwargs)
    page = ctx.new_page()
    page.dd_errors = []
    page.on("pageerror", lambda e: page.dd_errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: page.dd_errors.append(f"console: {m.text}") if m.type == "error" else None)
    return page


def open_dashboard(page, settle=2.5):
    page.goto(URL)
    page.wait_for_selector("#meters .panel")
    time.sleep(settle)


def shot(page, name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    page.screenshot(path=os.path.join(SHOT_DIR, name + ".png"))


def enter_modify(page):
    if page.inner_text("#launcher-modify-toggle").strip() == "Modify":
        page.click("#launcher-modify-toggle")
        time.sleep(0.4)


def panel_order(page):
    return page.eval_on_selector_all("#meters > .panel", "els => els.map(e => e.id)")


def canvas_state(page, canvas_id):
    """Size on screen, backing size, and count of painted pixels."""
    return page.evaluate("""(cid) => {
      const c = document.getElementById(cid); if (!c) return null;
      const r = c.getBoundingClientRect();
      let painted = 0;
      if (c.width > 0 && c.height > 0) {
        const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        for (let i = 3; i < d.length; i += 4) if (d[i] > 0) painted++;
      }
      return {w: c.width, h: c.height, cw: Math.round(r.width), ch: Math.round(r.height), painted};
    }""", canvas_id)


def canvas_signature(page, canvas_id):
    """Cheap hash of the canvas pixels, to prove it changes over time."""
    return page.evaluate("""(cid) => {
      const c = document.getElementById(cid);
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let s = 0; for (let i = 0; i < d.length; i += 7) s = (s * 31 + d[i]) | 0; return s;
    }""", canvas_id)


def chart_is_live(state):
    return bool(state) and state["w"] > 0 and state["h"] > 0 and state["painted"] > 0


def finish_page(results, page, label):
    """Every page must end with zero console or page errors."""
    results.check(f"{label}: no console or page errors", not page.dd_errors, page.dd_errors[:5])

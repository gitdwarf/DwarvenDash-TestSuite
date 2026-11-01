"""
Stopping an instance must stop the whole thing.

Many apps start through a wrapper script that runs the real program as a
child (Jackett's own launcher does exactly that). Stopping by signalling
one pid used to kill the wrapper and leave the program running, orphaned,
holding its port, so a re-add could not start. No browser here: real
processes, started and stopped through the real generated rc script.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import appprovision  # noqa: E402

APP = "ddtreeapp"

PROGRAM = """#!/usr/bin/env python3
import socket, sys, time
port = [int(a.split("=")[1]) for a in sys.argv if a.startswith("--Port=")][0]
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", port)); s.listen(5)
time.sleep(3600)
"""

# The shape of Jackett's real launcher: the program is a CHILD of this script.
LAUNCHER = """#!/bin/sh
DIR="$(dirname "$(readlink -f "$0")")"
"$DIR/program" --NoRestart "$@"
exit $?
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _running(marker):
    out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines() if marker in line and "grep" not in line)


def _wait(cond, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


def _rc(tmp, port, user):
    path = os.path.join(tmp, f"rc.dwarvendash-{APP}-{user}")
    with open(path, "w") as f:
        f.write(appprovision.SYSVINIT_RC_TEMPLATE.format(
            app=APP, username=user, exec_start=f"/bin/sh {tmp}/launcher.sh --Port={port}"))
    os.chmod(path, 0o755)
    return path


def _old_style_rc(path):
    """The stop this module used to generate: one pid, nothing waited for."""
    text = open(path).read()
    start = text.index("stop() {")
    end = text.index("case \"$1\"")
    old = 'stop() {\n    if [ -f "$PIDFILE" ]; then\n        kill "$(cat "$PIDFILE")" 2>/dev/null\n        rm -f "$PIDFILE"\n    fi\n}\n\n'
    with open(path, "w") as f:
        f.write(text[:start] + old + text[end:])


def _cleanup(marker, user):
    subprocess.run(["pkill", "-f", marker], capture_output=True)
    for p in (f"/var/run/dwarvendash-{APP}-{user}.pid", f"/var/log/dwarvendash-{APP}-{user}.log"):
        if os.path.exists(p):
            os.remove(p)


def run(browser, r):
    user = h.TEST_USER
    tmp = tempfile.mkdtemp(prefix="ddtree-")
    os.chmod(tmp, 0o755)
    marker = tmp
    try:
        for name, body in (("program", PROGRAM), ("launcher.sh", LAUNCHER)):
            with open(os.path.join(tmp, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(tmp, name), 0o755)

        # ---- The generated stop leaves nothing behind. ---------------------
        port = _free_port()
        rc = _rc(tmp, port, user)
        subprocess.run([rc, "start"], capture_output=True)
        r.check("stoptree: the wrapped program starts and listens", _wait(lambda: _listening(port)))
        r.check("stoptree: it really is a wrapper with a child",
                _running(f"{tmp}/launcher.sh") >= 1 and _running(f"{tmp}/program") >= 1)
        subprocess.run([rc, "stop"], capture_output=True)
        r.check("stoptree: stop leaves no process running", _wait(lambda: _running(marker) == 0),
                subprocess.run(["ps", "-eo", "pid,ppid,args"], capture_output=True, text=True).stdout[-400:])
        r.check("stoptree: and the port is free again", _wait(lambda: not _listening(port)))
        subprocess.run([rc, "start"], capture_output=True)
        r.check("stoptree: starting again on the same port works", _wait(lambda: _listening(port)))
        subprocess.run([rc, "stop"], capture_output=True)
        _wait(lambda: _running(marker) == 0)
        r.check("stoptree: stop with nothing running is harmless",
                subprocess.run([rc, "stop"], capture_output=True).returncode == 0)

        # ---- Removal cleans up even after an OLD generated script. ---------
        port = _free_port()
        rc = _rc(tmp, port, user)
        _old_style_rc(rc)
        subprocess.run([rc, "start"], capture_output=True)
        _wait(lambda: _listening(port))
        saved = (appprovision.SYSVINIT_RC_DIR, appprovision.RC_LOCAL_PATH)
        appprovision.SYSVINIT_RC_DIR = tmp
        appprovision.RC_LOCAL_PATH = os.path.join(tmp, "rc.local")
        open(appprovision.RC_LOCAL_PATH, "w").write("#!/bin/sh\n")
        try:
            appprovision.remove_init_artifact(APP, user, "sysvinit")
        finally:
            appprovision.SYSVINIT_RC_DIR, appprovision.RC_LOCAL_PATH = saved
        r.check("stoptree: removing an instance made by an older version leaves nothing running",
                _wait(lambda: _running(marker) == 0 and not _listening(port)))
        r.check("stoptree: its script and pidfile are gone",
                not os.path.exists(rc) and not os.path.exists(f"/var/run/dwarvendash-{APP}-{user}.pid"))

        # ---- Stopping a tree is careful about what it signals. -------------
        r.check("stoptree: init, none and a missing pid give an empty tree, never everything",
                all(appprovision.process_tree(x) == [] for x in (None, 0, 1, 2 ** 22 + 12345)))

        child = subprocess.Popen(["sh", "-c", "sleep 30 & wait"])
        time.sleep(0.5)
        tree = appprovision.process_tree(child.pid)
        r.check("stoptree: the tree holds the process and what it started", len(tree) >= 2, str(tree))

        bystander = subprocess.Popen(["sleep", "30"])
        try:
            stale = [(bystander.pid, "1")]  # right pid, wrong start time: a reused pid
            appprovision.stop_process_tree(stale, wait_seconds=1)
            r.check("stoptree: a pid that no longer is the same process is left alone", bystander.poll() is None)
        finally:
            bystander.kill()
            bystander.wait()

        appprovision.stop_process_tree(tree, wait_seconds=2)
        child.wait(timeout=5)
        r.check("stoptree: stopping a tree stops it all",
                _wait(lambda: not any(appprovision._still_running(p, t) for p, t in tree), 5))

        stubborn = subprocess.Popen(["/bin/sh", "-c", "trap '' TERM; while :; do sleep 1; done"])
        time.sleep(0.5)
        t0 = time.time()
        appprovision.stop_process_tree(appprovision.process_tree(stubborn.pid), wait_seconds=1)
        gone = _wait(lambda: stubborn.poll() is not None, 5)
        r.check("stoptree: a process that ignores TERM is killed after the wait", gone, f"{time.time() - t0:.1f}s")
        if not gone:
            stubborn.kill()
    finally:
        _cleanup(marker, user)
        shutil.rmtree(tmp, ignore_errors=True)

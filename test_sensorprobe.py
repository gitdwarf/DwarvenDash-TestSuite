"""
tools/sensor-probe.sh against a throwaway hwmon tree: it must read every input, say which one followed the CPU, and
call a reading of 127C or more implausible. The load it applies is real but the test shortens it to two seconds.
"""

import os
import subprocess
import tempfile
import threading
import time

import dd_harness as h

SCRIPT = os.path.join(h.ROOT, "tools", "sensor-probe.sh")


def _write(root, path, text):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text + "\n")


def _shells():
    """How many processes are called sh: the probe's busy loops are subshells of sh, so none may be left over."""
    return int(subprocess.run(["pgrep", "-xc", "sh"], capture_output=True, text=True).stdout.strip() or 0)


def run(browser, r):
    shells_before = _shells()
    with tempfile.TemporaryDirectory() as root:
        _write(root, "hwmon0/name", "coretemp")
        _write(root, "hwmon0/temp1_input", "40000")
        _write(root, "hwmon0/temp1_label", "Package id 0")
        _write(root, "hwmon1/name", "it8628")
        _write(root, "hwmon1/temp1_input", "39000")
        _write(root, "hwmon1/temp1_type", "4")
        _write(root, "hwmon1/temp2_input", "127000")
        _write(root, "hwmon1/temp3_input", "30000")

        def warm():
            time.sleep(1)
            _write(root, "hwmon0/temp1_input", "52000")
            _write(root, "hwmon1/temp1_input", "41000")
            _write(root, "hwmon1/temp3_input", "40000")
        threading.Thread(target=warm).start()
        done = subprocess.run(["sh", SCRIPT, "2"], capture_output=True, text=True, timeout=30, env=dict(os.environ, HWMON_ROOT=root))
        rows = {tuple(line.split()[:2]): line for line in done.stdout.splitlines()[2:] if line.strip()}
        r.check("probe: it exits cleanly and lists every input", done.returncode == 0 and len(rows) == 4, done.stdout + done.stderr)
        r.check("probe: the input that rose with the CPU is called the CPU, a small rise is not",
                "the CPU" in rows[("it8628", "temp3")] and "a little" in rows[("it8628", "temp1")], done.stdout)
        r.check("probe: 127C is called not plausible", "not a plausible" in rows[("it8628", "temp2")], rows[("it8628", "temp2")])
        r.check("probe: an input's own type is shown", " 4 " in rows[("it8628", "temp1")], rows[("it8628", "temp1")])
        empty = tempfile.mkdtemp()
        none = subprocess.run(["sh", SCRIPT, "1"], capture_output=True, text=True, timeout=30, env=dict(os.environ, HWMON_ROOT=empty))
        r.check("probe: no sensors is said plainly and is an error", none.returncode == 1 and "No temperature inputs" in none.stdout, none.stdout)
        os.rmdir(empty)
        shells_after = _shells()
        r.check("probe: the load it started is gone", shells_after == shells_before, (shells_before, shells_after))

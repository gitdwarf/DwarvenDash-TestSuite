"""
sysvinit detection of a stale system-wide service.

No browser here: this exercises appprovision directly against fake rc
scripts and boot runner files in a temp directory, by pointing the
module's path constants at it. Nothing real on the box is touched.

The cases that matter most:
- DwarvenDash's own per-user rc.dwarvendash-<app>-<user> lines sit in
  rc.local too, and must never make the ORIGINAL look enabled.
- A script with no `status` handler must never be executed during
  detection (running an unknown script with an arbitrary argument can
  start the service instead of reporting on it).
"""

import os
import stat
import tempfile

import dd_harness as h

# appprovision lives in app/, not tests/.
import sys
sys.path.insert(0, h.APP_DIR)
import appprovision  # noqa: E402


def _script(path, body, executable=True):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    mode = 0o755 if executable else 0o644
    os.chmod(path, mode)
    return path


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def run(browser, r):
    saved = (appprovision.SYSVINIT_BOOT_RUNNERS, appprovision.SYSVINIT_RUNLEVEL_DIR_GLOBS)
    with tempfile.TemporaryDirectory() as tmp:
        rc_local = os.path.join(tmp, "rc.local")
        rc_m = os.path.join(tmp, "rc.M")
        runlevel = os.path.join(tmp, "rc3.d")
        os.mkdir(runlevel)
        appprovision.SYSVINIT_BOOT_RUNNERS = [rc_local, rc_m]
        appprovision.SYSVINIT_RUNLEVEL_DIR_GLOBS = [os.path.join(tmp, "rc?.d")]
        check = appprovision.check_existing_service_running
        try:
            marker = os.path.join(tmp, "marker")
            svc = _script(os.path.join(tmp, "rc.qbittorrent-nox"), f'echo "$1" >> {marker}\n')

            # enabled: executable AND named by a boot runner
            _write(rc_local, f"#!/bin/sh\n{svc} start\n")
            r.check("sysvinit: executable and named in rc.local is enabled", check(svc, "sysvinit")[1])

            os.chmod(svc, 0o644)
            r.check("sysvinit: not executable is not enabled", not check(svc, "sysvinit")[1])
            os.chmod(svc, 0o755)

            _write(rc_local, f"#!/bin/sh\n# {svc} start\n")
            r.check("sysvinit: only a commented reference is not enabled", not check(svc, "sysvinit")[1])

            _write(rc_local, "#!/bin/sh\n")
            r.check("sysvinit: executable but named nowhere is not enabled", not check(svc, "sysvinit")[1])

            # DwarvenDash's own generated per-user entry must not count
            generated = os.path.join(tmp, "rc.dwarvendash-qbittorrent-nox-david")
            _write(rc_local, f"#!/bin/sh\n{generated} start\n")
            r.check("sysvinit: per-user generated entry does not make rc.<app> look enabled",
                    not check(svc, "sysvinit")[1])
            initd = _script(os.path.join(tmp, "qbittorrent-nox"), "true\n")
            r.check("sysvinit: per-user generated entry does not make a bare <app> script look enabled",
                    not check(initd, "sysvinit")[1])

            # runlevel start link
            os.symlink(initd, os.path.join(runlevel, "S20qbittorrent-nox"))
            r.check("sysvinit: runlevel S-link counts as enabled", check(initd, "sysvinit")[1])
            os.symlink(initd, os.path.join(runlevel, "K20other"))
            _write(rc_local, "#!/bin/sh\n")

            # running: only via a declared status handler
            os.path.exists(marker) and os.remove(marker)
            nostatus = _script(os.path.join(tmp, "rc.nostatus"),
                               f'echo ran >> {marker}\ncase "$1" in\n  start) true ;;\n  stop) true ;;\nesac\n')
            r.check("sysvinit: no status handler reports not running", not check(nostatus, "sysvinit")[0])
            r.check("sysvinit: script without a status handler was never executed", not os.path.exists(marker))

            up = _script(os.path.join(tmp, "rc.up"), 'case "$1" in\n  status) exit 0 ;;\nesac\n')
            down = _script(os.path.join(tmp, "rc.down"), 'case "$1" in\n  status) exit 3 ;;\nesac\n')
            r.check("sysvinit: status handler exit 0 is running", check(up, "sysvinit")[0])
            r.check("sysvinit: status handler exit 3 is not running", not check(down, "sysvinit")[0])

            # stop and disable
            os.path.exists(marker) and os.remove(marker)
            _write(rc_local, f"#!/bin/sh\n{svc} start\n")
            ok = appprovision.stop_and_disable_existing_service(svc, "sysvinit")
            ran = open(marker).read().split() if os.path.exists(marker) else []
            r.check("sysvinit: stop_and_disable returns True", ok)
            r.check("sysvinit: stop_and_disable ran the script with 'stop'", ran == ["stop"], ran)
            r.check("sysvinit: executable bit removed", not os.stat(svc).st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            r.check("sysvinit: disabled service reports not enabled", not check(svc, "sysvinit")[1])
            r.check("sysvinit: boot references still reported for the admin",
                    len(appprovision.sysvinit_boot_references(svc)) == 1)

            failing = _script(os.path.join(tmp, "rc.failstop"), "exit 1\n")
            r.check("sysvinit: non-zero stop exit is tolerated and still disables",
                    appprovision.stop_and_disable_existing_service(failing, "sysvinit")
                    and not os.access(failing, os.X_OK))

            unrunnable = _script(os.path.join(tmp, "rc.unrunnable"), "true\n", executable=False)
            r.check("sysvinit: an unrunnable script is reported as a failure",
                    not appprovision.stop_and_disable_existing_service(unrunnable, "sysvinit"))
        finally:
            appprovision.SYSVINIT_BOOT_RUNNERS, appprovision.SYSVINIT_RUNLEVEL_DIR_GLOBS = saved

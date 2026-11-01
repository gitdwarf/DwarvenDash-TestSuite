"""
nginx must be reloaded whenever a port map changes.

nginx reads the per-app port maps only at reload. Adding the second user of
an app changes a map but not the app's routing blocks, and used to trigger
no reload, so that user's page was sent nowhere until nginx restarted.
No browser, no real nginx: subprocess.run is replaced by a recorder, and
the module's path constants point at a temp directory.
"""

import os
import subprocess
import sys
import tempfile

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import appprovision  # noqa: E402

PATCHED = ["PORT_MAP_DIR", "POLICY_DIR", "NGINX_APPS_DIR", "NGINX_MAPS_FILE",
           "SYSVINIT_RC_DIR", "RC_LOCAL_PATH", "SYSTEMD_UNIT_DIR"]
EXEC = "/bin/true --port={port}"


class Recorder:
    """Stands in for subprocess.run. Commands in `fail` return 1, in `missing` raise."""

    def __init__(self, fail=(), missing=()):
        self.calls, self.fail, self.missing = [], set(fail), set(missing)

    def __call__(self, command, *a, **kw):
        self.calls.append(list(command))
        key = " ".join(command[:3])
        if key in self.missing or command[0] in self.missing:
            raise FileNotFoundError(command[0])
        code = 1 if key in self.fail else 0
        return subprocess.CompletedProcess(command, code, "", "")

    def reloads(self):
        return [c for c in self.calls if "reload" in c and "daemon-reload" not in c]


def run(browser, r):
    saved = {name: getattr(appprovision, name) for name in PATCHED}
    real_run = appprovision.subprocess.run
    try:
        with tempfile.TemporaryDirectory() as tmp:
            d = lambda *p: os.path.join(tmp, *p)
            appprovision.PORT_MAP_DIR = d("ports")
            appprovision.POLICY_DIR = d("policies")
            appprovision.NGINX_APPS_DIR = d("nginx-apps")
            appprovision.NGINX_MAPS_FILE = d("nginx-maps.conf")
            appprovision.SYSVINIT_RC_DIR = d("rc.d")
            appprovision.RC_LOCAL_PATH = d("rc.d", "rc.local")
            appprovision.SYSTEMD_UNIT_DIR = d("systemd")
            for p in (d("rc.d"), d("systemd")):
                os.makedirs(p)

            # ---- The reload itself. ---------------------------------------
            rec = Recorder()
            appprovision.subprocess.run = rec
            r.check("reload: succeeds with nginx's own signal first",
                    appprovision.reload_nginx() and rec.calls == [["nginx", "-s", "reload"]], rec.calls)

            rec = Recorder(fail=["nginx -s reload"])
            appprovision.subprocess.run = rec
            r.check("reload: falls back to systemctl when the signal fails",
                    appprovision.reload_nginx() and rec.calls[-1] == ["systemctl", "reload", "nginx"], rec.calls)

            rec = Recorder(missing=["nginx", "systemctl"])
            appprovision.subprocess.run = rec
            r.check("reload: missing programs are skipped, service is tried",
                    appprovision.reload_nginx() and rec.calls[-1] == ["service", "nginx", "reload"], rec.calls)

            rec = Recorder(fail=["nginx -s reload", "systemctl reload nginx", "service nginx reload"])
            appprovision.subprocess.run = rec
            r.check("reload: reports failure when nothing worked", appprovision.reload_nginx() is False)
            r.check("reload: and validate_and_reload_nginx reports it too, not a false success",
                    appprovision.validate_and_reload_nginx() is False)

            rec = Recorder(fail=["nginx -t"])
            appprovision.subprocess.run = rec
            r.check("reload: a config that fails validation is never reloaded",
                    appprovision.validate_and_reload_nginx() is False and not rec.reloads(), rec.calls)

            # ---- Provisioning: a second user of an app. -------------------
            rec = Recorder()
            appprovision.subprocess.run = rec
            first = appprovision.provision_app_for_user("reloadapp", 40000, "/reloadapp/", "alice", 1001, EXEC)
            r.check("reload: the first user's provisioning reloads nginx",
                    first["nginx_reloaded"] is True and len(rec.reloads()) == 1, rec.reloads())

            rec = Recorder()
            appprovision.subprocess.run = rec
            second = appprovision.provision_app_for_user("reloadapp", 40000, "/reloadapp/", "bob", 1002, EXEC)
            r.check("reload: the second user's routing blocks already exist", second["nginx_routing_was_new"] is False)
            r.check("reload: and nginx is reloaded anyway, because the port map changed",
                    second["nginx_reloaded"] is True and len(rec.reloads()) == 1, rec.reloads())

            # ---- Deprovisioning. ------------------------------------------
            rec = Recorder()
            appprovision.subprocess.run = rec
            out = appprovision.deprovision_app_for_user("reloadapp", "bob", "sysvinit")
            r.check("reload: removing an instance reloads nginx so its port stops being routed",
                    out["port_freed"] and out["nginx_reloaded"] is True and len(rec.reloads()) == 1, rec.reloads())

            rec = Recorder()
            appprovision.subprocess.run = rec
            out = appprovision.deprovision_app_for_user("reloadapp", "nobody-had-this", "sysvinit")
            r.check("reload: removing what was never there reloads nothing", not rec.reloads(), rec.reloads())

            rec = Recorder()
            appprovision.subprocess.run = rec
            appprovision.deprovision_app_for_user("reloadapp", "alice", "sysvinit", reload=False)
            r.check("reload: a caller removing many instances can reload once itself", not rec.reloads(), rec.reloads())

            # ---- Unregistering an app with several users: one reload. -----
            appprovision.subprocess.run = Recorder()
            for user, uid in (("alice", 1001), ("bob", 1002), ("carol", 1003)):
                appprovision.provision_app_for_user("reloadapp", 40000, "/reloadapp/", user, uid, EXEC)
            rec = Recorder()
            appprovision.subprocess.run = rec
            appprovision.unregister_app("reloadapp")
            r.check("reload: unregistering an app with three users reloads exactly once",
                    len(rec.reloads()) == 1, rec.reloads())
    finally:
        appprovision.subprocess.run = real_run
        for name, value in saved.items():
            setattr(appprovision, name, value)

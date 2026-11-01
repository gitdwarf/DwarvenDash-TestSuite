"""
Cleanup: leftovers from removed users and apps.

No browser. Builds a small fake world in a temp directory (apps, users,
port maps, nginx files, rc scripts, per-user configs) by pointing the
module's path constants at it, runs scan() and apply() against it, and
checks both what was removed and, just as important, what was kept.

World:
  alpha    registered, binary exists            keep
  beta     registered, binary gone              remove completely
  ghost    routing and instances, no policy     remove completely
  alice    in group, has alpha + ghost          keeps alpha, loses ghost
  bob      account exists, left the group       alpha instance removed, ACL revoked
  carol    account deleted, had alpha           alpha instance removed
  dave     in group, beta + a button with no    both buttons removed
           instance behind it
"""

import json
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

import dd_harness as h

import sys
sys.path.insert(0, h.APP_DIR)
import appprovision  # noqa: E402
import cleanup  # noqa: E402
import userprovision  # noqa: E402

PATCHED = ["PORT_MAP_DIR", "POLICY_DIR", "NGINX_APPS_DIR", "NGINX_MAPS_FILE",
           "SYSVINIT_RC_DIR", "RC_LOCAL_PATH", "SYSTEMD_UNIT_DIR"]


def _write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def _config(path, links):
    _write(path, json.dumps({"launcher": [{"group": "Apps", "links": links}]}))


def _titles(path):
    with open(path) as f:
        return [(l["title"], l.get("type")) for g in json.load(f)["launcher"] for l in g["links"]]


def _acl_works(tmp):
    """Can this box set a named-group ACL here? If not the ACL checks are skipped."""
    if not (shutil.which("setfacl") and shutil.which("getfacl")):
        return False
    probe = os.path.join(tmp, "aclprobe")
    os.mkdir(probe)
    return subprocess.run(["setfacl", "-m", "g:root:x", probe], capture_output=True).returncode == 0


def run(browser, r):
    saved = {name: getattr(appprovision, name) for name in PATCHED}
    saved_validate = appprovision.validate_and_reload_nginx
    saved_group = userprovision.GROUP_NAME
    with tempfile.TemporaryDirectory() as tmp:
        d = lambda *p: os.path.join(tmp, *p)
        appprovision.PORT_MAP_DIR = d("ports")
        appprovision.POLICY_DIR = d("policies")
        appprovision.NGINX_APPS_DIR = d("nginx-apps")
        appprovision.NGINX_MAPS_FILE = d("nginx-maps.conf")
        appprovision.SYSVINIT_RC_DIR = d("rc.d")
        appprovision.RC_LOCAL_PATH = d("rc.d", "rc.local")
        appprovision.SYSTEMD_UNIT_DIR = d("systemd")
        appprovision.validate_and_reload_nginx = lambda: True
        userprovision.GROUP_NAME = "root"  # a group that exists here, for the ACL check
        log = d("stops.log")

        try:
            existing = {"alice", "bob", "dave"}
            in_group = {"alice", "dave"}
            user_exists = lambda u: u in existing
            group_check = lambda u: u in in_group
            home = lambda u: d("home", u)
            cfg = lambda u: os.path.join(home(u), ".config", "dwarvendash", "config.json") if u in existing else None
            accounts = lambda: [SimpleNamespace(pw_name=u, pw_dir=home(u)) for u in sorted(existing)]

            for app, tmpl in (("alpha", "/bin/true --port={port}"), ("beta", "/nonexistent/beta --port={port}")):
                appprovision.register_app_policy(app, 50000, f"/{app}/", tmpl)
            for app, users in (("alpha", ("alice", "bob", "carol")), ("beta", ("dave",)), ("ghost", ("alice",))):
                appprovision.save_port_map(app, {u: 50100 + i for i, u in enumerate(users)})
                _write(os.path.join(appprovision.NGINX_APPS_DIR, f"{app}.conf"), "location {}\n")
                for u in users:
                    _write(d("rc.d", f"rc.dwarvendash-{app}-{u}"), f'#!/bin/sh\n# DwarvenDash-managed {app} for {u}\necho "{app}-{u} $1" >> {log}\n', 0o755)
            _write(appprovision.RC_LOCAL_PATH, "#!/bin/sh\n" + "".join(
                f"{d('rc.d', f'rc.dwarvendash-{a}-{u}')} start\n"
                for a, u in (("alpha", "alice"), ("alpha", "bob"), ("alpha", "carol"), ("beta", "dave"), ("ghost", "alice"))))

            # Strays: generated launcher files with no port map entry behind them,
            # and DwarvenDash's own service script, which must never be touched.
            stray = d("rc.d", "rc.dwarvendash-alpha-zed")
            _write(stray, f'#!/bin/sh\n# DwarvenDash-managed alpha for zed\necho "alpha-zed $1" >> {log}\n', 0o755)
            with open(appprovision.RC_LOCAL_PATH, "a") as f:
                f.write(f"{stray} start\n")
            own = d("rc.d", "rc.dwarvendash")
            _write(own, "#!/bin/sh\n# DwarvenDash itself\n", 0o755)
            unit = d("systemd", "dwarvendash-beta-yan.service")
            _write(unit, "[Unit]\nDescription=DwarvenDash-managed beta for yan\n")
            _write(d("systemd", "dwarvendash-authcheck.service"), "[Unit]\nDescription=DwarvenDash auth\n")

            app_link = lambda a: {"title": a, "url": f"/{a}/", "type": "app"}
            _config(cfg("alice"), [app_link("alpha"), app_link("ghost"),
                                   {"title": "Site", "url": "https://example.com", "type": "bookmark"},
                                   {"title": "Legacy", "url": "/grafana/"}])
            _config(cfg("bob"), [app_link("alpha")])
            _config(cfg("dave"), [app_link("beta"), app_link("alpha")])

            acl = _acl_works(tmp)
            if acl:
                subprocess.run(["setfacl", "-m", "g:root:x", home("bob")], check=True)
            else:
                print("SKIP ACL checks: setfacl/getfacl not usable here")

            found = cleanup.scan(user_exists, group_check, cfg, accounts)
            r.check("cleanup: finds the missing-binary and unregistered apps",
                    sorted((a["app"], a["reason"]) for a in found["apps"]) ==
                    [("beta", "binary-missing"), ("ghost", "not-registered")], found["apps"])
            r.check("cleanup: finds exactly the removed-user and left-group instances",
                    sorted((i["app"], i["user"], i["reason"]) for i in found["instances"]) ==
                    [("alpha", "bob", "not-in-group"), ("alpha", "carol", "user-removed")], found["instances"])
            r.check("cleanup: never plans to touch alice's live alpha instance",
                    ("alpha", "alice") not in {(i["app"], i["user"]) for i in found["instances"]})
            r.check("cleanup: finds the launcher files nothing backs, not the live ones or DwarvenDash's own",
                    sorted((a["app"], a["user"], a["init_system"]) for a in found["artifacts"]) ==
                    [("alpha", "zed", "sysvinit"), ("beta", "yan", "systemd")], found["artifacts"])
            os.remove(unit)  # applying a systemd stray needs systemctl, covered by the scan check above
            found["artifacts"] = [a for a in found["artifacts"] if a["init_system"] == "sysvinit"]
            r.check("cleanup: plan lists the buttons that point at nothing",
                    sorted((b["user"], b["title"]) for b in found["launcher"]) ==
                    [("alice", "ghost"), ("bob", "alpha"), ("dave", "alpha"), ("dave", "beta")], found["launcher"])
            if acl:
                r.check("cleanup: finds the stale ACL on the user who left the group",
                        [a["user"] for a in found["acls"]] == ["bob"], found["acls"])
            r.check("cleanup: plan describes every finding",
                    len(cleanup.describe(found)) == sum(len(v) for v in found.values()))
            r.check("cleanup: scan changed nothing (still 3 instances on alpha)",
                    sorted(appprovision.load_port_map("alpha")) == ["alice", "bob", "carol"])

            done = cleanup.apply(found, cfg, accounts, init_system="sysvinit")
            r.check("cleanup: every step reported success", all(ok for _, ok in done), [w for w, ok in done if not ok])

            r.check("cleanup: alpha keeps only alice", sorted(appprovision.load_port_map("alpha")) == ["alice"],
                    appprovision.load_port_map("alpha"))
            r.check("cleanup: alpha policy and routing untouched",
                    appprovision.get_app_policy("alpha") is not None
                    and os.path.exists(os.path.join(appprovision.NGINX_APPS_DIR, "alpha.conf")))
            r.check("cleanup: beta and ghost fully gone (policy, port map, routing)",
                    all(not os.path.exists(p) for p in (
                        os.path.join(appprovision.POLICY_DIR, "beta.json"),
                        os.path.join(appprovision.PORT_MAP_DIR, "beta.map"),
                        os.path.join(appprovision.NGINX_APPS_DIR, "beta.conf"),
                        os.path.join(appprovision.PORT_MAP_DIR, "ghost.map"),
                        os.path.join(appprovision.NGINX_APPS_DIR, "ghost.conf"))))
            rc = lambda a, u: d("rc.d", f"rc.dwarvendash-{a}-{u}")
            r.check("cleanup: removed instances lost their rc scripts, alice's alpha kept it",
                    not any(os.path.exists(rc(a, u)) for a, u in (("alpha", "bob"), ("alpha", "carol"), ("beta", "dave"), ("ghost", "alice")))
                    and os.path.exists(rc("alpha", "alice")))
            stops = sorted(open(log).read().splitlines()) if os.path.exists(log) else []
            r.check("cleanup: each removed instance was stopped first",
                    stops == sorted(f"{a}-{u} stop" for a, u in (("alpha", "bob"), ("alpha", "carol"), ("alpha", "zed"), ("beta", "dave"), ("ghost", "alice"))), stops)
            r.check("cleanup: stray launcher file stopped and removed, with its rc.local line",
                    not os.path.exists(stray) and stray not in open(appprovision.RC_LOCAL_PATH).read()
                    and "alpha-zed stop" in (open(log).read() if os.path.exists(log) else ""))
            r.check("cleanup: DwarvenDash's own service files untouched",
                    os.path.exists(own) and os.path.exists(d("systemd", "dwarvendash-authcheck.service")))
            local = open(appprovision.RC_LOCAL_PATH).read()
            r.check("cleanup: rc.local lost the removed entries and kept alice's",
                    rc("alpha", "alice") in local and all(rc(a, u) not in local for a, u in (
                        ("alpha", "bob"), ("alpha", "carol"), ("beta", "dave"), ("ghost", "alice"))))

            r.check("cleanup: alice keeps alpha, bookmark and untyped link, loses ghost",
                    _titles(cfg("alice")) == [("alpha", "app"), ("Site", "bookmark"), ("Legacy", None)], _titles(cfg("alice")))
            r.check("cleanup: bob's and dave's dead buttons removed",
                    _titles(cfg("bob")) == [] and _titles(cfg("dave")) == [], (_titles(cfg("bob")), _titles(cfg("dave"))))
            r.check("cleanup: user config files still exist (data is never deleted)",
                    all(os.path.isfile(cfg(u)) for u in ("alice", "bob", "dave")))
            if acl:
                r.check("cleanup: ACL revoked on bob's home", not cleanup._has_group_acl(home("bob")))

            again = cleanup.scan(user_exists, group_check, cfg, accounts)
            r.check("cleanup: a second scan finds nothing", cleanup.is_empty(again), again)
            r.check("cleanup: applying an empty plan is a no-op",
                    cleanup.apply(again, cfg, accounts, init_system="sysvinit") == [])
        finally:
            for name, value in saved.items():
                setattr(appprovision, name, value)
            appprovision.validate_and_reload_nginx = saved_validate
            userprovision.GROUP_NAME = saved_group

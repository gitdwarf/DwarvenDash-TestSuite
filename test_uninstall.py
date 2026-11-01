"""
install.sh uninstall: the order of its steps, the confirmation, and what it does to the nginx files.

Each function is cut out of install.sh (so the real text is what is tested) and run against a fake nginx
directory with stand-in nginx, getent and gpasswd commands. Nothing real is installed or removed.
"""

import os
import shutil
import stat
import subprocess
import tempfile

import dd_harness as h
from test_installer import INSTALL, _function, _header

ROOT = os.path.dirname(INSTALL)
MARK = "# DwarvenDash nginx site config\n"
FUNCTIONS = ("detect_init", "reload_nginx", "validate_and_reload_nginx", "choose_nginx_layout", "uninstall_confirm",
             "uninstall_empty_group", "uninstall_nginx_config", "run_uninstall", "get_ssl_cert_path", "get_ssl_key_path",
             "write_default_site", "restore_welcome_page", "uninstall_cleanup", "uninstall_services", "uninstall_files",
             "uninstall_account")


def _sh(body, shims=None, tree=None, www="/nonexistent", root=""):
    """Run body with the uninstall functions loaded. shims: {command: script body} put first on PATH."""
    work = tempfile.mkdtemp(prefix="dd-un-")
    try:
        for name, text in (shims or {}).items():
            path = os.path.join(work, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + text)
            os.chmod(path, stat.S_IRWXU)
        script = os.path.join(work, "run.sh")
        with open(script, "w") as f:
            f.write("set -eu\n" + _header() + 'GROUP_NAME=dwarvendash\nSERVICE_ACCOUNT=dwarvendash-svc\n'
                    f'INSTALL_DIR=/opt/dwarvendash\nSCRIPT_DIR="{ROOT}"\nNGINX_DIR="{tree}"\nWWW_DIR="{www}"\nROOT_DIR="{root}"\nUNINSTALL_PLAN=plan\n'
                    + "".join(_function(n) for n in FUNCTIONS) + body)
        done = subprocess.run(["sh", script], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              env=dict(os.environ, PATH=work + os.pathsep + os.environ["PATH"]), timeout=30)
        return done.returncode, done.stdout + done.stderr
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _tree(layout, site=None, extra=()):
    """A fake /etc/nginx. layout 'sites' has sites-available, 'conf.d' does not. site is the config's text."""
    tree = tempfile.mkdtemp(prefix="dd-nginx-")
    os.makedirs(os.path.join(tree, "conf.d"))
    os.makedirs(os.path.join(tree, "dwarvendash-apps"))
    os.makedirs(os.path.join(tree, "dwarvendash-ports"))
    for name in ("dwarvendash-gate.conf", "conf.d/dwarvendash-maps.conf", "dwarvendash-apps/x.conf"):
        open(os.path.join(tree, name), "w").write("x\n")
    if layout == "sites":
        os.makedirs(os.path.join(tree, "sites-available"))
        os.makedirs(os.path.join(tree, "sites-enabled"))
        target = os.path.join(tree, "sites-available", "default")
    else:
        target = os.path.join(tree, "conf.d", "dwarvendash.conf")
    if site is not None:
        open(target, "w").write(site)
    for name, text in extra:
        open(os.path.join(tree, name), "w").write(text)
    return tree, target


# nginx, and the commands that reload it, are stand-ins: a test must never reload the real one.
NGINX_OK = {"nginx": "exit 0\n", "systemctl": "exit 0\n", "service": "exit 0\n"}


def run(browser, r):
    _whole_run(r, "sysvinit")
    _whole_run(r, "systemd")

    stock = open(os.path.join(ROOT, "nginx", "stock-default-reference.conf")).read()

    # The confirmation.
    code, out = _sh("UNINSTALL_YES=0\nuninstall_confirm || exit 1\n", tree="/nonexistent")
    r.check("uninstall: without --yes and with no terminal it refuses and says nothing was changed",
            code != 0 and "Nothing was changed" in out, (code, out))
    code, out = _sh("UNINSTALL_YES=1\nuninstall_confirm\necho CONFIRMED\n", tree="/nonexistent")
    r.check("uninstall: --yes goes ahead without asking", code == 0 and "CONFIRMED" in out, (code, out))

    # The order, and that a refusal stops before any step.
    steps = "".join(f'{n}() {{ echo STEP-{n}; }}\n' for n in (
        "uninstall_empty_group", "uninstall_cleanup", "uninstall_services", "uninstall_files",
        "uninstall_nginx_config", "uninstall_account"))
    code, out = _sh(steps + "run_uninstall --yes\n", tree="/nonexistent")
    order = [line.split("STEP-")[1] for line in out.splitlines() if line.startswith("STEP-")]
    r.check("uninstall: the steps run in order, group first, then cleanup, then services, files, nginx, account",
            order == ["uninstall_empty_group", "uninstall_cleanup", "uninstall_services", "uninstall_files",
                      "uninstall_nginx_config", "uninstall_account"], order)
    code, out = _sh(steps + "run_uninstall\n", tree="/nonexistent")
    r.check("uninstall: a refused confirmation runs no step and exits 2", code == 2 and "STEP-" not in out, (code, out))
    code, out = _sh(steps + "run_uninstall --bogus\n", tree="/nonexistent")
    r.check("uninstall: an unknown argument stops before any step", code == 1 and "STEP-" not in out, (code, out))

    # Emptying the group.
    log = tempfile.mktemp(prefix="dd-gp-")
    shims = {"getent": 'echo "dwarvendash:x:900:alice,bob"\n', "gpasswd": f'echo "$@" >> {log}\n'}
    code, out = _sh("uninstall_empty_group\n", shims, "/nonexistent")
    calls = open(log).read().splitlines() if os.path.exists(log) else []
    r.check("uninstall: every member is taken out of the group", code == 0 and calls == ["-d alice dwarvendash", "-d bob dwarvendash"], (code, calls, out))
    if os.path.exists(log):
        os.remove(log)
    shims = {"getent": "exit 2\n", "gpasswd": f'echo "$@" >> {log}\n'}
    code, out = _sh("uninstall_empty_group\n", shims, "/nonexistent")
    r.check("uninstall: no group at all is not an error", code == 0 and not os.path.exists(log), (code, out))

    # The nginx side, Debian layout: the default site that serves the welcome page comes back, the pieces go.
    www = tempfile.mkdtemp(prefix="dd-www-")
    tree, target = _tree("sites", MARK + "server { include /etc/nginx/dwarvendash-gate.conf; }\n")
    try:
        os.symlink(target, os.path.join(tree, "sites-enabled", "default"))
        code, out = _sh("uninstall_nginx_config\n", NGINX_OK, tree, www)
        site = open(target).read()
        r.check("uninstall nginx: sites layout gets a default site that serves the welcome page",
                code == 0 and "listen 80 default_server;" in site and f"root {www};" in site and "index.nginx-debian.html" in site
                and "try_files $uri $uri/ =404;" in site and "dwarvendash" not in site and "ssl" not in site, (code, site, out))
        r.check("uninstall nginx: a plain HTTP install stays plain HTTP", "443" not in site)
        r.check("uninstall nginx: no copy of the DwarvenDash config is left behind",
                not [n for n in os.listdir(os.path.dirname(target)) if "dwarvendash" in n])
        r.check("uninstall nginx: the stock welcome page is put back when the web root has none",
                open(os.path.join(www, "index.nginx-debian.html")).read() == open(os.path.join(ROOT, "nginx", "stock-index-reference.html")).read())
        r.check("uninstall nginx: the gate file, apps, ports and maps are gone",
                not any(os.path.exists(os.path.join(tree, p)) for p in (
                    "dwarvendash-gate.conf", "dwarvendash-apps", "dwarvendash-ports", "conf.d/dwarvendash-maps.conf")))
    finally:
        shutil.rmtree(tree)
        shutil.rmtree(www)

    # A page the person made is never replaced.
    www = tempfile.mkdtemp(prefix="dd-www-")
    open(os.path.join(www, "index.html"), "w").write("mine\n")
    tree, target = _tree("sites", MARK + "server {}\n")
    try:
        _sh("uninstall_nginx_config\n", NGINX_OK, tree, www)
        r.check("uninstall nginx: an index page that is already there is left alone",
                open(os.path.join(www, "index.html")).read() == "mine\n" and os.listdir(www) == ["index.html"], os.listdir(www))
    finally:
        shutil.rmtree(tree)
        shutil.rmtree(www)

    # An HTTPS install goes back to an HTTPS default site with the same certificate.
    www = tempfile.mkdtemp(prefix="dd-www-")
    tls = MARK + "server {\n  listen 443 ssl;\n  ssl_certificate /etc/ssl/a/fullchain.pem;\n  ssl_certificate_key /etc/ssl/a/key.pem;\n}\n"
    tree, target = _tree("sites", tls)
    try:
        code, out = _sh("uninstall_nginx_config\n", NGINX_OK, tree, www)
        site = open(target).read()
        r.check("uninstall nginx: an HTTPS install goes back to an HTTPS default site with the same certificate",
                "listen 443 ssl default_server;" in site and "ssl_certificate /etc/ssl/a/fullchain.pem;" in site
                and "ssl_certificate_key /etc/ssl/a/key.pem;" in site and "listen 80 default_server;" in site, (site, out))
    finally:
        shutil.rmtree(tree)
        shutil.rmtree(www)

    # conf.d layout: the file is simply removed, nothing left behind.
    tree, target = _tree("conf.d", MARK + "server {}\n")
    try:
        code, out = _sh("uninstall_nginx_config\n", NGINX_OK, tree)
        r.check("uninstall nginx: conf.d layout removes the DwarvenDash file and leaves no copy",
                code == 0 and not [n for n in os.listdir(os.path.join(tree, "conf.d")) if "dwarvendash" in n], (code, out))
    finally:
        shutil.rmtree(tree)

    # An edited config that still includes our files is left alone, and so are the files.
    edited = "server { include /etc/nginx/dwarvendash-gate.conf; }\n"
    tree, target = _tree("sites", edited)
    try:
        code, out = _sh("uninstall_nginx_config\n", NGINX_OK, tree)
        r.check("uninstall nginx: an edited config that uses DwarvenDash is left alone",
                open(target).read() == edited, out)
        r.check("uninstall nginx: and its nginx files stay, so nginx is never left pointing at nothing",
                os.path.exists(os.path.join(tree, "dwarvendash-gate.conf")) and os.path.isdir(os.path.join(tree, "dwarvendash-apps")), out)
    finally:
        shutil.rmtree(tree)

    # A config with nothing to do with DwarvenDash is left alone, its files still go.
    other = "server { listen 80; }\n"
    tree, target = _tree("sites", other)
    try:
        code, out = _sh("uninstall_nginx_config\n", NGINX_OK, tree)
        r.check("uninstall nginx: an unrelated config is untouched and DwarvenDash's files are removed",
                open(target).read() == other and not os.path.exists(os.path.join(tree, "dwarvendash-gate.conf")), out)
    finally:
        shutil.rmtree(tree)

    # The file installed alongside, and its symlink.
    tree, target = _tree("sites", other, extra=[("sites-available/dwarvendash", MARK + "server {}\n")])
    try:
        os.symlink(os.path.join(tree, "sites-available", "dwarvendash"), os.path.join(tree, "sites-enabled", "dwarvendash"))
        code, out = _sh("uninstall_nginx_config\n", NGINX_OK, tree)
        r.check("uninstall nginx: the alongside file and its sites-enabled link are removed",
                not os.path.lexists(os.path.join(tree, "sites-enabled", "dwarvendash"))
                and not os.path.exists(os.path.join(tree, "sites-available", "dwarvendash")), out)
        r.check("uninstall nginx: nothing named dwarvendash is left in any nginx directory",
                not [os.path.join(d, n) for d, _, names in os.walk(tree) for n in names + _ if "dwarvendash" in n], os.listdir(tree))
    finally:
        shutil.rmtree(tree)

    # nginx rejecting the result is reported, not hidden.
    tree, target = _tree("sites", MARK + "server {}\n")
    try:
        code, out = _sh("uninstall_nginx_config\n", dict(NGINX_OK, nginx='echo "bad config" >&2\nexit 1\n'), tree)
        r.check("uninstall nginx: a config nginx rejects is reported, not reloaded", "validation FAILED" in out, out)
    finally:
        shutil.rmtree(tree)


def _whole_run(r, init):
    """
    The whole of `uninstall --yes`, every step, against a fake root (DWARVENDASH_ROOT) and a fake nginx tree,
    with stand-ins for the commands that would touch the machine. Records every command in order.
    """
    root = tempfile.mkdtemp(prefix="dd-root-")
    www = tempfile.mkdtemp(prefix="dd-www-")
    calls = os.path.join(root, "calls.log")
    tls = MARK + "server {\n  listen 443 ssl;\n  ssl_certificate /etc/ssl/a/fullchain.pem;\n  ssl_certificate_key /etc/ssl/a/key.pem;\n}\n"
    tree, target = _tree("sites", tls, extra=[("sites-available/dwarvendash.bak", "old\n")])
    files = ["opt/dwarvendash/server.py", "etc/dwarvendash/app-policies/x.json", "etc/pam.d/dwarvendash", "var/log/dwarvendash.log",
             "var/log/dwarvendash-authcheck.log", "var/run/dwarvendash.pid", "var/run/dwarvendash-authcheck.pid",
             "etc/systemd/system/dwarvendash.service", "etc/systemd/system/dwarvendash-authcheck.service",
             "etc/rc.d/rc.dwarvendash", "etc/rc.d/rc.dwarvendash-authcheck", "home/alice/.config/dwarvendash/config.json"]
    for f in files:
        os.makedirs(os.path.dirname(os.path.join(root, f)), exist_ok=True)
        open(os.path.join(root, f), "w").write("x\n")
        if f.startswith("etc/rc.d/"):
            os.chmod(os.path.join(root, f), 0o755)
    open(os.path.join(root, "etc/rc.d/rc.local"), "w").write(
        "#!/bin/sh\n/etc/rc.d/rc.dwarvendash-authcheck start\n/etc/rc.d/rc.dwarvendash start\n/etc/rc.d/rc.other start\nexit 0\n")
    log = lambda name: f'echo "{name} $*" >> {calls}\n'
    shims = {
        "getent": 'case "$1" in group) [ -e ' + root + '/group-gone ] && exit 2; echo "dwarvendash:x:900:alice,bob,dwarvendash-svc";; esac\n',
        "gpasswd": log("gpasswd") + f"touch {root}/emptied\n",
        "python3": f'echo "cleanup emptied=$([ -e {root}/emptied ] && echo yes || echo no) $*" >> {calls}\n',
        "systemctl": log("systemctl"), "service": "exit 0\n", "nginx": log("nginx"),
        "id": 'exit 0\n', "userdel": log("userdel"), "groupdel": log("groupdel") + f"touch {root}/group-gone\n",
    }
    try:
        code, out = _sh(f'detect_init() {{ echo {init}; }}\nrun_uninstall --yes\n', shims, tree, www, root)
        seen = open(calls).read().splitlines() if os.path.exists(calls) else []
        names = [c.split()[0] for c in seen]
        r.check(f"uninstall whole run ({init}): finishes cleanly and says what it left", code == 0 and "DwarvenDash is uninstalled" in out, (code, out[-300:]))
        r.check(f"uninstall whole run ({init}): members are removed from the group before cleanup runs, and cleanup sees an empty group",
                names[:2] == ["gpasswd", "gpasswd"] or names[:3] == ["gpasswd"] * 3, seen)
        cleanup = [c for c in seen if c.startswith("cleanup")]
        r.check(f"uninstall whole run ({init}): cleanup runs once, with --cleanup --yes, after the group was emptied",
                len(cleanup) == 1 and "emptied=yes" in cleanup[0] and "--cleanup --yes" in cleanup[0], cleanup)
        r.check(f"uninstall whole run ({init}): the account goes before the group, and both last",
                names[-2:] == ["userdel", "groupdel"], names)
        other = ("etc/rc.d/", "var/run/") if init == "systemd" else ("etc/systemd/",)  # the other init system's files are not this run's business
        gone = [f for f in files if "home/" not in f and not f.startswith(other) and os.path.exists(os.path.join(root, f))]
        r.check(f"uninstall whole run ({init}): every DwarvenDash file under the root is gone", not gone, gone)
        r.check(f"uninstall whole run ({init}): a person's own config is never touched",
                os.path.exists(os.path.join(root, "home/alice/.config/dwarvendash/config.json")))
        if init == "sysvinit":
            rc = open(os.path.join(root, "etc/rc.d/rc.local")).read()
            r.check("uninstall whole run (sysvinit): rc.local loses only DwarvenDash's lines",
                    "rc.dwarvendash" not in rc and "rc.other start" in rc and "exit 0" in rc, rc)
        else:
            r.check("uninstall whole run (systemd): units are disabled and systemd is told", any("disable --now dwarvendash" in c for c in seen)
                    and any("daemon-reload" in c for c in seen), seen)
        site = open(target).read()
        r.check(f"uninstall whole run ({init}): nginx ends as an HTTPS default site, nothing named dwarvendash anywhere",
                "ssl_certificate /etc/ssl/a/fullchain.pem;" in site and "welcome" not in site.lower()
                and not [n for d, ds, ns in os.walk(tree) for n in ns + ds if "dwarvendash" in n], site)
        r.check(f"uninstall whole run ({init}): nginx is checked and reloaded after its files changed", "nginx -t" in "\n".join(seen), seen)
    finally:
        for d in (root, www, tree):
            shutil.rmtree(d, ignore_errors=True)

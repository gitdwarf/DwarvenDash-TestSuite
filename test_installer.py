"""
The installer's prerequisite check, its offer to install python-pam, and where it puts the nginx config.

The regression: `PAM_IMPORT_ERROR=$(python3 -c "import pam" 2>&1)` under `set -e` ended the whole script
the moment python-pam was missing, printing nothing after "Checking for python-pam", so the explanation
written for exactly that case never appeared. The check is run on its own here (cut out of install.sh,
so the real text is what is tested) with a stand-in python3 that fails or succeeds as asked.
"""

import os
import pty
import re
import shutil
import stat
import subprocess
import tempfile

import dd_harness as h

INSTALL = os.path.join(os.path.dirname(h.APP_DIR), "install.sh")


def _function(name):
    text = open(INSTALL).read()
    return re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M).group(0)


def _header():
    """The part of install.sh that reports how it stopped: LAST_STEP to the trap, log, finish, stop."""
    text = open(INSTALL).read()
    return re.search(r"^LAST_STEP=.*?^trap finish EXIT\n\nstop\(\) \{\n.*?^\}\n", text, re.S | re.M).group(0)


def _script(body):
    done = subprocess.run(["sh", "-c", "set -eu\n" + _header() + body], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=30)
    return done.returncode, done.stdout + done.stderr


def _prerequisites(have_nginx=None):
    """The prerequisite check, with its nginx question answered by a stand-in when have_nginx is given ("return 1")."""
    stand_in = f"have_nginx() {{ {have_nginx}; }}\n" if have_nginx else _function("have_nginx")
    return _function("check_prerequisites") + stand_in


def _run(shim_body, path_extra=None, have_nginx=None):
    work = tempfile.mkdtemp(prefix="dd-inst-")
    try:
        shim = os.path.join(work, "python3")
        with open(shim, "w") as f:
            f.write("#!/bin/sh\n" + shim_body)
        os.chmod(shim, stat.S_IRWXU)
        script = os.path.join(work, "check.sh")
        with open(script, "w") as f:
            f.write("set -eu\n" + _header() + "INSTALL_DEPS=${DD_INSTALL_DEPS:-0}\n" + _function("pam_imports") + _function("offer_python_deps")
                    + _prerequisites(have_nginx) + "check_prerequisites\necho CHECK-FINISHED\n")
        done = subprocess.run(["sh", script], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              env=dict(os.environ, PATH=work + os.pathsep + os.environ["PATH"]), timeout=30)
        return done.returncode, done.stdout + done.stderr
    finally:
        for name in os.listdir(work):
            os.remove(os.path.join(work, name))
        os.rmdir(work)


def run(browser, r):
    code, out = _run('echo "ModuleNotFoundError: No module named \'pam\'" >&2\nexit 1\n')
    r.check("installer: a missing python-pam is explained, not a silent stop after 'Checking for python-pam'",
            "python-pam: import failed" in out and "No module named 'pam'" in out and "pip install python-pam" in out, out[-400:])
    r.check("installer: and it still stops, since nobody is there to say continue", code == 1 and "CHECK-FINISHED" not in out, (code, out[-200:]))

    # nginx is a requirement like the rest: its absence is said up front, not found out when nothing answers.
    code, out = _run("exit 0\n", have_nginx="return 1")
    r.check("installer: a missing nginx is named, with the install line, before anything is installed",
            "- nginx: not found" in out and "apt install nginx" in out and code == 1 and "CHECK-FINISHED" not in out, (code, out[-300:]))
    code, out = _run("exit 0\n", have_nginx="return 0")
    r.check("installer: nginx present is not reported", "nginx: not found" not in out, out[-300:])

    r.check("installer: a stop it chose and explained is not also reported as unexpected", "stopped unexpectedly" not in out, out[-300:])

    # No abort is silent: a command that fails under set -e says where, and how to find out which.
    code, out = _script('log "Doing the thing"\nfalse\necho NOT-REACHED\n')
    r.check("installer: an unexplained failure names the step it was on and how to see the command",
            code == 1 and "stopped unexpectedly (exit 1) after: Doing the thing" in out and "sh -x" in out and "NOT-REACHED" not in out, (code, out))
    code, out = _script('log "x"\necho explained >&2\nstop 3\n')
    r.check("installer: stop() keeps its exit status and adds nothing", code == 3 and "unexpectedly" not in out, (code, out))
    code, out = _script('log "x"\n')
    r.check("installer: a clean finish says nothing extra", code == 0 and "unexpectedly" not in out, (code, out))
    done = subprocess.run(["sh", INSTALL, "no-such-command"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    r.check("installer: an unknown command is explained and exits 1, without the unexpected note",
            done.returncode == 1 and "Unknown command" in done.stderr and "unexpectedly" not in done.stderr, (done.returncode, done.stderr[-200:]))

    code, out = _run("exit 0\n")
    r.check("installer: with python-pam importing, the pam step reports nothing wrong", "python-pam: import failed" not in out, out[-300:])

    run_nginx_and_pip(r)


PIP_SHIM = r"""#!/bin/sh
# A python3 whose pam import works once "pip install" has run. DD_STATE holds what happened.
case "$*" in
  "-c import pam")
    [ -f "$DD_STATE/pam" ] && exit 0
    echo "ModuleNotFoundError: No module named 'pam'" >&2; exit 1 ;;
  "-m pip --version")
    [ "${DD_NO_PIP:-0}" = 1 ] && exit 1
    exit 0 ;;
  "-m pip install python-pam six --break-system-packages")
    echo "$*" >> "$DD_STATE/pip.log"
    [ "${DD_OLD_PIP:-0}" = 1 ] && { echo "no such option: --break-system-packages" >&2; exit 2; }
    [ "${DD_PIP_FAILS:-0}" = 1 ] && exit 1
    touch "$DD_STATE/pam"; exit 0 ;;
  "-m pip install python-pam six")
    echo "$*" >> "$DD_STATE/pip.log"
    [ "${DD_PIP_FAILS:-0}" = 1 ] && exit 1
    touch "$DD_STATE/pam"; exit 0 ;;
esac
exit 0
"""


def _terminal(args, env, answers):
    """Run with a real terminal on stdin, typing the answers ahead of time. (exit code, output)."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(args, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, close_fds=True)
    os.close(slave)
    for answer in answers:
        os.write(master, (answer + "\n").encode())
    out = proc.communicate(timeout=60)[0].decode(errors="replace")
    os.close(master)
    return proc.returncode, out


def _pip_run(answers=None, **flags):
    """check_prerequisites with the pip stand-in. answers=None is no terminal. -> (code, output, pip install lines, pam works)"""
    work = tempfile.mkdtemp(prefix="dd-pip-")
    try:
        state = os.path.join(work, "state")
        os.mkdir(state)
        shim = os.path.join(work, "python3")
        with open(shim, "w") as f:
            f.write(PIP_SHIM)
        os.chmod(shim, stat.S_IRWXU)
        script = os.path.join(work, "check.sh")
        with open(script, "w") as f:
            f.write("set -eu\n" + _header() + "INSTALL_DEPS=${DD_INSTALL_DEPS:-0}\n" + _function("pam_imports") + _function("offer_python_deps")
                    + _prerequisites("return 0") + "check_prerequisites\necho CHECK-FINISHED\n")
        env = dict(os.environ, PATH=work + os.pathsep + os.environ["PATH"], DD_STATE=state,
                   **{k: str(v) for k, v in flags.items()})
        if answers is None:
            done = subprocess.run(["sh", script], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, timeout=60)
            code, out = done.returncode, done.stdout + done.stderr
        else:
            code, out = _terminal(["sh", script], env, answers)
        log = os.path.join(state, "pip.log")
        return code, out, (open(log).read().splitlines() if os.path.exists(log) else []), os.path.exists(os.path.join(state, "pam"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


SLACKWARE_CONF = """user nobody;
events {
    worker_connections  1024;
}
http {
    include       mime.types;
    # a } in a comment, and "a } in a string"
    log_format  main  '$remote_addr - { } $remote_user';
    server {
        listen       80;
        server_name  localhost;
        location / { root html; }
    }
    #include /etc/nginx/conf.d/*.conf;
}
"""
DEBIAN_CONF = "events {}\nhttp {\n    include /etc/nginx/conf.d/*.conf;\n    include /etc/nginx/sites-enabled/*;\n}\n"

NGINX_SHIM = """#!/bin/sh
echo "nginx $*" >> "$DD_STATE/nginx.log"
[ "$1" = "-t" ] && exit "${DD_NGINX_TEST:-0}"
exit 0
"""
FAILING_SHIM = "#!/bin/sh\nexit 1\n"

NGINX_FUNCTIONS = ("choose_nginx_layout", "is_stock_file", "interrogate_existing_setup", "get_ssl_cert_path", "get_ssl_key_path",
                   "render_template", "note_stock_server_block", "ensure_conf_d_included", "reload_nginx", "validate_and_reload_nginx",
                   "install_nginx_config")


def _nginx_run(conf=SLACKWARE_CONF, sites=False, answers=None, existing=None, **flags):
    """install_nginx_config on a fake /etc/nginx. -> a dict of what happened."""
    work = tempfile.mkdtemp(prefix="dd-ng-")
    try:
        nginx_dir, state, bin_dir = (os.path.join(work, n) for n in ("nginx", "state", "bin"))
        for d in (nginx_dir, state, bin_dir):
            os.mkdir(d)
        if sites:
            os.mkdir(os.path.join(nginx_dir, "sites-available"))
        if conf is not None:
            with open(os.path.join(nginx_dir, "nginx.conf"), "w") as f:
                f.write(conf)
        if existing:
            os.makedirs(os.path.dirname(os.path.join(nginx_dir, existing[0])), exist_ok=True)
            with open(os.path.join(nginx_dir, existing[0]), "w") as f:
                f.write(existing[1])
        for name, body in (("nginx", NGINX_SHIM), ("systemctl", FAILING_SHIM), ("service", FAILING_SHIM)):
            with open(os.path.join(bin_dir, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(bin_dir, name), stat.S_IRWXU)
        script = os.path.join(work, "run.sh")
        with open(script, "w") as f:
            f.write("set -eu\n" + _header() + f'SCRIPT_DIR="{os.path.dirname(INSTALL)}"\nNGINX_DIR="{nginx_dir}"\nDOMAIN=""\n'
                    + "EDIT_NGINX_CONF=${DD_EDIT:-0}\n" + "".join(_function(n) for n in NGINX_FUNCTIONS) + "install_nginx_config\necho RUN-FINISHED\n")
        env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"], DD_STATE=state, **{k: str(v) for k, v in flags.items()})
        if answers is None:
            done = subprocess.run(["sh", script], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, timeout=60)
            code, out = done.returncode, done.stdout + done.stderr
        else:
            code, out = _terminal(["sh", script], env, answers)

        def read(rel):
            path = os.path.join(nginx_dir, rel)
            return open(path).read() if os.path.isfile(path) else None
        nginx_log = os.path.join(state, "nginx.log")
        return {"code": code, "out": out, "conf": read("nginx.conf"), "dwarvendash": read("conf.d/dwarvendash.conf"),
                "default": read("sites-available/default"), "gate": read("dwarvendash-gate.conf"),
                "backups": sorted(n for n in os.listdir(nginx_dir) if n.startswith("nginx.conf.bak.")),
                "backup_text": next((read(n) for n in sorted(os.listdir(nginx_dir)) if n.startswith("nginx.conf.bak.")), None),
                "nginx_calls": open(nginx_log).read().splitlines() if os.path.exists(nginx_log) else []}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _include_tool(args, text=None):
    work = tempfile.mkdtemp(prefix="dd-inc-")
    try:
        path = os.path.join(work, "nginx.conf")
        if text is not None:
            with open(path, "w") as f:
                f.write(text)
            os.chmod(path, 0o640)
        done = subprocess.run(["python3", "-I", os.path.join(os.path.dirname(INSTALL), "tools", "nginx-include.py"), args[0], path] + args[1:],
                              capture_output=True, text=True, timeout=30)
        return done.returncode, done.stdout.strip(), (open(path).read() if os.path.exists(path) else None), oct(os.stat(path).st_mode & 0o777) if os.path.exists(path) else None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_nginx_and_pip(r):
    INC = "/etc/nginx/conf.d/*.conf"

    # python-pam and six: offered, done on a yes, never done silently.
    code, out, log, ok = _pip_run(DD_INSTALL_DEPS=1)
    r.check("installer deps: --install-deps installs python-pam and six and carries on", code == 0 and ok and "CHECK-FINISHED" in out and "python-pam: import failed" not in out
            and log == ["-m pip install python-pam six --break-system-packages"], (code, log, out[-300:]))
    code, out, log, ok = _pip_run(DD_INSTALL_DEPS=1, DD_OLD_PIP=1)
    r.check("installer deps: a pip too old for --break-system-packages is retried without it",
            ok and log == ["-m pip install python-pam six --break-system-packages", "-m pip install python-pam six"], (log, out[-300:]))
    code, out, log, ok = _pip_run(DD_INSTALL_DEPS=1, DD_PIP_FAILS=1)
    r.check("installer deps: when pip fails the missing prerequisite is still explained, and nobody there means cancel",
            not ok and code == 1 and "python-pam: import failed" in out and "CHECK-FINISHED" not in out, (code, out[-300:]))
    code, out, log, ok = _pip_run(DD_INSTALL_DEPS=1, DD_NO_PIP=1)
    r.check("installer deps: no pip is said plainly and the explanation still follows", log == [] and "pip is not available" in out and "python-pam: import failed" in out, out[-300:])
    code, out, log, ok = _pip_run()
    r.check("installer deps: with no terminal and no flag pip is never run", log == [] and not ok and code == 1 and "[y/N]" not in out, (log, code, out[-200:]))
    code, out, log, ok = _pip_run(answers=["y"])
    r.check("installer deps: a yes at the terminal installs them", ok and len(log) == 1 and "CHECK-FINISHED" in out, (log, out[-300:]))
    code, out, log, ok = _pip_run(answers=["n", "x"])
    r.check("installer deps: a no at the terminal installs nothing and the usual choice follows", log == [] and not ok and "python-pam: import failed" in out, (log, out[-300:]))
    work_ok = _run("exit 0\n")
    r.check("installer deps: python-pam already importing runs nothing", "Installing python-pam" not in work_ok[1], work_ok[1][-200:])
    helped = subprocess.run(["sh", INSTALL, "--help"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    r.check("installer: --help lists --install-deps and --edit-nginx-conf", "--install-deps" in helped.stdout and "--edit-nginx-conf" in helped.stdout)
    done = subprocess.run(["sh", INSTALL, "--install-deps", "--edit-nginx-conf", "--nonsense"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    r.check("installer: both flags are accepted as arguments (only the nonsense one is refused, before anything is touched)",
            done.returncode == 1 and "Unknown argument: --nonsense" in done.stderr and "Detected init" not in done.stderr, done.stderr[-200:])

    # The reminder about the group is the last thing printed, so it cannot scroll away under the rest.
    code, out = _script('INSTALL_DIR=/opt/x; GROUP_NAME=dwarvendash; SERVICE_ACCOUNT=svc; SCRIPT_DIR=/x\n' + _function("print_group_reminder") + _function("print_summary") + "print_summary\n")
    tail = [l for l in out.splitlines() if l.strip()]
    r.check("installer: the group reminder is the last thing the installer prints, once",
            code == 0 and out.count("Nobody can log in until") == 1 and "usermod -aG dwarvendash <username>" in "\n".join(tail[-14:])
            and out.index("docs/APPS.md") < out.index("Nobody can log in until"), tail[-6:])

    # The include helper on its own.
    code, out, text, mode = _include_tool(["check"], SLACKWARE_CONF)
    r.check("nginx include: a commented-out include does not count, it is missing", (code, out) == (0, "missing"), (code, out))
    code, out, text, mode = _include_tool(["add", INC], SLACKWARE_CONF)
    want = SLACKWARE_CONF.replace("    #include /etc/nginx/conf.d/*.conf;\n}", "    #include /etc/nginx/conf.d/*.conf;\n    include /etc/nginx/conf.d/*.conf;\n}")
    r.check("nginx include: the line goes in as the last line of the http block and nothing else changes", out == "added" and text == want, text)
    r.check("nginx include: the file keeps its permissions", mode == "0o640", mode)
    code, out, text, mode = _include_tool(["add", INC], want)
    r.check("nginx include: adding twice changes nothing", out == "present" and text == want, (out, text))
    code, out, text, mode = _include_tool(["check"], DEBIAN_CONF)
    r.check("nginx include: Debian's own include is recognised", out == "present", out)
    code, out, text, mode = _include_tool(["check"], "events {}\nhttp { include conf.d/*; }\n")
    r.check("nginx include: a relative include of conf.d/* is recognised", out == "present", out)
    code, out, text, mode = _include_tool(["check"], "events {}\nhttp { include /etc/nginx/sites-enabled/*; server { listen 80; } }\n")
    r.check("nginx include: other includes do not count", out == "missing", out)
    code, out, text, mode = _include_tool(["add", INC], "events {}\nhttp { server { listen 80; } }\n")
    r.check("nginx include: a one line http block gets the include inside it", out == "added" and text == "events {}\nhttp { server { listen 80; }\n    include /etc/nginx/conf.d/*.conf;\n}\n", text)
    code, out, text, mode = _include_tool(["add", INC], "events {}\nstream { server { listen 1; } }\n")
    r.check("nginx include: no http block is reported and the file is left alone", out == "nohttp" and text == "events {}\nstream { server { listen 1; } }\n", (out, text))
    code, out, text, mode = _include_tool(["check"], "# http {\nevents {}\n")
    r.check("nginx include: an http block that is only a comment is not one", out == "nohttp", out)

    # Slackware: no sites-available, nginx.conf does not load conf.d.
    a = _nginx_run()
    r.check("nginx layout: with no sites-available the site config goes to conf.d/dwarvendash.conf, no crash",
            a["code"] == 0 and "RUN-FINISHED" in a["out"] and a["dwarvendash"] and "DwarvenDash nginx site config" in a["dwarvendash"]
            and "listen 80 default_server" in a["dwarvendash"] and a["default"] is None, (a["code"], a["out"][-300:]))
    r.check("nginx layout: the shared gate file is written beside it", a["gate"] is not None)
    r.check("nginx layout: with no terminal nginx.conf is not edited, and the line to add is shown",
            a["conf"] == SLACKWARE_CONF and a["backups"] == [] and "conf.d/*.conf;" in a["out"], a["out"][-400:])
    r.check("nginx layout: it still validates and reloads what it did write", any(c.startswith("nginx -t") for c in a["nginx_calls"]) and "nginx -s reload" in a["nginx_calls"], a["nginx_calls"])

    b = _nginx_run(DD_EDIT=1)
    r.check("nginx layout: --edit-nginx-conf adds the include, with a backup that is the original",
            b["code"] == 0 and "conf.d/*.conf;\n}" in b["conf"] and len(b["backups"]) == 1 and b["backup_text"] == SLACKWARE_CONF, (b["code"], b["conf"], b["backups"]))
    r.check("nginx layout: and the stock server block is mentioned", "server block of its own" in b["out"], b["out"][-300:])

    c = _nginx_run(DD_EDIT=1, DD_NGINX_TEST=1)
    r.check("nginx layout: an nginx.conf nginx rejects after the edit is put back exactly, and it is said", c["conf"] == SLACKWARE_CONF
            and "put back" in c["out"] and "nginx -s reload" not in c["nginx_calls"] and c["code"] == 0, (c["conf"], c["out"][-300:]))

    d = _nginx_run(conf=DEBIAN_CONF, DD_EDIT=1)
    r.check("nginx layout: an nginx.conf that already loads conf.d is not touched or backed up", d["conf"] == DEBIAN_CONF and d["backups"] == [] and d["dwarvendash"], d["out"][-200:])

    e = _nginx_run(conf=DEBIAN_CONF, sites=True)
    r.check("nginx layout: with sites-available (Debian) it is still sites-available/default, not conf.d",
            e["default"] and "DwarvenDash nginx site config" in e["default"] and e["dwarvendash"] is None and e["conf"] == DEBIAN_CONF, e["out"][-300:])

    f = _nginx_run(existing=("conf.d/dwarvendash.conf", "# somebody else's file\n"))
    r.check("nginx layout: a dwarvendash.conf that is not ours is left alone with no terminal", f["dwarvendash"] == "# somebody else's file\n" and "leaving it alone" in f["out"] and f["code"] == 0, f["out"][-300:])

    g = _nginx_run(answers=["y"])
    r.check("nginx layout: at a terminal, yes edits nginx.conf", g["code"] == 0 and "conf.d/*.conf;\n}" in g["conf"] and len(g["backups"]) == 1, (g["code"], g["out"][-300:]))
    g = _nginx_run(answers=["n"])
    r.check("nginx layout: at a terminal, no leaves nginx.conf alone and says what to do", g["conf"] == SLACKWARE_CONF and g["backups"] == [] and "Not edited" in g["out"], g["out"][-300:])

    h2 = _nginx_run(conf=None)
    r.check("nginx layout: no nginx.conf at all is said, not a crash", h2["code"] == 0 and "RUN-FINISHED" in h2["out"] and "cannot check" in h2["out"], h2["out"][-300:])

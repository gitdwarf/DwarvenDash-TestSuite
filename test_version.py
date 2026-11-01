"""
Versioning: one VERSION file, reported consistently everywhere.
"""

import json
import os
import re
import subprocess
import urllib.request

import dd_harness as h

import sys
sys.path.insert(0, h.APP_DIR)
import version  # noqa: E402

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def run(browser, r):
    expected = open(os.path.join(h.APP_DIR, "VERSION")).read().strip()
    r.check("version: VERSION file is plain semantic versioning", bool(SEMVER.match(expected)), expected)
    r.check("version: version.get_version reads the file", version.get_version() == expected)

    with urllib.request.urlopen(h.request("/version.json"), timeout=5) as resp:
        r.check("version: /version.json reports it", json.loads(resp.read()) == {"version": expected})
        r.check("version: the Server header carries it", resp.headers.get("Server", "").startswith(f"DwarvenDash/{expected}"),
                resp.headers.get("Server"))

    out = subprocess.run(["sh", os.path.join(h.ROOT, "install.sh"), "version"], capture_output=True, text=True)
    r.check("version: install.sh version prints it", out.stdout.strip() == f"DwarvenDash {expected}", out.stdout)

    page = h.new_page(browser)
    h.open_dashboard(page, settle=1.5)
    r.check("version: the title bar shows it under the name", page.inner_text("#version") == f"v{expected}", page.inner_text("#version"))
    h.finish_page(r, page, "version")
    page.context.close()

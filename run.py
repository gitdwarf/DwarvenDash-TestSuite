#!/usr/bin/env python3
"""
One command for the whole browser suite:

    sudo python3 tests/run.py            # everything
    sudo python3 tests/run.py panels     # one module by name

Needs: root (throwaway system user), python3 playwright, and a Chromium
(set DD_CHROMIUM to its path if Playwright cannot find its own).
Starts its own server on port 18090 (DD_TEST_PORT to change it) and
removes the throwaway user afterwards. Screenshots go to
tests/screenshots/ (git-ignored when the repo has a .gitignore for it).
Exit code is 0 only if every check passed.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dd_harness as h  # noqa: E402

MODULES = ["panels", "widgets", "levels", "absolute", "sweep", "status", "icons", "static", "version", "bookmarks", "theme", "header", "probe", "layout", "hostinfo", "gpu", "installer", "sysvinit", "stoptree", "identity", "login", "reload", "proxy", "numsize", "temps", "disks", "cleanup", "logo", "sensorprobe", "uninstall", "dots", "overflow", "flipboard"]


def main(argv):
    wanted = argv or MODULES
    unknown = [m for m in wanted if m not in MODULES]
    if unknown:
        sys.exit(f"unknown module(s) {unknown}, choose from {MODULES}")

    from playwright.sync_api import sync_playwright

    results = h.Results()
    with h.Environment(), sync_playwright() as p:
        browser = h.launch_browser(p)
        for name in wanted:
            print(f"\n== {name} ==", flush=True)
            importlib.import_module(f"test_{name}").run(browser, results)
        browser.close()

    bad = results.failures()
    print(f"\n{len(results.rows) - len(bad)}/{len(results.rows)} checks passed")
    for name, _, detail in bad:
        print(f"  FAILED: {name} :: {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

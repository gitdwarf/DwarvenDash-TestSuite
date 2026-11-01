"""
Logo: one geometry in app/logo.py, and the three places it is drawn
(favicon file, dashboard header, sign-in page) must all carry exactly it.
"""

import os
import re
import sys

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import logo  # noqa: E402
import loginpage  # noqa: E402

PARTS = (logo.TRACK, logo.LIT, logo.NEEDLE, logo.ANVIL)


def _paths(text):
    return re.findall(r'\sd="([^"]+)"', text)


def run(browser, r):
    favicon = open(os.path.join(h.APP_DIR, "static", "favicon.svg")).read()
    index = open(os.path.join(h.APP_DIR, "static", "index.html")).read()
    header = re.search(r'<svg class="brand-mark".*?</svg>', index, re.S)
    sign_in = re.search(r"<svg.*?</svg>", loginpage.render().decode(), re.S)

    r.check("logo: favicon.svg is exactly what logo.favicon() makes", favicon == logo.favicon())
    r.check("logo: the dashboard header draws the same four parts",
            header is not None and tuple(_paths(header.group(0))) == PARTS, header and _paths(header.group(0)))
    r.check("logo: the sign-in page draws the same four parts",
            sign_in is not None and tuple(_paths(sign_in.group(0))) == PARTS)
    r.check("logo: the mark's parts take the theme's colours through classes, not fixed colours",
            header is not None and "#" not in header.group(0) and sign_in is not None and "#" not in sign_in.group(0))
    r.check("logo: no em-dash in the module", chr(0x2014) not in open(os.path.join(h.APP_DIR, "logo.py")).read())

"""
The title bar: brand with the version under it on the left, the machine's name
in the middle (an option, off by default), Modify and Log out on the right, and
no footer. Positions are measured on the real page, not assumed.
"""

import os
import socket
import time

import dd_harness as h


def _boxes(page):
    return page.evaluate("""() => {
      const b = (sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, w: r.width, h: r.height }; };
      return { header: b("header.brand"), name: b(".brand-name"), version: b("#version"), host: b("#brand-host"),
               modify: b("#launcher-modify-toggle"), out: b("#logout-button") };
    }""")


def _centre_y(b):
    return (b["top"] + b["bottom"]) / 2


def run(browser, r):
    expected = open(os.path.join(h.APP_DIR, "VERSION")).read().strip()
    machine = socket.gethostname()

    h.reset_user_config()
    page = h.new_page(browser)
    h.open_dashboard(page, settle=1.5)
    g = _boxes(page)
    h.shot(page, "header_01_default")

    r.check("header: there is no footer any more", page.locator("footer").count() == 0)
    r.check("header: the version is under the DwarvenDash name, as v<version>",
            page.inner_text("#version") == f"v{expected}" and g["version"]["top"] >= g["name"]["bottom"] - 1
            and abs(g["version"]["left"] - g["name"]["left"]) <= 2, (page.inner_text("#version"), g))
    r.check("header: Log out sits right beside Modify, on the same row, at the right end",
            abs(_centre_y(g["out"]) - _centre_y(g["modify"])) < 4 and 0 <= g["out"]["left"] - g["modify"]["right"] <= 16
            and g["header"]["right"] - g["out"]["right"] <= 2, g)
    r.check("header: Modify is in the top row of the title bar, not fixed to the screen corner",
            g["modify"]["top"] < g["header"]["top"] + 30 and g["modify"]["right"] <= g["header"]["right"] + 1, g)
    r.check("header: the machine name is off by default, and takes no room", page.inner_text("#brand-host") == ""
            and not page.locator("#brand-host").is_visible())

    # The option lives with the other modify-mode options.
    r.check("header: no hostname option outside modify mode", page.locator(".hostname-toggle").count() == 0)
    h.enter_modify(page)
    r.check("header: the hostname option is in the modify-mode options row, unchecked",
            page.locator("header.brand .hostname-toggle input").count() == 1 and not page.locator(".hostname-toggle input").is_checked())
    page.check(".hostname-toggle input")
    page.wait_for_function("document.getElementById('brand-host').textContent !== ''")
    g = _boxes(page)
    h.shot(page, "header_02_hostname")
    r.check("header: ticking it shows this machine's name", page.text_content("#brand-host") == machine, (page.text_content("#brand-host"), machine))
    r.check("header: the name is in the middle of the title bar",
            abs((g["host"]["left"] + g["host"]["right"]) / 2 - (g["header"]["left"] + g["header"]["right"]) / 2) <= 3, g)
    r.check("header: and between the brand and the buttons, on the same row",
            g["name"]["right"] < g["host"]["left"] and g["host"]["right"] < g["modify"]["left"]
            and abs(_centre_y(g["host"]) - _centre_y(g["name"])) < 20, g)
    measure = """() => {
      const r = (s) => document.querySelector(s).getBoundingClientRect();
      const bar = r("header.brand"), id = r(".brand-text"), act = r(".brand-actions"), host = r("#brand-host");
      const half = Math.min(bar.left + bar.width / 2 - id.right, act.left - (bar.left + bar.width / 2));
      const css = getComputedStyle(document.getElementById("brand-host"));
      return { hostW: host.width, gapW: 2 * half, size: parseFloat(css.fontSize), weight: css.fontWeight,
               off: Math.abs((host.left + host.right) / 2 - (bar.left + bar.right) / 2) };
    }"""
    # A short name is capped at a sensible size; a realistic long one fills the gap.
    page.evaluate("document.getElementById('brand-host').textContent = 'vps.dwarven.com'; fitHostname()")
    gap = page.evaluate(measure)
    h.shot(page, "header_03_long_hostname")
    r.check("header: a realistic hostname is big and bold and fills most of the gap, centred, touching neither side",
            gap["hostW"] >= 0.7 * gap["gapW"] and gap["hostW"] <= gap["gapW"] and gap["size"] > 16
            and int(gap["weight"]) >= 600 and gap["off"] <= 3, gap)
    page.evaluate("document.getElementById('brand-host').textContent = %r; fitHostname()" % machine)
    r.check("header: it is saved", h.read_user_config().get("show_hostname") is True)

    page.reload()
    page.wait_for_selector("#meters .panel")
    page.wait_for_function("document.getElementById('brand-host').textContent !== ''")
    r.check("header: it is still shown after a reload", page.text_content("#brand-host") == machine)

    # Phone width: no sideways scroll, and the name moves to a row of its own.
    page.set_viewport_size({"width": 375, "height": 900})
    time.sleep(0.4)
    g = _boxes(page)
    r.check("header: phone width has no sideways scroll", not page.evaluate("document.documentElement.scrollWidth > innerWidth"))
    r.check("header: and the machine name drops under the brand", g["host"]["top"] >= g["name"]["bottom"] - 1, g)
    page.set_viewport_size({"width": 1200, "height": 1000})
    time.sleep(0.3)

    h.enter_modify(page)
    page.uncheck(".hostname-toggle input")
    page.wait_for_function("document.getElementById('brand-host').textContent === ''")
    r.check("header: unticking hides it again and saves that", not page.locator("#brand-host").is_visible()
            and h.read_user_config().get("show_hostname") is False)

    h.finish_page(r, page, "header")
    page.context.close()
    h.reset_user_config()

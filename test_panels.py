"""
Panels: remove, re-add and reorder, for all nine panel types.

The history behind this module: an earlier hide/show design left a
StripChart permanently 0x0 once it had been hidden at construction or
resize. Panels are now genuinely removed and rebuilt, so these checks
assert exactly that: a removed panel has no DOM node, a re-added chart
is nonzero and painting live data.
"""

import time

import dd_harness as h

ALL = ["cpu-composite", "cpu-cores", "mem", "net", "disk", "load", "cpu-freq", "temps", "fans", "host"]


def _live_content(page, pid):
    if pid in h.CHART_CANVAS:
        return h.chart_is_live(h.canvas_state(page, h.CHART_CANVAS[pid]))
    if pid == "cpu-cores":
        return page.locator("#cpu-cores-bars > *").count() > 0
    if pid == "disk":
        return page.locator("#disk-bars > *").count() > 0
    if pid == "load":
        return "--" not in page.inner_text("#load-val")
    if pid in ("cpu-freq", "temps", "fans"):
        return page.locator(f"#{pid}-bars > *").count() > 0
    if pid == "host":
        return page.locator("#host-list > *").count() > 0
    return False


def _available_labels(page):
    return page.eval_on_selector_all("#available-panels .available-app-row span", "e => e.map(x => x.textContent)")


def run(browser, r):
    h.reset_user_config()
    page = h.new_page(browser)
    h.open_dashboard(page)
    h.shot(page, "panels_01_default")

    default_ids = [h.PANEL_EL[p] for p in h.DEFAULT_PANELS]
    r.check("panels: default order", h.panel_order(page) == default_ids, h.panel_order(page))
    for pid, cid in h.CHART_CANVAS.items():
        if h.PANEL_EL[pid] in default_ids:
            r.check(f"panels: default chart live ({pid})", h.chart_is_live(h.canvas_state(page, cid)))

    sig_a = h.canvas_signature(page, "net-canvas")
    time.sleep(3)
    r.check("panels: net chart pixels change over time", sig_a != h.canvas_signature(page, "net-canvas"))

    r.check("panels: no panel controls outside modify mode",
            page.locator("#meters .panel-remove").count() == 0 and page.locator("#available-panels .available-app-row").count() == 0)

    def toggle_in_corner():
        # Top row of the title bar, at its right end beside Log out.
        b = page.locator("#launcher-modify-toggle").bounding_box()
        head = page.locator("header.brand").bounding_box()
        return b["y"] < head["y"] + 30 and head["x"] + head["width"] - (b["x"] + b["width"]) < 110
    r.check("panels: Modify button sits at the top right of the title bar", toggle_in_corner())
    r.check("panels: no empty Available panels box outside modify mode", not page.locator("#available-panels").is_visible())
    h.enter_modify(page)
    r.check("panels: Done button stays at the top right of the title bar", toggle_in_corner())
    r.check("panels: modify shows a remove button per panel",
            page.locator("#meters .panel-remove").count() == len(default_ids))
    r.check("panels: the panels not on by default are available (the fake host can feed all of them)",
            _available_labels(page) == ["Individual-Cores", "Backlog", "CPU-Freq", "TEMPS", "FANS", "HOST"], _available_labels(page))

    page.locator("#available-panels .available-app-row", has_text="Individual-Cores").locator("button").click()
    time.sleep(1.5)
    r.check("panels: added panel lands at the bottom", h.panel_order(page)[-1] == "cpu-cores-panel", h.panel_order(page))
    for label in ("Backlog", "CPU-Freq", "TEMPS", "FANS", "HOST"):
        page.locator("#available-panels .available-app-row", has_text=label).locator("button").click()
        time.sleep(0.5)

    for n, pid in enumerate(ALL, start=1):
        el, label = h.PANEL_EL[pid], h.PANEL_LABEL[pid]
        page.click(f'#meters .panel-remove[title="Remove {label}"]')
        time.sleep(0.4)
        r.check(f"panels: {pid} removed, no DOM node, listed as available",
                el not in h.panel_order(page) and page.locator(f"#{el}").count() == 0 and label in _available_labels(page),
                _available_labels(page))
        h.shot(page, f"panels_02_{n}_{pid}_removed")

        page.locator("#available-panels .available-app-row", has_text=label).locator("button").click()
        time.sleep(3)
        r.check(f"panels: {pid} re-added at the bottom", h.panel_order(page)[-1] == el, h.panel_order(page))
        r.check(f"panels: {pid} shows live content, not 0x0 or placeholders", _live_content(page, pid))
        h.shot(page, f"panels_03_{n}_{pid}_readded")

    page.set_viewport_size({"width": 900, "height": 1000})
    time.sleep(2)
    for pid, cid in h.CHART_CANVAS.items():
        r.check(f"panels: {pid} chart live after window resize", h.chart_is_live(h.canvas_state(page, cid)))
    page.set_viewport_size({"width": 1200, "height": 1000})
    time.sleep(1)

    before = h.panel_order(page)
    page.drag_and_drop(f"#{before[0]} .panel-label", f"#{before[-1]} .panel-label")
    time.sleep(1.5)
    expected = before[1:-1] + [before[0], before[-1]]
    after = h.panel_order(page)
    r.check("panels: drag reorder moves first panel before last", after == expected, {"after": after, "expected": expected})
    for pid, cid in h.CHART_CANVAS.items():
        r.check(f"panels: {pid} chart live after reorder", h.chart_is_live(h.canvas_state(page, cid)))
    h.shot(page, "panels_04_reordered")

    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(3)
    r.check("panels: order persists after reload", h.panel_order(page) == after, h.panel_order(page))
    for pid, cid in h.CHART_CANVAS.items():
        r.check(f"panels: {pid} chart live after reload", h.chart_is_live(h.canvas_state(page, cid)))
    el_to_id = {v: k for k, v in h.PANEL_EL.items()}
    r.check("panels: saved panels array matches screen order",
            [p["id"] for p in h.read_user_config().get("panels", [])] == [el_to_id[e] for e in after], h.read_user_config().get("panels"))

    h.finish_page(r, page, "panels")
    page.context.close()

"""
Layout: where the three sections (panels, apps, bookmarks) sit, and whether
apps and bookmarks read as a flow or a list.

Everything is checked from what the browser actually laid out (bounding boxes),
not from the classes or attributes that were set.
"""

import json
import time

import dd_harness as h

SECTIONS = ["sec-panels", "sec-apps", "sec-bookmarks"]
NAME = {"sec-panels": "Panels", "sec-apps": "Apps", "sec-bookmarks": "Bookmarks"}


def _seed(layout=None):
    """A user with two apps and two bookmarks, and optionally a saved layout."""
    h.reset_user_config()
    cfg = {
        "launcher": [
            {"group": "Apps", "links": [
                {"title": "alpha", "url": "/apps/alpha/", "type": "app"},
                {"title": "beta", "url": "/apps/beta/", "type": "app"}]},
            {"group": "Bookmarks", "links": [
                {"title": "First", "url": "https://example.com/1", "type": "bookmark"},
                {"title": "Second", "url": "https://example.com/2", "type": "bookmark"}]},
        ],
    }
    if layout is not None:
        cfg["layout"] = layout
    with open(h.user_config_path(), "w") as fh:
        json.dump(cfg, fh)


def _open(browser, width=1300, height=1000):
    page = h.new_page(browser, width=width, height=height, color_scheme="dark")
    h.open_dashboard(page, settle=1)
    return page


def _boxes(page):
    return page.evaluate("""(ids) => Object.fromEntries(ids.map(id => {
      const r = document.getElementById(id).getBoundingClientRect();
      return [id, {left: r.left, top: r.top, right: r.right, bottom: r.bottom}];
    }))""", SECTIONS)


def _by(boxes, key):
    return sorted(SECTIONS, key=lambda s: boxes[s][key])


def _side_by_side(boxes):
    tops = [boxes[s]["top"] for s in SECTIONS]
    return max(tops) - min(tops) < 4 and all(
        boxes[a]["right"] <= boxes[b]["left"] + 1 for a, b in _pairs(_by(boxes, "left")))


def _pairs(seq):
    return list(zip(seq, seq[1:]))


def _stacked(boxes):
    return all(boxes[a]["bottom"] <= boxes[b]["top"] + 1 for a, b in _pairs(_by(boxes, "top")))


def _links(page, container):
    return page.evaluate("""(sel) => [...document.querySelectorAll(sel + ' .launcher-link-item')].map(e => {
      const r = e.getBoundingClientRect(); return {text: e.textContent.trim(), left: r.left, top: r.top, right: r.right}; })""", container)


def _is_list(links):
    """One per line AND every row stretched to the same width. (In a narrow
    column a flow also wraps to one per line, but its buttons stay ragged.)"""
    return (len(links) >= 2
            and all(abs(l["left"] - links[0]["left"]) < 2 for l in links)
            and all(abs(l["right"] - links[0]["right"]) < 2 for l in links)
            and links[1]["top"] > links[0]["top"] + 5)


def _is_flow(links):
    return len(links) >= 2 and abs(links[0]["top"] - links[1]["top"]) < 4 and links[1]["left"] > links[0]["left"]


def _click_tool(page, section, text):
    page.click(f'#tools-{section.replace("sec-", "")} .seg-btn:text-is("{text}")')
    time.sleep(0.7)


def _move(page, section, direction):
    page.click(f'#tools-{section.replace("sec-", "")} .sec-move[title$="{direction}"]')
    time.sleep(0.7)


def _sideways(page):
    return page.evaluate("document.documentElement.scrollWidth > innerWidth")


def _charts_measured(page):
    """Every strip chart's backing size matches what is on screen now."""
    for cid in ("cpu-canvas", "mem-canvas", "net-canvas"):
        st = h.canvas_state(page, cid)
        if not st or abs(st["w"] - st["cw"]) > 1 or st["cw"] < 40:
            return False, (cid, st)
    return True, None


def run(browser, r):
    # ---- Defaults: a config with no layout looks exactly as before. --------
    _seed()
    page = _open(browser)
    boxes = _boxes(page)
    r.check("layout: default is stacked in the order panels, apps, bookmarks",
            _stacked(boxes) and _by(boxes, "top") == SECTIONS, str(boxes))
    r.check("layout: default link style is a flow",
            _is_flow(_links(page, "#launcher")) and _is_flow(_links(page, "#launcher-bookmarks")))
    r.check("layout: no controls outside modify mode",
            page.locator(".sec-tools > *").count() == 0 and page.locator(".layout-switcher").count() == 0)

    # ---- Controls in modify mode. ------------------------------------------
    h.enter_modify(page)
    r.check("layout: arrange switcher offers Stacked and Columns",
            page.eval_on_selector_all(".layout-switcher-btn", "e => e.map(x => x.textContent)") == ["Stacked", "Columns"])
    r.check("layout: each section is labelled",
            page.eval_on_selector_all(".sec-name", "e => e.map(x => x.textContent)") == ["Panels", "Apps", "Bookmarks"])
    r.check("layout: list style offered for apps and bookmarks only",
            page.locator("#tools-apps .list-switcher").count() == 1 and
            page.locator("#tools-bookmarks .list-switcher").count() == 1 and
            page.locator("#tools-panels .list-switcher").count() == 0)
    r.check("layout: first section cannot move earlier, last cannot move later",
            page.locator('#tools-panels .sec-move[title$="up"]').is_disabled() and
            page.locator('#tools-bookmarks .sec-move[title$="down"]').is_disabled() and
            page.locator('#tools-apps .sec-move[title$="up"]').is_enabled())

    # ---- Stacked reorder: graphs, bookmarks, apps. -------------------------
    _move(page, "sec-bookmarks", "up")
    boxes = _boxes(page)
    r.check("layout: stacked order can be panels, bookmarks, apps",
            _stacked(boxes) and _by(boxes, "top") == ["sec-panels", "sec-bookmarks", "sec-apps"], str(boxes))
    r.check("layout: reorder saved", h.read_user_config()["layout"]["order"] == ["panels", "bookmarks", "apps"])
    _move(page, "sec-bookmarks", "down")
    r.check("layout: and back again", _by(_boxes(page), "top") == SECTIONS)

    # ---- Columns. ----------------------------------------------------------
    _click_tool_arrange = lambda text: (page.click(f'.layout-switcher-btn:text-is("{text}")'), time.sleep(0.9))
    _click_tool_arrange("Columns")
    boxes = _boxes(page)
    r.check("layout: columns puts the sections side by side, in order",
            _side_by_side(boxes) and _by(boxes, "left") == SECTIONS, str(boxes))
    r.check("layout: the panels column takes the spare width",
            (boxes["sec-panels"]["right"] - boxes["sec-panels"]["left"]) >
            (boxes["sec-apps"]["right"] - boxes["sec-apps"]["left"]) * 2, str(boxes))
    ok, why = _charts_measured(page)
    r.check("layout: charts are measured at their new width after the switch", ok, why)
    live = h.canvas_state(page, "cpu-canvas")
    time.sleep(2)
    r.check("layout: charts keep drawing in columns", h.chart_is_live(h.canvas_state(page, "cpu-canvas")), str(live))
    r.check("layout: no sideways scroll in columns", not _sideways(page))
    r.check("layout: move buttons turn sideways in columns",
            page.locator('#tools-apps .sec-move[title$="left"]').count() == 1)
    h.shot(page, "layout_01_columns")

    # ---- Apps on the left, graphs centre, bookmarks right. -----------------
    _move(page, "sec-apps", "left")
    boxes = _boxes(page)
    r.check("layout: columns order can be apps, panels, bookmarks",
            _side_by_side(boxes) and _by(boxes, "left") == ["sec-apps", "sec-panels", "sec-bookmarks"], str(boxes))
    ok, why = _charts_measured(page)
    r.check("layout: charts re-measured after moving a column", ok, why)

    # ---- One below the other. ----------------------------------------------
    _click_tool(page, "sec-apps", "List")
    r.check("layout: apps as a list are one below the other", _is_list(_links(page, "#launcher")), str(_links(page, "#launcher")))
    r.check("layout: bookmarks stay a flow until asked",
            not _is_list(_links(page, "#launcher-bookmarks")))
    _click_tool(page, "sec-bookmarks", "List")
    r.check("layout: bookmarks as a list are one below the other",
            _is_list(_links(page, "#launcher-bookmarks")), str(_links(page, "#launcher-bookmarks")))
    h.shot(page, "layout_02_three_columns")

    saved = h.read_user_config()["layout"]
    r.check("layout: everything saved",
            saved == {"mode": "columns", "order": ["apps", "panels", "bookmarks"], "apps": "list", "bookmarks": "list"}, str(saved))

    # ---- Persistence. ------------------------------------------------------
    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(1.5)
    boxes = _boxes(page)
    r.check("layout: columns and order survive a reload",
            _side_by_side(boxes) and _by(boxes, "left") == ["sec-apps", "sec-panels", "sec-bookmarks"], str(boxes))
    r.check("layout: list styles survive a reload",
            _is_list(_links(page, "#launcher")) and _is_list(_links(page, "#launcher-bookmarks")))
    ok, why = _charts_measured(page)
    r.check("layout: charts are right at first paint in columns", ok, why)

    # ---- Narrow window: columns fall back to a stack, same order. ----------
    page.set_viewport_size({"width": 700, "height": 1000})
    time.sleep(1.2)
    boxes = _boxes(page)
    r.check("layout: columns stack when the window is narrow, keeping the order",
            _stacked(boxes) and _by(boxes, "top") == ["sec-apps", "sec-panels", "sec-bookmarks"], str(boxes))
    r.check("layout: no sideways scroll when narrow", not _sideways(page))
    h.enter_modify(page)
    r.check("layout: move buttons point up and down while the columns are stacked",
            page.locator('#tools-apps .sec-move[title$="down"]').count() == 1 and
            page.locator('#tools-apps .sec-move[title$="right"]').count() == 0)
    # The JS and CSS breakpoints must agree: one pixel either side of the line.
    page.set_viewport_size({"width": 901, "height": 1000})
    time.sleep(1)
    wide_ok = _side_by_side(_boxes(page)) and page.locator('#tools-apps .sec-move[title$="right"]').count() == 1
    page.set_viewport_size({"width": 900, "height": 1000})
    time.sleep(1)
    narrow_ok = _stacked(_boxes(page)) and page.locator('#tools-apps .sec-move[title$="down"]').count() == 1
    r.check("layout: columns at 901px, stacked at 900px, arrows to match", wide_ok and narrow_ok)
    r.check("layout: crossing the breakpoint never duplicates the controls",
            page.locator(".layout-switcher").count() == 1 and page.locator(".theme-switcher").count() == 1)
    page.set_viewport_size({"width": 700, "height": 1000})
    time.sleep(1)
    ok, why = _charts_measured(page)
    r.check("layout: charts follow the window down", ok, why)
    page.set_viewport_size({"width": 1300, "height": 1000})
    time.sleep(1.2)
    r.check("layout: and go back to columns when it widens again", _side_by_side(_boxes(page)))
    ok, why = _charts_measured(page)
    r.check("layout: charts follow the window back up", ok, why)

    # ---- Back to stacked, lists kept. --------------------------------------
    h.enter_modify(page)
    _click_tool_arrange("Stacked")
    boxes = _boxes(page)
    r.check("layout: stacked again", _stacked(boxes) and _by(boxes, "top") == ["sec-apps", "sec-panels", "sec-bookmarks"], str(boxes))
    r.check("layout: lists kept when stacked", _is_list(_links(page, "#launcher")))
    ok, why = _charts_measured(page)
    r.check("layout: charts re-measured after going back to stacked", ok, why)
    page.set_viewport_size({"width": 375, "height": 900})
    time.sleep(0.8)
    r.check("layout: no sideways scroll at phone width with a list layout", not _sideways(page))

    # ---- Apps as they are, bookmarks as a list. ----------------------------
    page.set_viewport_size({"width": 1300, "height": 1000})
    time.sleep(0.5)
    _click_tool(page, "sec-apps", "Flow")
    r.check("layout: apps can be a flow while bookmarks are a list",
            _is_flow(_links(page, "#launcher")) and _is_list(_links(page, "#launcher-bookmarks")))
    h.finish_page(r, page, "layout")
    page.context.close()

    # ---- A saved layout is applied before the first paint. -----------------
    _seed({"mode": "columns", "order": ["apps", "panels", "bookmarks"], "apps": "list", "bookmarks": "list"})
    page = _open(browser)
    boxes = _boxes(page)
    r.check("layout: a seeded three-column layout comes up as saved",
            _side_by_side(boxes) and _by(boxes, "left") == ["sec-apps", "sec-panels", "sec-bookmarks"] and
            _is_list(_links(page, "#launcher")) and _is_list(_links(page, "#launcher-bookmarks")), str(boxes))

    # ---- Normalising bad values. -------------------------------------------
    got = page.evaluate("""() => normalizeLayout({mode: "diagonal", order: ["apps", "apps", "zzz"], apps: "q", bookmarks: 7})""")
    r.check("layout: bad values fall back, order is completed and de-duplicated",
            got == {"mode": "stack", "order": ["apps", "panels", "bookmarks"], "apps": "flow", "bookmarks": "flow"}, str(got))
    r.check("layout: nothing at all gives the defaults",
            page.evaluate("JSON.stringify(normalizeLayout(undefined)) === JSON.stringify(normalizeLayout(null))") and
            page.evaluate("normalizeLayout('x').mode") == "stack")
    r.check("layout: moving past either end changes nothing",
            page.evaluate("""() => { const l = normalizeLayout(); return moveSection(l, 'panels', -1) === l && moveSection(l, 'bookmarks', 1) === l; }"""))
    r.check("layout: moving never changes the original",
            page.evaluate("""() => { const l = normalizeLayout(); moveSection(l, 'apps', -1); return l.order.join() === 'panels,apps,bookmarks'; }"""))
    h.finish_page(r, page, "layout seeded")
    page.context.close()

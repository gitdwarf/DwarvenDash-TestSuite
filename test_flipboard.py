"""
The Flip board view: the flip clock (numbers only) and the split-flap board (numbers and letters) are one view with a
list beside the View list, and the panel keeps the choice under `flip`. The same list mechanism serves the dot matrix.
"""

import time

import dd_harness as h
import test_widgets as w

PANEL = {"id": "cpu-composite", "view": "flip", "merge": False, "pct": "used", "amount": "off", "total": False, "size": 6}


def run(browser, r):
    h.reset_user_config()
    w._write_config({"launcher": [], "panels": [PANEL]})
    page = h.new_page(browser)
    h.open_dashboard(page)

    got = page.evaluate("""() => [styleOf({ view: "flip" }), styleOf({ view: "flip", flip: "letters" }), styleOf({ view: "flip", flip: "x" }),
        styleOf({ view: "dots", dots: "printer" }), styleOf({ view: "gauge", gauge: "x" })]""")
    r.check("flipboard: the look is the saved one when valid, else the view's first, and none for a view without looks",
            got == ["numbers", "letters", "numbers", "printer", None], got)
    got = page.evaluate("""() => normalizePanels([{ id: "cpu-composite", view: "flip", flip: "letters" }, { id: "mem", view: "flip", flip: "x" },
        { id: "net", view: "board" }]).map(p => [p.view, p.flip === undefined ? null : p.flip])""")
    r.check("flipboard: a valid look is kept, an invalid one dropped, and the old separate Board view is no longer a view",
            got[0] == ["flip", "letters"] and got[1][1] is None and got[2][0] != "board", got)

    r.check("flipboard: numbers only is the flip clock: no name row of flaps",
            page.locator("#cpu-panel .flip-clock").count() >= 1 and page.locator("#cpu-panel .flip-name").count() == 0)
    h.enter_modify(page)
    r.check("flipboard: there is one list of looks, Numbers and Letters",
            page.eval_on_selector_all("#cpu-panel .panel-style option", "o => o.map(x => x.textContent)") == ["Numbers", "Letters"])
    r.check("flipboard: the View list has Flip board and no separate Board",
            "Flip board" in page.eval_on_selector_all("#cpu-panel .panel-view option", "o => o.map(x => x.textContent)")
            and "Board" not in page.eval_on_selector_all("#cpu-panel .panel-view option", "o => o.map(x => x.textContent)"))
    page.select_option("#cpu-panel .panel-style", "letters")
    time.sleep(3)
    r.check("flipboard: numbers and letters is the split-flap board: the name is on a row of flaps",
            page.locator("#cpu-panel .flip-board").count() >= 1 and page.locator("#cpu-panel .flip-name").count() == 1)
    saved = [p for p in h.read_user_config()["panels"] if p["id"] == "cpu-composite"][0]
    r.check("flipboard: the choice is saved under flip", saved["view"] == "flip" and saved.get("flip") == "letters", saved)
    page.select_option("#cpu-panel .panel-view", "gauge")
    time.sleep(1.5)
    r.check("flipboard: a view without looks has no list", page.locator("#cpu-panel .panel-style").count() == 0)
    page.select_option("#cpu-panel .panel-view", "flip")
    time.sleep(1.5)
    r.check("flipboard: and the look is remembered when the view comes back", page.input_value("#cpu-panel .panel-style") == "letters")
    r.check("flipboard: no page errors", not page.dd_errors, page.dd_errors[:3])
    page.close()

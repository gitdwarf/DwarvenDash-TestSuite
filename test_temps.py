"""
The TEMPS panel with a desktop's number of sensors (fourteen here, long names included): every display of it
has to stay readable, not only the two-sensor laptop the other tests use.
"""

import json
import os
import time

import dd_harness as h
import fakehost

CHIPS = [("k10temp", [("Tctl", 62000), ("Tccd1", 58000), ("Tccd2", 57000)]),
         ("nvme", [("Composite", 41000), ("Sensor 1", 43000), ("Sensor 2", 39000)]),
         ("nvme", [("Composite", 38000), ("Sensor 1", 40000)]),
         ("acpitz", [("temp1", 27800)]),
         ("iwlwifi_1", [("temp1", 44000)]),
         ("r8169_0_400:00", [("temp1", 47000)]),
         ("it8628", [("temp1", 39000), ("temp2", 51000)])]
SENSORS = 2 + sum(len(t) for _, t in CHIPS)


def _sensors(root):
    n = 10
    for name, temps in CHIPS:
        fakehost._write(root, f"sys/class/hwmon/hwmon{n}/name", name + "\n")
        for i, (label, milli) in enumerate(temps, 1):
            fakehost._write(root, f"sys/class/hwmon/hwmon{n}/temp{i}_input", f"{milli}\n")
            fakehost._write(root, f"sys/class/hwmon/hwmon{n}/temp{i}_label", label + "\n")
        n += 1


def _page(browser, view, merge, size):
    h.reset_user_config()
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"launcher": [], "panels": [{"id": "temps", "view": view, "merge": merge, "size": size}]}, f)
    page = h.new_page(browser)
    h.open_dashboard(page)
    time.sleep(3)
    return page


def _scroll_checks(browser, r, view):
    """
    Using a Show list must not move the page. The panels are rebuilt behind the reader, who is far down a page of
    many panels with the list's own tick box in view, and is clicked with the mouse where it is seen (a scripted
    check would scroll it into view itself and hide the problem).
    """
    h.reset_user_config()
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    panels = [{"id": i, "view": view, "merge": False, "size": 12} for i in ("cpu-composite", "mem", "net", "disk", "cpu-cores")]
    with open(path, "w") as f:
        json.dump({"launcher": [], "panels": panels + [{"id": "temps", "view": view, "merge": False, "size": 12}]}, f)
    page = h.new_page(browser, height=420)
    h.open_dashboard(page)
    time.sleep(3)
    h.enter_modify(page)
    page.click("#temps-panel .panel-items summary")
    item = page.locator("#temps-panel .panel-items-menu label:has-text('NVMe Composite') input").first
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    item.scroll_into_view_if_needed()
    time.sleep(0.5)
    moved = []
    for _ in (1, 2):
        before = page.evaluate("scrollY")
        box = item.bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        time.sleep(1.5)
        moved.append((before, page.evaluate("scrollY")))
    r.check(f"temps: ticking and unticking in the Show list far down a page of {view}s leaves it where it was",
            all(b > 300 and b == a for b, a in moved), moved)
    # The same for changing the display: the panel being edited stays where it is on the screen.
    top = lambda: page.evaluate("document.getElementById('temps-panel').getBoundingClientRect().top")
    placed = []
    for to in ("steps", "gauge", view):
        before = top()
        page.select_option("#temps-panel .panel-view", to)
        time.sleep(1.5)
        placed.append((to, round(before), round(top())))
    r.check(f"temps: changing the display far down a page of {view}s leaves the panel where it was",
            all(b == a for _, b, a in placed), placed)
    page.context.close()


def _dismiss_checks(browser, r):
    """The Show lists close like every other dropdown: a press elsewhere, Escape, or opening another one."""
    h.reset_user_config()
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fakehost._write(h.HOST_DIR, "proc/mounts", "/dev/sda1 / ext4 rw 0 0\n/dev/sdb1 /data ext4 rw 0 0\n")
    os.makedirs(os.path.join(h.HOST_DIR, "data"), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"launcher": [], "panels": [{"id": "disk", "view": "bars", "merge": False, "size": 6},
                                              {"id": "temps", "view": "bars", "merge": False, "size": 6}]}, f)
    page = h.new_page(browser)
    h.open_dashboard(page)
    time.sleep(3)
    h.enter_modify(page)
    opened = lambda: page.evaluate("[...document.querySelectorAll('.panel-items[open]')].map(e => e.closest('.panel').id)")
    show_temps = lambda: opened() or page.click("#temps-panel .panel-items summary")
    show_temps()
    r.check("temps: a Show list opens", opened() == ["temps-panel"], opened())
    page.locator("#temps-panel .panel-items-menu label").first.hover()
    page.mouse.click(5, 5)
    time.sleep(0.4)
    r.check("temps: a press elsewhere closes it", opened() == [], opened())
    show_temps()
    page.keyboard.press("Escape")
    time.sleep(0.4)
    r.check("temps: Escape closes it", opened() == [], opened())
    show_temps()
    page.locator("#temps-panel .panel-items-menu label input").nth(1).uncheck()
    time.sleep(1.5)
    r.check("temps: using it does not close it", opened() == ["temps-panel"], opened())
    page.click("#disk-panel .panel-items summary")
    time.sleep(0.4)
    r.check("temps: opening another Show list closes the first, so only one is open", opened() == ["disk-panel"], opened())
    page.context.close()


def _rename_checks(browser, r):
    """An unlabelled board input is "Unknown board temp N" and can be renamed in the Show list, nothing else can."""
    page = _page(browser, "bars", False, 12)
    h.enter_modify(page)
    page.click("#temps-panel .panel-items summary")
    buttons = page.locator("#temps-panel .panel-item-rename")
    r.check("temps: only the two unknown board inputs can be renamed", buttons.count() == 2, buttons.count())
    r.check("temps: they are called Unknown board temp N until named",
            page.locator("#temps-panel .disk-label", has_text="Unknown board temp").count() == 2)
    buttons.first.click()
    field = page.locator("#temps-panel .panel-item-name")
    r.check("temps: renaming offers the current name", field.input_value() == "Unknown board temp 1", field.input_value())
    field.fill("CPU (board chip)")
    field.press("Enter")
    time.sleep(2)
    names = page.evaluate("[...document.querySelectorAll('#temps-panel .disk-label')].map(e => e.textContent)")
    r.check("temps: the new name is what the panel shows", "CPU (board chip)" in names and "Unknown board temp 1" not in names, names)
    saved = next(p for p in h.read_user_config()["panels"] if p["id"] == "temps")
    r.check("temps: it is saved against the original name, and the list stays open",
            saved.get("names") == {"Unknown board temp 1": "CPU (board chip)"} and page.locator("#temps-panel .panel-items").evaluate("e => e.open"), saved)
    r.check("temps: the list shows the new name and keeps the original as its tooltip",
            page.locator("#temps-panel .panel-items-menu label", has_text="CPU (board chip)").count() == 1
            and page.locator("#temps-panel .panel-items-menu span[title='Unknown board temp 1']").count() == 1)
    page.locator("#temps-panel .panel-items-menu label", has_text="CPU (board chip)").locator("input").uncheck()
    time.sleep(2)
    saved = next(p for p in h.read_user_config()["panels"] if p["id"] == "temps")
    r.check("temps: hiding a renamed sensor is by its original name, so a rename never unhides it",
            saved.get("hidden") == ["Unknown board temp 1"] and saved.get("names") == {"Unknown board temp 1": "CPU (board chip)"}, saved)
    page.reload()
    time.sleep(3)
    h.enter_modify(page)
    page.click("#temps-panel .panel-items summary")
    page.locator("#temps-panel .panel-item-rename").first.click()
    page.locator("#temps-panel .panel-item-name").fill("never kept")
    page.locator("#temps-panel .panel-item-name").press("Escape")
    time.sleep(1.5)
    saved = next(p for p in h.read_user_config()["panels"] if p["id"] == "temps")
    r.check("temps: Escape drops the edit, and the name survives a reload", saved["names"] == {"Unknown board temp 1": "CPU (board chip)"}, saved)
    page.locator("#temps-panel .panel-items-menu label", has_text="CPU (board chip)").locator("input").check()
    time.sleep(1.5)
    page.locator("#temps-panel .panel-item-rename").first.click()
    page.locator("#temps-panel .panel-item-name").fill("   ")
    page.locator("#temps-panel .panel-item-name").press("Enter")
    time.sleep(2)
    saved = next(p for p in h.read_user_config()["panels"] if p["id"] == "temps")
    r.check("temps: an empty name puts the original back", "names" not in saved and
            page.locator("#temps-panel .disk-label", has_text="Unknown board temp 1").count() == 1, saved)
    kept = page.evaluate("normalizePanels([{id: 'temps', names: {a: '  two\\twords  ', b: '', c: 5, d: 'x'.repeat(80)}}])[0].names")
    r.check("temps: saved names are cleaned, empty and non-text ones dropped, long ones cut",
            kept == {"a": "two words", "d": "x" * 40}, kept)
    page.context.close()


def run(browser, r):
    _sensors(h.HOST_DIR)
    try:
        page = _page(browser, "gauge", True, 6)
        h.shot(page, "temps_gauge_merged")
        legend = page.eval_on_selector_all("#temps-panel .detail-bottom .detail-row", "e => e.length")
        r.check("temps: a merged gauge names every sensor in a legend, however many", legend == SENSORS, (legend, SENSORS))
        needles = page.evaluate("[...new Set([...document.querySelectorAll('#temps-panel .gauge-needle')].map(n => getComputedStyle(n).stroke))].length")
        r.check("temps: the needles are told apart by colour, not all one", needles > 3, needles)
        page.context.close()

        for size in (6, 12, 4):
            page = _page(browser, "strip", False, size)
            h.shot(page, f"temps_strip_separate_{size}")
            m = page.evaluate("""() => [...document.querySelectorAll('#temps-panel .disk-row')].map(row => {
                const l = row.querySelector('.disk-label').getBoundingClientRect(), t = row.querySelector('.chart-track').getBoundingClientRect(),
                      v = row.querySelector('.disk-percent').getBoundingClientRect(), box = row.getBoundingClientRect();
                return {track: t.width, labelEnd: l.right, trackStart: t.left, trackEnd: t.right, valueStart: v.left, rowEnd: box.right,
                        painted: row.querySelector('canvas').width > 0};
            })""")
            r.check(f"temps: separate strips at size {size}: every sensor has a strip of a usable width", len(m) == SENSORS and all(x["track"] >= 70 and x["painted"] for x in m),
                    [round(x["track"]) for x in m])
            r.check(f"temps: separate strips at size {size}: name, strip and reading never overlap or leave the cell",
                    all(x["labelEnd"] <= x["trackStart"] + 1 and x["trackEnd"] <= x["valueStart"] + 1 and x["valueStart"] <= x["rowEnd"] + 1 for x in m), m[:2])
            page.context.close()

        page = _page(browser, "bars", False, 6)
        m = page.evaluate("""() => [...document.querySelectorAll('#temps-panel .disk-row')].map(row => {
            const l = row.querySelector('.disk-label').getBoundingClientRect(), t = row.querySelector('.disk-track').getBoundingClientRect();
            return {track: t.width, over: l.right > t.left + 1}; })""")
        r.check("temps: separate bars at half width also keep a usable track and do not overlap their names",
                len(m) == SENSORS and all(x["track"] >= 70 and not x["over"] for x in m), m[:3])
        page.context.close()

        # Which sensors a panel shows is its own choice, made on the panel.
        page = _page(browser, "bars", False, 12)
        h.enter_modify(page)
        r.check("temps: the Show list counts the sensors", page.inner_text("#temps-panel .panel-items summary") == f"Show {SENSORS}/{SENSORS}",
                page.inner_text("#temps-panel .panel-items summary"))
        page.click("#temps-panel .panel-items summary")
        page.locator("#temps-panel .panel-items-menu label", has_text="NVMe Composite").first.locator("input").uncheck()
        time.sleep(2)
        names = page.evaluate("[...document.querySelectorAll('#temps-panel .disk-label')].map(e => e.textContent)")
        r.check("temps: unticking a sensor hides it and no other", len(names) == SENSORS - 1 and names.count("NVMe Composite") == 1, names)
        r.check("temps: the list stays open while it is used", page.locator("#temps-panel .panel-items").evaluate("e => e.open"))

        r.check("temps: the choice is saved", next(p for p in h.read_user_config()["panels"] if p["id"] == "temps")["hidden"] == ["NVMe Composite"],
                h.read_user_config()["panels"])
        page.reload()
        time.sleep(3)
        r.check("temps: and kept after a reload", page.locator("#temps-panel .disk-label").count() == SENSORS - 1)
        page.context.close()

        # The unit is one global choice, and only the text changes.
        page = _page(browser, "bars", False, 12)
        before = page.evaluate("[...document.querySelectorAll('#temps-panel .disk-percent')].map(e => e.textContent)")
        h.enter_modify(page)
        page.select_option(".temperature-unit", "F")
        time.sleep(2.5)
        after = page.evaluate("[...document.querySelectorAll('#temps-panel .disk-percent')].map(e => e.textContent)")
        loc = lambda tag: page.evaluate(f"localeTemperatureUnit({tag!r})")
        r.check("temps: the Auto unit follows the locale (US and others F, Australia, Germany and bare languages C)",
                [loc(t) for t in ("en-US", "en-AU", "de-DE", "en", "")] == ["F", "C", "C", "C", "C"],
                [loc(t) for t in ("en-US", "en-AU", "de-DE", "en", "")])
        r.check("temps: Celsius by default", before[0].endswith("\u00b0C"), before[:2])
        r.check("temps: Fahrenheit converts every reading (54 C is 129.2 F)", "129.2\u00b0F" in after and all(x.endswith("\u00b0F") for x in after), after[:3])
        r.check("temps: the unit is saved", h.read_user_config().get("temperature_unit") == "F")
        page.reload()
        time.sleep(3)
        r.check("temps: and kept after a reload", page.eval_on_selector("#temps-panel .disk-percent", "e => e.textContent").endswith("\u00b0F"))
        page.context.close()

        _dismiss_checks(browser, r)
        _rename_checks(browser, r)
        for view in ("ring", "strip"):
            _scroll_checks(browser, r, view)
    finally:
        fakehost.destroy(h.HOST_DIR)
        fakehost.build(h.HOST_DIR)

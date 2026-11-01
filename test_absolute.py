"""
Capacity readings on MEM and DISK: percentage (used, free, both, none), size (used,
free, both, none) and the total, each chosen on its own.

The wording is checked against a snapshot with known numbers. The real page is
checked for the layouts that carry the words: a table above and below the dial or
the strip chart, and a block (name and total, picture, reading) per series in the
bar and number views. The default must stay the compact look it always had.
"""

import json
import os
import re
import time

import dd_harness as h

SNAP = """{mem: {total_kb: 8000000, used_kb: 4000000, percent: 50, swap_total_kb: 2000000, swap_used_kb: 500000, swap_percent: 25},
          disk: [{label: "root", path: "/", ok: true, total_bytes: 107374182400, used_bytes: 53687091200, percent: 50},
                 {label: "data", path: "/d", ok: true, total_bytes: 1099511627776, used_bytes: 989560464998, percent: 90},
                 {label: "again", path: "/home", ok: true, total_bytes: 107374182400, used_bytes: 53687091200, percent: 50},
                 {label: "gone", path: "/g", ok: false}]}"""

SIZE = r"[\d.]+[BKMGTP]"


def _config(panels):
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"launcher": [], "panels": panels}, f)


def _pick(page, pid, field, value):
    page.locator(f"#{pid}-panel .panel-{field}").select_option(value)
    time.sleep(1.2)


def _logic(page, r):
    ev = page.evaluate

    def series(metric, cfg):
        return ev(f"METRICS.{metric}.series({SNAP}, {{palette: readPalette(), cfg: {json.dumps(cfg)}, state: {{}}}})")

    def texts(metric, cfg):
        return [s["text"] for s in series(metric, cfg)]

    r.check("absolute: formatBytes steps",
            ev("[0, 1023, 1536, 1048576, 8192000000, 1099511627776].map(formatBytes)") == ["0B", "1023B", "1.5K", "1.0M", "7.6G", "1.0T"])

    cases = [
        ("nothing chosen is the bare percentage", {}, ["50%", "25%"]),
        ("size used", {"amount": "used"}, ["50% | 3.8G used", "25% | 488.3M used"]),
        ("size free", {"amount": "free"}, ["50% | 3.8G free", "25% | 1.4G free"]),
        ("size both", {"amount": "both"}, ["50% | 3.8G used / 3.8G free", "25% | 488.3M used / 1.4G free"]),
        ("percent free only", {"pct": "free"}, ["50% free", "75% free"]),
        ("percent both", {"pct": "both"}, ["50% used / 50% free", "25% used / 75% free"]),
        ("size without a percentage", {"pct": "off", "amount": "used"}, ["3.8G used", "488.3M used"]),
        ("nothing at all falls back to the percentage", {"pct": "off"}, ["50%", "25%"]),
        ("total", {"total": True}, ["50% of 7.6G", "25% of 1.9G"]),
        ("everything", {"pct": "both", "amount": "both", "total": True},
         ["50% used / 50% free | 3.8G used / 3.8G free of 7.6G", "25% used / 75% free | 488.3M used / 1.4G free of 1.9G"]),
    ]
    for name, cfg, want in cases:
        got = texts("mem", cfg)
        r.check(f"absolute: {name}", got == want, got)
    r.check("absolute: headline is built from the same series",
            ev(f"METRICS.mem.headline({SNAP}, {json.dumps({'amount': 'used'})})") == "physical 50% | 3.8G used / swap 25% | 488.3M used")

    d = series("mem", {"pct": "both", "amount": "both", "total": True})
    r.check("absolute: detail has a total row, the reading with words, a big number, and is rich",
            [x["detail"]["top"] for x in d] == [{"label": "physical", "value": "7.6G"}, {"label": "swap", "value": "1.9G"}] and
            d[0]["detail"]["text"] == "50% used / 50% free | 3.8G used / 3.8G free" and d[0]["detail"]["big"] == "50%" and d[0]["detail"]["rich"] is True, d[0]["detail"])
    d = series("mem", {})
    r.check("absolute: nothing chosen is not rich, has no total row, reads '50% used'",
            all(x["detail"]["rich"] is False and x["detail"]["top"] is None for x in d) and d[0]["detail"]["text"] == "50% used")
    d = series("mem", {"pct": "free"})
    r.check("absolute: big number follows the percentage chosen", [x["detail"]["big"] for x in d] == ["50%", "75%"] and d[1]["detail"]["rich"] is True)
    r.check("absolute: big number is the size when there is no percentage",
            [x["detail"]["big"] for x in series("mem", {"pct": "off", "amount": "used"})] == ["3.8G", "488.3M"])

    r.check("absolute: disks, a lost mount stays n/a",
            texts("disk", {"total": True}) == ["50% of 100.0G", "90% of 1.0T", "50% of 100.0G", "n/a"])

    cpu = ev("METRICS['cpu-composite'].series({cpu: {overall: 8.4, per_core: {cpu0: 1, cpu1: 2}}}, {palette: readPalette(), state: {}}).map(s => s.detail)")
    r.check("absolute: composite CPU detail is the core count above and the usage below",
            cpu == [{"top": {"label": "cores", "value": "2"}, "label": "Composite CPU usage", "text": "8.4%", "rich": False}], cpu)
    r.check("absolute: panels without capacity ignore the choices",
            ev("METRICS.load.series({load: {'1m': 1, '5m': 2, '15m': 3}, cpu: {per_core: {cpu0: 1}}}, {palette: readPalette(), cfg: {pct: 'both', amount: 'both', total: true}, state: {}}).map(s => s.text)") == ["1", "2", "3"])

    cleaned = ev("""normalizePanels([{id: "mem", usage: true, free: true, total: true}, {id: "net", pct: "both", amount: "both", total: true},
                    {id: "disk", pct: "off"}, {id: "load", pct: "bogus"}]).map(p => [p.id, p.pct, p.amount, p.total])""")
    r.check("absolute: the older switches map onto the new choices, nonsense falls back",
            cleaned == [["mem", "both", "both", True], ["net", "used", "off", False], ["disk", "used", "off", False], ["load", "used", "off", False]], cleaned)
    kept = ev("""normalizePanels([{id: "mem", pct: "free", amount: "used"}, {id: "disk", pct: "off", amount: "free"}]).map(p => [p.pct, p.amount])""")
    r.check("absolute: chosen modes are kept", kept == [["free", "used"], ["off", "free"]], kept)


def run(browser, r):
    h.reset_user_config()
    _config(["mem", "disk"])
    page = h.new_page(browser)
    h.open_dashboard(page)
    _logic(page, r)

    # Controls.
    r.check("absolute: no controls outside modify mode", page.locator(".panel-pct, .panel-amount, .panel-total").count() == 0)
    h.enter_modify(page)
    for k in ("pct", "amount", "total"):
        r.check(f"absolute: {k} control on MEM and DISK only",
                sorted(page.eval_on_selector_all(f".panel-{k}", "e => e.map(x => x.closest('.panel').id)")) == ["disk-panel", "mem-panel"])
    opts = lambda sel: page.eval_on_selector_all(f"#mem-panel {sel} option", "e => e.map(x => x.value)")
    r.check("absolute: percentage offers used, free, both, none; size offers none, used, free, both",
            opts(".panel-pct") == ["used", "free", "both", "off"] and opts(".panel-amount") == ["off", "used", "free", "both"])
    r.check("absolute: defaults are % used, no size, no total",
            page.eval_on_selector("#mem-panel .panel-pct", "e => e.value") == "used" and page.eval_on_selector("#mem-panel .panel-amount", "e => e.value") == "off"
            and page.locator(".panel-total.on").count() == 0)

    # Default look: compact rows, nothing new on screen.
    r.check("absolute: default bars stay compact rows",
            page.locator("#disk-bars .disk-row").count() == 1 and page.locator("#disk-bars .detail-block").count() == 0
            and re.fullmatch(r"\d+(\.\d)?%", page.inner_text("#disk-bars .disk-percent")) is not None)

    # Strip, separate: the same rows as bars, a name, a chart and a reading each.
    rows = page.eval_on_selector_all("#mem-panel .disk-row .disk-label", "e => e.map(x => x.textContent)")
    r.check("absolute: strip shows memory split into physical and swap, not only merged", rows == ["physical", "swap"], rows)
    r.check("absolute: strip keeps its chart", page.locator("#mem-canvas").count() == 1)

    # Bars with detail: name and total, bar, reading.
    _pick(page, "disk", "amount", "both")
    page.locator("#disk-panel .panel-total").click()
    time.sleep(1.2)
    r.check("absolute: bars become a block when there is more to say", page.locator("#disk-bars .detail-block").count() == 1 and page.locator("#disk-bars .disk-row").count() == 0)
    st = os.statvfs("/")
    want_total = page.evaluate(f"formatBytes({st.f_blocks * st.f_frsize})")
    head = page.inner_text("#disk-bars .detail-head")
    r.check("absolute: block head is the name on the left and the filesystem's total on the right", head.replace("\n", "") == f"root{want_total}" or (head.startswith("root") and head.endswith(want_total)), head)
    reading = page.inner_text("#disk-bars .detail-reading")
    r.check("absolute: block reading is % used on one line, then sizes on the next", re.fullmatch(rf"\d+(\.\d)?% used\n{SIZE} used / {SIZE} free", reading) is not None, reading)
    order = page.evaluate("""() => { const b = document.querySelector('#disk-bars .detail-block');
      const y = (s) => b.querySelector(s).getBoundingClientRect().top;
      return y('.detail-head') < y('.disk-track') && y('.disk-track') < y('.detail-reading'); }""")
    r.check("absolute: block order is name and total, bar, reading", order is True)
    saved = {p["id"]: p for p in h.read_user_config()["panels"]}
    r.check("absolute: choices saved", saved["disk"]["amount"] == "both" and saved["disk"]["total"] is True and saved["disk"]["pct"] == "used", saved["disk"])

    # Gauge.
    _pick(page, "mem", "amount", "both")
    _pick(page, "mem", "pct", "both")
    page.locator("#mem-panel .panel-total").click()
    time.sleep(0.5)
    page.locator("#mem-panel .panel-view").select_option("gauge")
    time.sleep(1.5)
    r.check("absolute: gauge has one set of numbers, the header copy is hidden",
            page.eval_on_selector("#mem-val", "e => getComputedStyle(e).display") == "none")
    r.check("absolute: separate memory gauge is two gauges, each with its own total above and reading below",
            page.locator("#mem-panel .gauge-svg").count() == 2 and page.locator("#mem-panel .split-cell .detail-top .detail-row").count() == 2
            and page.locator("#mem-panel .split-cell .detail-bottom .detail-row").count() == 2)
    h.shot(page, "absolute_05_separate_gauges")
    page.locator("#mem-panel .panel-merge").click()
    time.sleep(1.2)
    r.check("absolute: merged memory gauge is one dial with two needles", page.locator("#mem-panel .gauge-svg").count() == 1 and page.locator("#mem-panel .gauge-needle").count() == 2)
    tops = page.eval_on_selector_all("#mem-panel .detail-top .detail-row", "e => e.map(x => [x.children[0].textContent, x.children[1].innerText.replace(/\\n/g, ' | ')])")
    r.check("absolute: gauge top is a table, name on the left and total on the right",
            len(tops) == 2 and tops[0][0] == "physical" and tops[1][0] == "swap" and re.fullmatch(SIZE, tops[0][1]) is not None, tops)
    bottoms = page.eval_on_selector_all("#mem-panel .detail-bottom .detail-row", "e => e.map(x => [x.children[0].textContent, x.children[1].innerText.replace(/\\n/g, ' | ')])")
    r.check("absolute: gauge readings are a table too",
            len(bottoms) == 2 and bottoms[0][0] == "physical" and re.fullmatch(rf"\d+(\.\d)?% used / \d+(\.\d)?% free \| {SIZE} used / {SIZE} free", bottoms[0][1]) is not None, bottoms)
    cols = page.evaluate("""() => { const t = [...document.querySelectorAll('#mem-panel .detail-top .detail-label')].map(e => e.getBoundingClientRect().left);
      const v = [...document.querySelectorAll('#mem-panel .detail-top .detail-val')].map(e => e.getBoundingClientRect().right);
      return [Math.abs(t[0] - t[1]) < 1, Math.abs(v[0] - v[1]) < 1]; }""")
    r.check("absolute: table columns line up, labels on a left edge and values on a right edge", cols == [True, True], cols)
    order = page.evaluate("""() => { const p = document.querySelector('#mem-panel');
      const y = (s) => p.querySelector(s).getBoundingClientRect().top;
      return y('.detail-top') < y('.gauge-svg') && y('.gauge-svg') < y('.detail-bottom'); }""")
    r.check("absolute: gauge order is totals, dial, readings", order is True)
    h.shot(page, "absolute_03_gauges")

    # The same settings in all four views: no view prints the numbers twice, and none is left bare.
    for view in ("strip", "bars", "gauge", "number"):
        page.locator("#mem-panel .panel-view").select_option(view)
        time.sleep(1.2)
        shown = page.evaluate("document.querySelector('#mem-val').offsetParent !== null")
        tables = page.locator("#mem-panel .detail-bottom .detail-row, #mem-panel .detail-block").count()
        r.check(f"absolute: {view} with rich settings shows its readings once, header copy hidden", shown is False and tables == 2, (shown, tables))
        text = page.inner_text("#mem-panel .panel-body")
        r.check(f"absolute: {view} names both physical and swap and shows their totals",
                "physical" in text and "swap" in text and len(re.findall(SIZE, text)) >= 4, text[:200])
    page.locator("#mem-panel .panel-view").select_option("strip")
    time.sleep(1.2)
    page.locator("#mem-panel .panel-pct").select_option("used")
    page.locator("#mem-panel .panel-amount").select_option("off")
    page.locator("#mem-panel .panel-total").click()
    time.sleep(1.2)
    r.check("absolute: a plain strip also hides the header copy, its table already says it",
            page.evaluate("document.querySelector('#mem-val').offsetParent !== null") is False)
    page.locator("#mem-panel .panel-pct").select_option("both")
    page.locator("#mem-panel .panel-amount").select_option("both")
    page.locator("#mem-panel .panel-total").click()
    time.sleep(1.2)

    # Strip with the same choices keeps the tables.
    page.locator("#mem-panel .panel-view").select_option("strip")
    time.sleep(1.5)
    r.check("absolute: strip carries the same two tables", page.locator("#mem-panel .detail-top .detail-row").count() == 2 and page.locator("#mem-panel .detail-bottom .detail-row").count() == 2)

    # Number: a block per series, a big number, the reading.
    page.locator("#mem-panel .panel-view").select_option("number")
    time.sleep(1.5)
    blocks = page.locator("#mem-panel .detail-block").count()
    big = page.eval_on_selector_all("#mem-panel .num-big", "e => e.map(x => x.textContent)")
    r.check("absolute: number view is a block per series with a big percentage",
            blocks == 2 and all(re.fullmatch(r"\d+(\.\d)?%", b) for b in big), (blocks, big))
    r.check("absolute: number blocks do not repeat their label under the number", page.locator("#mem-panel .num-label").count() == 0)
    h.shot(page, "absolute_01_numbers")
    over = page.evaluate("""() => [...document.querySelectorAll('#mem-panel .detail-block, #disk-panel .detail-block')].map(e => e.scrollWidth - e.clientWidth)""")
    r.check("absolute: nothing overflows its block", all(x <= 1 for x in over), over)

    # Survives a reload.
    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(2)
    r.check("absolute: survives a reload", page.locator("#mem-panel .detail-block").count() == 2 and page.locator("#disk-bars .detail-block").count() == 1)

    # Narrow, quarter-width: the block wraps, the page does not scroll sideways.
    page.set_viewport_size({"width": 420, "height": 900})
    h.enter_modify(page)
    page.locator("#disk-panel .panel-size").select_option("3")
    page.locator("#mem-panel .panel-view").select_option("gauge")
    time.sleep(1.5)
    narrow = page.evaluate("""() => [document.documentElement.scrollWidth - document.documentElement.clientWidth,
      document.querySelector('#disk-bars .disk-track').getBoundingClientRect().width,
      document.querySelector('#mem-panel .detail-bottom').getBoundingClientRect().right - document.querySelector('#mem-panel').getBoundingClientRect().right]""")
    r.check("absolute: narrow panels keep a bar and do not overflow", narrow[0] <= 0 and narrow[1] >= 40 and narrow[2] <= 0, narrow)
    # David's own case: no percentage, size used+free, total, a third-width panel, in every view.
    page.locator("#mem-panel .panel-size").select_option("4")
    page.locator("#mem-panel .panel-pct").select_option("off")
    for view in ("strip", "bars", "gauge", "number"):
        page.locator("#mem-panel .panel-view").select_option(view)
        time.sleep(1.2)
        fits = page.evaluate("""() => { const p = document.querySelector('#mem-panel').getBoundingClientRect();
          return [...document.querySelectorAll('#mem-panel .panel-body *')].every(e => e.getBoundingClientRect().right <= p.right + 1)
                 && document.documentElement.scrollWidth <= document.documentElement.clientWidth; }""")
        hidden = page.evaluate("document.querySelector('#mem-val').offsetParent === null")
        r.check(f"absolute: third-width {view} with sizes only fits and prints the numbers once", fits is True and hidden is True, (fits, hidden))
        h.shot(page, f"absolute_04_third_{view}")
    h.shot(page, "absolute_02_narrow")
    h.finish_page(r, page, "absolute")
    page.context.close()

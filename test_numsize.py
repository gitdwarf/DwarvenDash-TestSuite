"""A lone number (Composite-CPU, a single series) fills the panel width and is sized from it, not from half of it."""

import time

import dd_harness as h
import test_gpu
import test_widgets as w

PANELS = [("cpu-composite", 4), ("cpu-cores", 12)]


def run(browser, r):
    h.reset_user_config()
    cfg = [{"id": p, "view": "number", "merge": False, "pct": "used",
            "amount": "off", "total": False, "size": s} for p, s in PANELS]
    w._write_config({"launcher": [], "panels": cfg})
    page = h.new_page(browser)
    h.open_dashboard(page)
    time.sleep(3)
    for pid, _ in PANELS:
        got = page.evaluate("""(sel) => { const b = document.querySelector(sel + " .num-big");
            const c = b.closest(".num-cell, .detail-block") || b.parentElement;
            return [parseFloat(getComputedStyle(b).fontSize), c.getBoundingClientRect().width,
                    document.querySelector(sel + " .number-view").getBoundingClientRect().width,
                    document.querySelector(sel).getBoundingClientRect().width]; }""", "#" + w.IDS[pid])
        r.check(f"numsize: {pid} number is not shrunk to its minimum", got[0] > 20 and (pid != "cpu-composite" or got[1] > got[2] * 0.9), got)
    # Numbers in one panel row sit at the same height, and a bars panel centres in the room it is given.
    h.reset_user_config()
    cfg = [{"id": p, "view": "number", "merge": False, "pct": "used",
            "amount": "both", "total": True, "size": 4} for p in ("cpu-composite", "mem")]
    w._write_config({"launcher": [], "panels": cfg})
    page.reload()
    time.sleep(3)
    tops = page.evaluate("""() => [...document.querySelectorAll("#meters .panel .num-big")]
        .map(e => { const r = e.getBoundingClientRect(); return Math.round(r.top + r.height / 2); })""")
    r.check("numsize: numbers across a row are centred on one line, whatever their size",
            len(tops) >= 3 and max(tops) - min(tops) <= 1, tops)
    cfg[0]["view"] = "bars"
    w._write_config({"launcher": [], "panels": cfg})
    page.reload()
    time.sleep(3)
    gap = page.evaluate("""() => { const p = document.querySelector("#cpu-panel"), v = p.querySelector(".bars-view");
        const a = p.getBoundingClientRect(), b = v.getBoundingClientRect(), hd = p.querySelector(".panel-head").getBoundingClientRect();
        return [Math.round(b.top - hd.bottom), Math.round(a.bottom - b.bottom)]; }""")
    r.check("numsize: a bars panel sits in the middle of its room, not squashed to the top",
            abs(gap[0] - gap[1]) <= 6, gap)
    cfg = [{"id": p, "view": "ring", "merge": False, "pct": "used", "amount": "off", "total": False, "size": sz}
           for p, lv, sz in (("cpu-composite", True, 4), ("mem", False, 4), ("net", False, 4), ("cpu-cores", True, 12))]
    w._write_config({"launcher": [], "colours": True, "panels": cfg})
    page.reload()
    time.sleep(3)
    h.shot(page, "numsize_ring")
    # Dials in one row are one size and start at one height, however many each panel holds.
    cfg = [{"id": p, "view": v, "merge": False, "pct": "used", "amount": "off", "total": False, "size": 4}
           for p, v in (("cpu-composite", "gauge"), ("mem", "ring"), ("net", "ring"))]
    w._write_config({"launcher": [], "panels": cfg})
    page.reload()
    time.sleep(3)
    dials = page.evaluate("""() => [...document.querySelectorAll("#meters .panel .gauge-svg, #meters .panel .ring-svg")]
        .map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.width), Math.round(r.height)]; })""")
    rings = dials[1:]
    r.check("numsize: rings in one row share a size and a top, and a lone gauge is not shrunk to the rings' size",
            len(rings) >= 4 and len({d[0] for d in rings}) == 1 and len({d[1] for d in rings}) == 1 and dials[0][1] > rings[0][1] * 1.5, dials)
    # The LED readout is plain when Colours is off, and one of three pure colours when it is on.
    w._write_config({"launcher": [], "colours": True, "panels": cfg})
    page.reload()
    time.sleep(3)
    fills = page.evaluate("""() => { const q = (sel) => getComputedStyle(document.querySelector(sel + " .led-on")).fill;
        return [q("#mem-panel"), q("#net-panel")]; }""")
    band = lambda f: page.evaluate("""(f) => { const d = document.createElement("div"); d.style.color = ledColor(f); document.body.appendChild(d);
        const v = getComputedStyle(d).color; d.remove(); return v; }""", f)
    pure = tuple(band(f) for f in (0, 0.7, 1))
    w._write_config({"launcher": [], "colours": False, "panels": cfg})
    page.reload()
    time.sleep(3)
    plain = page.evaluate("""() => { const q = (sel) => getComputedStyle(document.querySelector(sel + " .led-on")).fill;
        return [q("#mem-panel"), q("#net-panel")]; }""")
    text = page.evaluate("getComputedStyle(document.body).color")
    r.check("numsize: with Colours on the LED readout is a pure green, yellow or red, off it follows the text colour",
            all(f in pure for f in fills) and plain == [text, text], (fills, plain, text))
    bands = page.evaluate("[0, 0.59, 0.6, 0.79, 0.8, 1].map(ledColor)")
    r.check("numsize: the LED colour bands are the quiet colour to 60%, the middle one to 80%, then the loud one, three different colours",
            bands[0] == bands[1] and bands[2] == bands[3] and bands[4] == bands[5] and len(set(bands)) == 3, bands)
    # A lone ring (one disk) is as big as a lone ring can be, the two in MEM share their panel.
    cfg = [{"id": p, "view": "ring", "merge": False, "pct": "used", "amount": "off", "total": False, "size": 4}
           for p in ("cpu-composite", "mem", "cpu-composite")]
    cfg[2] = dict(cfg[2], id="net")
    w._write_config({"launcher": [], "panels": cfg})
    page.reload()
    time.sleep(3)
    ws = page.evaluate("""() => ["#cpu-panel", "#mem-panel", "#net-panel"].map(s => [...document.querySelectorAll(s + " .ring-svg")].map(e => Math.round(e.getBoundingClientRect().width)))""")
    r.check("numsize: a panel with one ring gets a bigger ring than a panel holding two, and two share a size",
            len(ws[0]) == 1 and len(ws[1]) == 2 and ws[0][0] > ws[1][0] * 1.4 and ws[1][0] == ws[1][1], ws)
    # Gauge, two rings and a lone ring side by side: header text on one line at the top, under-text on one line
    # at the bottom, every dial centred on the line between them.
    cfg = [{"id": p, "view": v, "merge": False, "pct": "used", "amount": "both", "total": True, "size": 4}
           for p, v in (("cpu-composite", "gauge"), ("mem", "ring"), ("net", "ring"))]
    w._write_config({"launcher": [], "panels": cfg})
    page.reload()
    time.sleep(3)
    h.shot(page, "numsize_centred")
    got = page.evaluate("""() => { const c = (e) => Math.round(e.getBoundingClientRect().top + e.getBoundingClientRect().height / 2);
        const tops = [...document.querySelectorAll("#meters .detail-top")].filter(e => !e.hidden).map(e => Math.round(e.getBoundingClientRect().top));
        const bots = [...document.querySelectorAll("#meters .detail-bottom")].filter(e => !e.hidden).map(e => Math.round(e.getBoundingClientRect().bottom));
        const mid = [...document.querySelectorAll("#meters .gauge-svg, #meters .ring-svg")].map(c);
        return {tops, bots, mid}; }""")
    spread = lambda xs: max(xs) - min(xs)
    r.check("numsize: dials are centred on one line, header text shares a top and under-text a bottom",
            len(got["mid"]) >= 4 and spread(got["mid"]) <= 2 and spread(got["tops"]) <= 1 and spread(got["bots"]) <= 1, got)
    cfg = [{"id": p, "view": "steps", "merge": False, "pct": "used", "amount": "off", "total": False, "size": sz}
           for p, lv, sz in (("cpu-composite", True, 4), ("mem", False, 4), ("net", False, 4))]
    w._write_config({"launcher": [], "colours": True, "panels": cfg})
    page.reload()
    time.sleep(3)
    h.shot(page, "numsize_steps")
    # A lone ring is no taller than a lone gauge.
    cfg = [{"id": p, "view": v, "merge": False, "pct": "used", "amount": "off", "total": False, "size": 12}
           for p, v in (("cpu-composite", "gauge"),)]
    w._write_config({"launcher": [], "panels": cfg})
    page.reload()
    time.sleep(2)
    gh = page.evaluate("document.querySelector('#cpu-panel .gauge-svg').getBoundingClientRect().height")
    w._write_config({"launcher": [], "panels": [dict(cfg[0], view="ring")]})
    page.reload()
    time.sleep(2)
    rh = page.evaluate("document.querySelector('#cpu-panel .ring-svg').getBoundingClientRect().height")
    r.check("numsize: a lone ring is the same height as a lone gauge", abs(gh - rh) <= 3, (gh, rh))
    # A dial with a long reading under it and little above it is no further from its own header text than the text
    # above it needs (the rows around it are not both made as tall as the taller one). A panel on its own row, so
    # nothing beside it stretches it.
    for view in ("gauge", "ring"):
        w._write_config({"launcher": [], "panels": [{"id": "mem", "view": view, "merge": False, "pct": "used", "amount": "both", "total": True, "size": 6}]})
        page.reload()
        time.sleep(3)
        gaps = page.evaluate("""() => [...document.querySelectorAll("#mem-panel .split-cell")].map(c => {
            const t = c.querySelector(".detail-top"), d = c.querySelector(".gauge-svg, .ring-svg"), b = c.querySelector(".detail-bottom");
            return [Math.round(d.getBoundingClientRect().top - t.getBoundingClientRect().bottom), Math.round(b.getBoundingClientRect().height - t.getBoundingClientRect().height)]; })""")
        r.check(f"numsize: a {view} with more text under it than over it sits close under its header text",
                len(gaps) == 2 and all(g[0] <= 6 and g[1] >= 10 for g in gaps), gaps)
    # Rings on a second line are aligned with each other, not with the text of the line above: the GPU's lone
    # temperature ring has its own two lines under it and no blank over it, and a label sits right over its reading.
    test_gpu._say(h.FAKE_SMI, test_gpu.ONE)
    w._write_config({"launcher": [], "panels": [{"id": "gpu", "view": "ring", "merge": False, "pct": "used", "amount": "both", "total": True, "size": 4}]})
    page.set_viewport_size({"width": 1086, "height": 800})
    page.reload()
    page.wait_for_function("document.querySelectorAll('#gpu-panel .ring-svg').length === 3", timeout=15000)
    time.sleep(1.5)
    got = page.evaluate("""() => [...document.querySelectorAll("#gpu-panel .split-cell")].map(c => {
        const t = c.querySelector(".detail-top").getBoundingClientRect().height, b = c.querySelector(".detail-bottom");
        const rows = [...b.querySelectorAll(".detail-row > *")].map(e => Math.round(e.getBoundingClientRect().height));
        return [Math.round(c.getBoundingClientRect().top), Math.round(t), Math.round(b.getBoundingClientRect().height), rows.slice(0, 2)]; })""")
    r.check("numsize: a lone ring on the second line is not stretched to the text of the first line, and a label sits against its reading",
            len(got) == 3 and got[2][1] <= 2 and got[2][2] < got[0][2] - 10 and all(g[3][0] <= 16 for g in got), got)
    test_gpu._say(h.FAKE_SMI, "")
    cfg = [{"id": p, "view": v, "merge": False, "pct": "used", "amount": "off", "total": False, "size": 4}
           for p, v, lv in (("cpu-composite", "flip", True), ("mem", "flip", False), ("net", "flip", False))]
    cfg[2]["flip"] = "letters"
    w._write_config({"launcher": [], "colours": True, "panels": cfg})
    page.reload()
    time.sleep(4)
    h.shot(page, "numsize_flip")
    time.sleep(3)
    cells = page.eval_on_selector_all("#cpu-panel .flip-reading", "e => e.map(x => x.children.length)")
    r.check("numsize: a flip reading is always six cells (xxx.x%)", cells == [6], cells)
    page.context.close()

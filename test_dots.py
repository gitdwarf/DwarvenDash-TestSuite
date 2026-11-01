"""
The dot matrix view: the grid a reading becomes, the saved choices, and what is painted (black dots always, the LCD or
the surface under them, tinted by the process ink of the level when Colours is on).
"""

import time

import dd_harness as h
import test_widgets as w

PANEL = {"id": "cpu-composite", "view": "dots", "merge": False, "pct": "used", "amount": "off", "total": False, "size": 6}


def _pixels(page, sel):
    """The canvas's surface colour (a corner pixel), its darkest pixel, and its size."""
    return page.evaluate("""(sel) => { const c = document.querySelector(sel + " .dots-canvas"); if (!c) return null;
        const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
        let dark = 765, at = [0, 0, 0];
        for (let i = 0; i < d.length; i += 4) { const s = d[i] + d[i + 1] + d[i + 2]; if (s < dark) { dark = s; at = [d[i], d[i + 1], d[i + 2]]; } }
        return { corner: [d[4 * (c.width + 1)], d[4 * (c.width + 1) + 1], d[4 * (c.width + 1) + 2]], darkest: at, w: c.width, h: c.height }; }""", sel)


def _show(page, style, colours):
    h.reset_user_config()
    w._write_config({"launcher": [], "colours": colours, "panels": [dict(PANEL, dots=style)]})
    page.reload()
    time.sleep(3)
    return _pixels(page, "#cpu-panel")


def run(browser, r):
    page = h.new_page(browser)
    h.open_dashboard(page)

    # The grid: pure, so asked directly.
    grid = lambda text, f=None: page.evaluate("([t, f]) => dotGrid(t, f)", [text, f])
    g = grid("5")
    r.check("dots: one character is five columns and seven text rows, plus the gap and the bar row",
            g["cols"] == 5 and g["rows"] == 10 and len(g["lit"]) == 17 and not g["bar"], g)
    g = grid("041.2%")
    r.check("dots: a reading is its glyphs side by side with one blank column between", g["cols"] == 6 * 6 - 1, g["cols"])
    r.check("dots: a lower case letter draws as its capital, an unknown character as a blank",
            grid("s")["lit"] == grid("S")["lit"] and grid("☃")["lit"] == [], None)
    g = grid("100", 0.5)
    r.check("dots: the bar lights as many dots of the row as the fraction, from the left, on its own row",
            len(g["bar"]) == int(0.5 * g["cols"] + 0.5) and all(x == i and y == 9 for i, (x, y) in enumerate(g["bar"])), g["bar"])
    r.check("dots: a small reading still lights one dot of the bar, zero lights none, no fraction draws no bar",
            len(grid("1", 0.001)["bar"]) == 1 and not grid("1", 0)["bar"] and not grid("1", None)["bar"] and len(grid("1", 1)["bar"]) == 5)
    r.check("dots: the bar is never longer than the row", len(grid("1", 7)["bar"]) == 5)

    r.check("dots: padding zeros are left blank, real digits and the zero of 0.5 are kept",
            page.evaluate("() => [dotText('5.0%'), dotText('89.1%'), dotText('100.0%'), dotText('0.5%')]") == ["  5.0%", " 89.1%", "100.0%", "  0.5%"])

    # The saved choices.
    ok = page.evaluate("""() => { const p = normalizePanels([{ id: "cpu-composite", view: "dots", dots: "printer" }, { id: "mem", view: "dots", dots: "neon" },
        { id: "net", view: "gauge" }]); return p.map(x => [x.view, x.dots === undefined ? null : x.dots]); }""")
    r.check("dots: the dot matrix is a view, its style is kept when valid and dropped when not",
            ok == [["dots", "printer"], ["dots", None], ["gauge", None]], ok)

    # On the page.
    h.reset_user_config()
    w._write_config({"launcher": [], "panels": [dict(PANEL, view="gauge")]})
    page.reload()
    time.sleep(2.5)
    h.enter_modify(page)
    page.select_option("#cpu-panel .panel-view", "dots")
    time.sleep(2.5)
    px = _pixels(page, "#cpu-panel")
    r.check("dots: choosing Dot matrix in the View list draws the canvas", px is not None and px["w"] > 60 and px["h"] > 20, px)
    r.check("dots: with Modify on there is a style list, LCD and Printer, and no merge switch",
            page.eval_on_selector_all("#cpu-panel .panel-style option", "o => o.map(x => x.textContent)") == ["LCD", "Printer"]
            and page.locator("#cpu-panel .merge-toggle, #cpu-panel .panel-merge").count() == 0)
    page.select_option("#cpu-panel .panel-style", "printer")
    time.sleep(1)
    saved = [p for p in h.read_user_config()["panels"] if p["id"] == "cpu-composite"][0]
    r.check("dots: the style is saved on the panel", saved.get("dots") == "printer" and saved["view"] == "dots", saved)
    page.reload()
    time.sleep(2.5)
    kept = _pixels(page, "#cpu-panel")
    r.check("dots: and is still on the printer after a reload", kept and sum(kept["corner"]) > 640, kept)
    page.close()

    # What is painted.
    page = h.new_page(browser)
    h.open_dashboard(page)
    shots = {}
    for style in ("lcd", "printer"):
        for colours in (False, True):
            shots[(style, colours)] = _show(page, style, colours)
            h.shot(page, f"dots_{style}_{'colour' if colours else 'plain'}")
    r.check("dots: the dots are black in every style, with and without Colours",
            all(v and v["darkest"] == [0, 0, 0] for v in shots.values()), {k: v and v["darkest"] for k, v in shots.items()})
    lcd, paper = shots[("lcd", False)]["corner"], shots[("printer", False)]["corner"]
    r.check("dots: plain paper is lighter than the plain LCD, and the LCD is greenish", sum(paper) > sum(lcd) + 30 and lcd[1] >= lcd[2], (lcd, paper))
    for style in ("lcd", "printer"):
        plain, coloured = shots[(style, False)]["corner"], shots[(style, True)]["corner"]
        r.check(f"dots: Colours tints the {style} surface", plain != coloured, (plain, coloured))
    # The tint is the flip board's own process ink for the level (the machine is idle, so the quiet band: cyan).
    ink = page.evaluate("() => flapFace(0).match(/\\d+/g).map(Number)")
    want = [round(0.62 * p + 0.38 * i) for p, i in zip([242, 238, 224], ink)]
    got = shots[("printer", True)]["corner"]
    r.check("dots: coloured printer paper is the paper mixed with the same process ink the flip board's flaps use",
            all(abs(a - b) <= 3 for a, b in zip(got, want)) and got[2] > got[0], (got, want, ink))
    lcd_c = shots[("lcd", True)]["corner"]
    r.check("dots: the LCD's overlay is that ink laid over the glass, so the red falls and the blue and green stay",
            lcd_c[0] + 20 < min(lcd_c[1], lcd_c[2]) and lcd_c[0] < shots[("lcd", False)]["corner"][0] - 40, (lcd_c, shots[("lcd", False)]["corner"]))
    # Shape: one lit dot painted in each style, then the pixel at the corner of the square it would fill.
    corner = page.evaluate("""() => { const out = {};
        for (const style of ["lcd", "printer"]) {
          const c = document.createElement("canvas"); paintDots(c, { cols: 1, rows: 1, lit: [[0, 0]], bar: [] }, style, null, 100, 100);
          const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data, k = c.width / 100;
          const grid = { cols: 1, rows: 1 }; const pitch = Math.min(100 / (1 + (style === "printer" ? 6.4 : 3)), 100 / 3);
          const at = (x, y) => { const i = 4 * (Math.round(y * k) * c.width + Math.round(x * k)); return d[i] + d[i + 1] + d[i + 2]; };
          const r = pitch * (style === "printer" ? 0.4 : 0.38);
          out[style] = [at(50, 50), at(50 - r * 0.9, 50 - r * 0.9)];
        } return out; }""")
    r.check("dots: the LCD's dots are square (the corner of the square is inked) and the printer's are round (it is not)",
            corner["lcd"][0] < 30 and corner["lcd"][1] < 30 and corner["printer"][0] < 30 and corner["printer"][1] > 300, corner)
    r.check("dots: the dot matrix panel is a single display with no merge", page.locator("#cpu-panel .dots-view").count() == 1)
    r.check("dots: no page errors", not page.dd_errors, page.dd_errors[:3])
    page.close()

    # Tapping a panel rebuilds its display. The row must not shrink and spring back while the new one waits for its
    # row's matched text heights: record the heights of both panels on every frame for 600ms after the tap.
    record = """() => { window.__heights = []; const t0 = performance.now(); const hh = (id) => Math.round(document.getElementById(id).getBoundingClientRect().height);
        const f = () => { window.__heights.push([hh("cpu-panel"), hh("mem-panel")]); if (performance.now() - t0 < 600) requestAnimationFrame(f); }; requestAnimationFrame(f); }"""
    for view, style in (("dots", "lcd"), ("dots", "printer"), ("gauge", None), ("ring", None)):
        h.reset_user_config()
        cfg = [{"id": p, "view": view, "size": 4, **({"dots": style} if style else {})} for p in ("cpu-composite", "mem")]
        w._write_config({"launcher": [], "panels": cfg})
        page = h.new_page(browser, 1068, 800)
        h.open_dashboard(page, 3)
        before = page.evaluate("[...document.querySelectorAll('#cpu-panel, #mem-panel')].map(e => Math.round(e.getBoundingClientRect().height))")
        box = page.locator("#cpu-panel .panel-body").first.bounding_box()
        page.evaluate(record)
        page.wait_for_timeout(60)
        page.mouse.click(box["x"] + 20, box["y"] + 20)
        page.wait_for_timeout(800)
        seen = {tuple(x) for x in page.evaluate("window.__heights")}
        r.check(f"dots: tapping a {view} panel{' (' + style + ')' if style else ''} does not move the row (heights {before})", seen == {tuple(before)}, sorted(seen))
        page.close()

    # The startup sequences, as a pure timetable first. LCD: off, all on, each overlay, off. Printer: white paper, a
    # full printing on each colour of paper, white paper. Without Colours there are no overlays and one sheet.
    page = h.new_page(browser, 1068, 400)
    h.open_dashboard(page, 0)
    ev = lambda js: page.evaluate(js)
    r.check("dots: the sequences run 3100ms (LCD) and 3800ms (printer) with Colours, 1600 and 1800 without",
            ev("[dotsSweepMs('lcd', true), dotsSweepMs('printer', true), dotsSweepMs('lcd', false), dotsSweepMs('printer', false)]") == [3100, 3800, 1600, 1800])
    frames = ev("[-5, 0, 399, 400, 1199, 1200, 1700, 2200, 2699, 2700, 3099, 3100, 9999].map((t) => dotsSweepFrame(t, 'lcd', true)).map((f) => [f.show, f.ink])")
    r.check("dots: the LCD is off, then on, then cyan, yellow and magenta overlays on the lit screen, then off, then the reading",
            frames == [["off", None], ["off", None], ["off", None], ["all", None], ["all", None], ["all", 0], ["all", 1], ["all", 2], ["all", 2], ["off", None], ["off", None], ["real", None], ["real", None]], frames)
    rows = ev("[0, 99, 100, 450, 799, 800, 999].map((t) => dotsSweepFrame(400 + t, 'printer', true)).map((f) => [f.show, f.ink, f.rows])")
    r.check("dots: the printer prints a row every 100ms on the first sheet, to all eight rows, and holds the full sheet",
            rows == [["rows", 0, 0], ["rows", 0, 0], ["rows", 0, 1], ["rows", 0, 4], ["rows", 0, 7], ["rows", 0, 8], ["rows", 0, 8]], rows)
    sheets = ev("[1399, 1400, 2399, 2400, 3399, 3400, 3799, 3800].map((t) => dotsSweepFrame(t, 'printer', true)).map((f) => [f.show, f.ink])")
    r.check("dots: then the next sheet is yellow, then magenta, then clean white paper, then the reading",
            sheets == [["rows", 0], ["rows", 1], ["rows", 1], ["rows", 2], ["rows", 2], ["off", None], ["off", None], ["real", None]], sheets)
    counts = ev("""(() => { const g = dotGrid('  5.0%', 0.5), n = g.cols;
        const of = (frame) => { const x = dotsSweepGrid(g, frame); return [x.lit.length, x.bar.length]; };
        return { cols: n, off: of({ show: 'off' }), all: of({ show: 'all' }), rows3: of({ show: 'rows', rows: 3 }), rows8: of({ show: 'rows', rows: 8 }), same: dotsSweepGrid(g, { show: 'all' }).rows === g.rows }; })()""")
    r.check("dots: a frame lights no dots, every dot (seven text rows and the bar's row), or the first rows printed, in the same size of grid",
            counts["off"] == [0, 0] and counts["all"] == [7 * counts["cols"], counts["cols"]] and counts["rows3"] == [3 * counts["cols"], 0]
            and counts["rows8"] == [7 * counts["cols"], counts["cols"]] and counts["same"], counts)
    r.check("dots: a run's length is the sequence's, and part by part in turn they follow one another",
            ev("(() => { const p = sweepPlan(true, 2, 'in-turn', 3100); return [p.total - p.rampAt, p.partGap, sweepLocal(p.rampAt + 3100 + 50, p, 1), sweepLocal(10, p, 0)]; })()") == [6200, 3100, 50, 10 - 1000])
    page.close()

    # On the page, with the startup sweep: every picture the dots are painted as, in order. The wake-up stages first
    # (blank), then the sequence of the look, then the reading.
    record = """() => { window.__paints = []; const paint = paintDots;
        window.paintDots = function (canvas, grid, style, tint, ...rest) { window.__paints.push([grid.lit.length, grid.bar.length, tint]); return paint(canvas, grid, style, tint, ...rest); }; }"""
    for style, colours in (("lcd", True), ("printer", True), ("lcd", False), ("printer", False)):
        h.reset_user_config()
        w._write_config({"launcher": [], "startup_sweep": True, "colours": colours,
                         "panels": [{"id": "cpu-composite", "view": "dots", "dots": style, "size": 4}]})
        page = h.new_page(browser, 1068, 800)
        page.goto(h.URL)
        page.wait_for_selector("#meters .panel")
        page.evaluate(record)
        page.evaluate("""() => { window.__stages = []; const t0 = performance.now();
            const f = () => { const p = document.getElementById("cpu-panel"); const c = p.querySelector(".dots-canvas");
              window.__stages.push([p.className, c ? getComputedStyle(c).filter : ""]); if (performance.now() - t0 < 9000) requestAnimationFrame(f); }; requestAnimationFrame(f); }""")
        page.wait_for_timeout(9500)
        paints = page.evaluate("window.__paints")
        seq = []
        for p in paints:
            if not seq or seq[-1] != p: seq.append(p)
        cols = max(p[1] for p in paints)
        ink = page.evaluate("[0, 1, 2].map((i) => flapFace(BANDS[i]))")
        tints = [p[2] for p in seq]
        label = f"{style}, Colours {'on' if colours else 'off'}"
        everything, text_only = (7 * cols, cols), None
        runs = [(p[0], p[1], p[2]) for p in seq]
        if style == "lcd":
            lead = runs[:6] if colours else runs[:3]
            want = [(0, 0, None), (7 * cols, cols, None)] + ([(7 * cols, cols, i) for i in ink] if colours else []) + [(0, 0, None)]
            r.check(f"dots: the {label} sequence on the page is off, all on{', then cyan, yellow and magenta overlays' if colours else ''}, off", lead == want, (lead, want))
        else:
            want = [(0, 0, None)]
            for i in (ink if colours else [None]):
                # (With Colours off the white paper and the empty plain sheet are the one picture.)
                want += ([(0, 0, i)] if i is not None else []) + [(k * cols, 0, i) for k in range(1, 8)] + [(7 * cols, cols, i)]
            want += [(0, 0, None)]
            r.check(f"dots: the {label} sequence on the page is white paper, then every row printed one at a time on {'each colour' if colours else 'the paper'}, then white", runs[:len(want)] == want, (runs[:len(want)], want))
        r.check(f"dots: and then the {label} display shows the reading (a few dots, not all of them)",
                runs[len(want)][0] < 7 * cols and runs[len(want)][0] > 0 and (colours or all(p[2] is None for p in runs)), runs[len(want):len(want) + 2])
        stages = page.evaluate("window.__stages")
        r.check(f"dots: the {label} panel gains the wake-up stage classes and loses them again",
                (not colours or sum("sweep-" in f[0] for f in stages) > 5) and "sweep-" not in stages[-1][0] and page.evaluate("sweeping.size") == 0, stages[-1])
        if colours:
            grey = [f for f in stages if "sweep-nocolour" in f[0]]
            r.check(f"dots: the colour stage of the {label} panel is grey and colour returns after it",
                    grey and all("grayscale" in f[1] for f in grey[2:]) and "grayscale" not in stages[-1][1], (len(grey), stages[-1][1]))
        page.close()

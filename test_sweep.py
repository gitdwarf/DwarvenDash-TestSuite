"""
The startup sweep: the dashboard waking up like a car dash, an option off by default.

Two halves. The arithmetic and the timetable are pure functions, checked exactly. Then the
page is recorded frame by frame from the moment it loads, because a sweep is a sequence and
only a recording can say whether the stages came in the right order, whether panels waited
their turn, and whether the dash ends on the real readings.
"""

import json
import os
import re
import time

import dd_harness as h

RECORDER = """
window.__rec = [];
(() => {
  const t0 = performance.now();
  const tick = () => {
    const t = performance.now() - t0;
    const grab = (id) => {
      const p = document.getElementById(id);
      if (!p) return null;
      const n = p.querySelector(".gauge-needle");
      const f = p.querySelector(".disk-fill");
      return { cls: p.className, needle: n ? 1 - Math.atan2(100 - n.getAttribute("y2"), n.getAttribute("x2") - 100) / Math.PI : null,
               fill: f ? parseFloat(f.style.width) : null };
    };
    window.__rec.push({ t, load: grab("load-panel"), disk: grab("disk-panel") });
    if (t < 9000) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();
"""


def _config(panels, **extra):
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = {"launcher": [], "panels": panels}
    cfg.update(extra)
    with open(path, "w") as f:
        json.dump(cfg, f)


def _pure(page, r):
    ev = page.evaluate
    plan_c, plan_p = ev("sweepPlan(true)"), ev("sweepPlan(false)")
    r.check("sweep: a coloured panel has four lead-in stages before the run", plan_c["headerAt"] < plan_c["colourAt"] < plan_c["footerAt"] < plan_c["rampAt"], plan_c)
    r.check("sweep: a plain panel goes straight to the run", plan_p["rampAt"] == 0 and plan_p["headerAt"] == 0 and plan_p["total"] < plan_c["total"], plan_p)
    st = lambda t, p: ev(f"sweepStage({t}, sweepPlan({p}))")
    r.check("sweep: at the start nothing has appeared", st(0, "true") == {"header": False, "colour": False, "footer": False})
    r.check("sweep: header, then colour, then footer",
            st(plan_c["headerAt"] + 1, "true") == {"header": True, "colour": False, "footer": False}
            and st(plan_c["colourAt"] + 1, "true") == {"header": True, "colour": True, "footer": False}
            and st(plan_c["footerAt"] + 1, "true") == {"header": True, "colour": True, "footer": True})
    r.check("sweep: a plain panel has everything from the start", st(0, "false") == {"header": True, "colour": True, "footer": True})

    v = lambda t, plan: ev(f"sweepValue({t}, 40, 100, sweepPlan({plan}))")
    up, down, settle, ramp = ev("[SWEEP_UP_MS, SWEEP_DOWN_MS, SWEEP_SETTLE_MS]") + [plan_c["rampAt"]]
    r.check("sweep: zero until the run starts", v(0, "true") == 0 and v(ramp - 1, "true") == 0)
    r.check("sweep: full at the top of the run, empty after the way down", abs(v(ramp + up, "true") - 100) < 1e-6 and abs(v(ramp + up + down, "true")) < 1e-6)
    r.check("sweep: it ends on the real value and stays there", abs(v(ramp + up + down + settle, "true") - 40) < 1e-6 and v(99999, "true") == 40)
    up_leg = [v(ramp + up * i / 10, "true") for i in range(11)]
    down_leg = [v(ramp + up + down * i / 10, "true") for i in range(11)]
    settle_leg = [v(ramp + up + down + settle * i / 10, "true") for i in range(11)]
    inc = lambda xs: all(b >= a for a, b in zip(xs, xs[1:]))
    r.check("sweep: up, then down, then up to the value, each leg smooth and one way",
            inc(up_leg) and inc(down_leg[::-1]) and inc(settle_leg), (up_leg, down_leg, settle_leg))
    r.check("sweep: a plain panel runs the same legs from time zero", abs(v(up, "false") - 100) < 1e-6)

    r.check("sweep: numbers in a text scale together and keep their decimals",
            ev("scaleNumbers('57.8% | 3.8G used / 3.8G free', 0.5)") == "28.9% | 1.9G used / 1.9G free")
    s = ev("""sweepSeries([{key: 'a', value: 40, max: 100, text: '40%', detail: {text: '40% used', big: '40%'}},
                         {key: 'b', value: 0, max: 100, text: '0%', detail: null}], __T__, sweepPlan(false))""".replace("__T__", str(up // 2)))
    r.check("sweep: a series is caught part way, its texts moving with it, a zero left alone",
            0 < s[0]["value"] < 100 and s[0]["text"] != "40%" and s[0]["detail"]["big"] == s[0]["text"] and s[1]["text"] == "0%" and s[1]["detail"] is None, s)
    r.check("sweep: together every panel starts at zero", ev("sweepOffsets([sweepPlan(true), sweepPlan(false), sweepPlan(true)], 'together')") == [0, 0, 0])
    t = [plan_c["total"], plan_p["total"]]
    r.check("sweep: in turn each starts when the one before ends", ev("sweepOffsets([sweepPlan(true), sweepPlan(false), sweepPlan(true)], 'in-turn')") == [0, t[0], t[0] + t[1]])

    r.check("sweep: strips, gauges, rings, steps, flip boards, dot matrix, bars and numbers are swept", ev("SWEEP_VIEWS") == ["strip", "gauge", "ring", "steps", "flip", "dots", "bars", "number"])
    strip = ev("""(() => { const cv = document.createElement('canvas'); cv.style.width = '600px'; cv.style.height = '40px'; document.body.appendChild(cv);
                   const c = new StripChart(cv, false); let got = null; c._draw = (lines) => { got = lines; };
                   for (const v of [10, 20, 30]) c.push([{key: 'a', value: v, max: 100, color: '#fff'}]);
                   const out = { length: c.history.a.length, xs: got[0].points.map((p) => p[0]), width: c.width }; cv.remove(); return out; })()""")
    r.check("sweep: a strip starts on the left and grows to the right, it does not start flat across the chart",
            strip["length"] == 3 and strip["xs"][0] == 0 and 0 < strip["xs"][1] < strip["width"] / 20 and strip["xs"][2] < strip["width"] / 10, strip)
    after = ev("""(() => { const cv = document.createElement('canvas'); cv.style.width = '600px'; cv.style.height = '40px'; document.body.appendChild(cv);
                   const c = new StripChart(cv, false); let got = null; c._draw = (lines) => { got = lines; };
                   for (let i = 0; i <= 20; i++) c.trail([{key: 'a', value: i * 5, max: 100, color: '#fff'}], i / 20);
                   c.push([{key: 'a', value: 50, max: 100, color: '#fff'}]);
                   const xs = got[0].points.map((p) => p[0]); const out = { n: xs.length, first: xs[0], last: xs[xs.length - 1], width: c.width }; cv.remove(); return out; })()""")
    r.check("sweep: after the sweep the strip carries on from the right edge, it does not start again at the left",
            after["n"] == ev("HISTORY_LENGTH") and after["first"] == 0 and after["last"] > after["width"] - 1, after)
    r.check("sweep: the status dots go off, up, down, off, then the real state",
            ev("[0, 299, 300, 599, 600, 899, 900, 1199].map(sweepDots)") == ["dark", "dark", "lit", "lit", "down", "down", "dark", "dark"] and ev("SWEEP_DOT_PLAN.total") == 1200)
    dots = ev("""(() => { const d = document.createElement('span'); d.className = 'status-dot'; d.dataset.app = 'x'; document.body.appendChild(d);
                    applyStatus({x: false}); const cls = () => d.className;
                    const out = [cls()]; holdStatus('dark'); out.push(cls()); holdStatus('lit'); out.push(cls());
                    applyStatus({x: false}); out.push(cls()); holdStatus('down'); out.push(cls()); holdStatus('dark'); out.push(cls()); holdStatus(null); out.push(cls()); d.remove(); return out; })()""")
    r.check("sweep: held dark a dot shows neither colour, held lit it is green, and let go it is its real state, down",
            dots == ["status-dot down", "status-dot", "status-dot up", "status-dot up", "status-dot down", "status-dot", "status-dot down"], dots)
    plan_t = ev("sweepPlan(true, 3, 'in-turn')")
    r.check("sweep: in turn, a panel leaves room for the run of each of its parts",
            plan_t["total"] == plan_c["rampAt"] + 3 * ev("SWEEP_RUN_MS") and plan_t["partGap"] == ev("SWEEP_RUN_MS") and ev("sweepPlan(true, 3, 'together')")["partGap"] == 0)
    parts = ev("""(() => { const plan = sweepPlan(false, 2, 'in-turn'); const list = [{key: 'a', value: 40, max: 100, text: '40%'}, {key: 'b', value: 20, max: 100, text: '20%'}];
                   return [SWEEP_UP_MS / 2, SWEEP_RUN_MS + 1, SWEEP_RUN_MS + SWEEP_UP_MS / 2, 2 * SWEEP_RUN_MS].map((t) => sweepSeries(list, t, plan).map((s) => s.value)); })()""")
    r.check("sweep: in turn, part two waits at zero while part one runs, then runs while part one rests on its real value",
            0 < parts[0][0] < 100 and parts[0][1] == 0 and parts[1][0] == 40 and parts[1][1] < 1 and parts[2][0] == 40 and 0 < parts[2][1] < 100 and parts[3] == [40, 20], parts)
    r.check("sweep: the strip's line is drawn across as the run goes, nothing before it",
            ev("[sweepTrailAt(0, sweepPlan(true)), sweepTrailAt(sweepPlan(true).rampAt, sweepPlan(true)), sweepTrailAt(99999, sweepPlan(true))]") == [None, 0, 1])
    r.check("sweep: the header copy has one rule, in code, not also in the stylesheet",
            ev("headerRepeatsView('number', []) && headerRepeatsView('gauge', []) && !headerRepeatsView('bars', [])")
            and 'data-view="number"] .panel-val' not in open(os.path.join(h.APP_DIR, "static", "style.css")).read())


def _record(browser, panels, wait=6.5, **cfg):
    h.reset_user_config()
    _config(panels, **cfg)
    page = h.new_page(browser)
    page.add_init_script(RECORDER)
    page.goto(h.URL)
    time.sleep(wait)
    rec = page.evaluate("window.__rec")
    return page, rec


def _first(rec, key, test):
    """Time of the first frame, once the panel has data on it, where test holds."""
    return next((f["t"] for f in rec if f[key] and (f[key]["needle"] is not None or f[key]["fill"] is not None) and test(f[key])), None)


CORES_RECORDER = """
window.__cores = [];
(() => {
  const t0 = performance.now();
  const tick = () => {
    const ns = [...document.querySelectorAll('#cpu-cores-panel .gauge-needle')].map((n) => 1 - Math.atan2(100 - n.getAttribute('y2'), n.getAttribute('x2') - 100) / Math.PI);
    window.__cores.push([performance.now() - t0, ns]);
    if (performance.now() - t0 < 9000) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();
"""


def _waits(page, r):
    """A first reading can have no data for a panel (a core's percentage needs two samples, so the first
    reading after the server starts has none). The sweep must wait for it, but not for ever."""
    out = page.evaluate("""() => {
      const fake = { cfg: { id: 'fake', view: 'gauge' }, metric: { series: () => have }, state: {} };
      let have = []; panelViews.fake = fake; const was = sweepWaits; const on = currentConfig.startup_sweep; currentConfig.startup_sweep = true; sweepWaits = 0;
      const empty = [sweepDue(), sweepDue()];
      have = [{ key: 'a' }]; const filled = sweepDue();
      have = []; sweepWaits = 0; let n = 0; while (!sweepDue() && n < 50) n++;
      delete panelViews.fake; sweepWaits = was; currentConfig.startup_sweep = on; return { empty, filled, gaveUpAfter: n, limit: SWEEP_WAIT_READINGS }; }""")
    r.check("sweep: it waits while a panel has nothing to draw, starts once it has, and gives up after a few readings",
            out["empty"] == [False, False] and out["filled"] is True and out["gaveUpAfter"] == out["limit"], out)


def _modify(browser, r):
    """Pressing Modify mid-sweep takes one press and ends the sweep, nothing carries on into the new panels.
    Pressing before the sweep has even started means it never starts."""
    h.reset_user_config()
    _config(["cpu-composite", "mem", "net", "load", "cpu-cores", "disk"], startup_sweep=True, sweep_order="in-turn")
    press = lambda page: (lambda b: (page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2), page.mouse.down(), time.sleep(0.1), page.mouse.up()))(
        page.locator("#launcher-modify-toggle").bounding_box())
    page = h.new_page(browser)
    page.goto(h.URL)
    time.sleep(3.5)
    r.check("sweep: sequential, six panels, still running after a few seconds", page.evaluate("runningSweeps.size") == 1)
    press(page)
    time.sleep(0.8)
    r.check("sweep: one press on Modify mid-sweep enters Modify mode and ends the sweep",
            page.evaluate("[modifyMode, runningSweeps.size, sweeping.size]") == [True, 0, 0], page.evaluate("[modifyMode, runningSweeps.size, sweeping.size]"))
    time.sleep(2)
    r.check("sweep: and nothing starts up again in the new panels", page.evaluate("[runningSweeps.size, sweeping.size]") == [0, 0])
    page.context.close()

    page = h.new_page(browser)
    # The live stream is held back two seconds so the press certainly comes first.
    page.add_init_script("""(() => { const Real = window.EventSource;
      window.EventSource = class extends Real { set onmessage(fn) { super.onmessage = (e) => setTimeout(() => fn(e), 2000); } }; })();""")
    page.goto(h.URL)
    time.sleep(0.6)
    press(page)
    time.sleep(6)
    r.check("sweep: pressing before the sweep has started means it never does", page.evaluate("[modifyMode, runningSweeps.size, sweeping.size]") == [True, 0, 0],
            page.evaluate("[modifyMode, runningSweeps.size, sweeping.size]"))
    page.context.close()


def _cores(browser, r):
    """In turn, each core makes its run on its own. The first reading has no core data (a percentage needs
    two samples), so the sweep has to wait for it or it is over before there is anything to run."""
    h.reset_user_config()
    _config([{"id": "cpu-cores", "view": "gauge", "merge": False, "levels": False, "size": 12}], startup_sweep=True, sweep_order="in-turn")
    page = h.new_page(browser)
    page.add_init_script(CORES_RECORDER)
    page.goto(h.URL)
    time.sleep(9)
    rec = [f for f in page.evaluate("window.__cores") if f[1]]
    cores = len(rec[-1][1])
    peak = lambda i: max(rec, key=lambda f: f[1][i])
    peaks = [peak(i) for i in range(cores)]
    r.check("sweep: every core makes a full run, to near the top of its dial", all(p[1][i] > 0.6 for i, p in enumerate(peaks)), [round(p[1][i], 2) for i, p in enumerate(peaks)])
    r.check("sweep: and one after another, in core order", all(peaks[i][0] < peaks[i + 1][0] - 800 for i in range(cores - 1)), [round(p[0]) for p in peaks])
    r.check("sweep: while one core runs the others wait at the bottom",
            all(max(f[1][j] for j in range(cores) if j != i) < 0.3 for i in range(cores) for f in [peaks[i]]))
    page.context.close()


def run(browser, r):
    h.reset_user_config()
    page = h.new_page(browser)
    h.open_dashboard(page)
    _pure(page, r)
    _waits(page, r)
    page.context.close()

    panels = [{"id": "disk", "view": "bars"}, {"id": "load", "view": "gauge"}]

    # Off by default: nothing sweeps.
    page, rec = _record(browser, panels, wait=3)
    r.check("sweep: off by default, the dash never runs a sweep",
            not page.evaluate("sweeping.size") and not any(f["load"] and "sweep-" in f["load"]["cls"] for f in rec))
    final_off = [f for f in rec if f["disk"] and f["disk"]["fill"] is not None]
    r.check("sweep: and the disk bar never goes up to full", all(f["disk"]["fill"] < 99 for f in final_off) if final_off else True)
    page.context.close()

    # On, together.
    page, rec = _record(browser, panels, startup_sweep=True, colours=True)
    first = lambda key, test: _first(rec, key, test)
    firstdata = next(f["load"] for f in rec if f["load"] and f["load"]["needle"] is not None)
    r.check("sweep: the first frame of a coloured panel is blank, no header, no colour, no footer",
            firstdata["cls"].count("sweep-no") == 3 and firstdata["needle"] < 0.02, firstdata)
    t_head = first("load", lambda g: "sweep-noheader" not in g["cls"] and "sweep-nofooter" in g["cls"])
    t_col = first("load", lambda g: "sweep-nocolour" not in g["cls"] and "sweep-nofooter" in g["cls"])
    t_foot = first("load", lambda g: "sweep-nofooter" not in g["cls"] and "sweep-nocolour" not in g["cls"] and "sweep-noheader" not in g["cls"])
    r.check("sweep: header appears, then colour, then footer, in that order", None not in (t_head, t_col, t_foot) and t_head < t_col < t_foot, (t_head, t_col, t_foot))
    waiting = [f["load"]["needle"] for f in rec if f["load"] and "sweep-nofooter" in f["load"]["cls"] and f["load"]["needle"] is not None]
    r.check("sweep: the needles stay at zero through the lead-in", waiting and max(waiting) < 0.02, waiting[:3])
    needle_max = max(f["load"]["needle"] for f in rec if f["load"] and f["load"]["needle"] is not None)
    r.check("sweep: then they run to full", needle_max > 0.8, needle_max)
    ends = [f for f in rec if f["load"]]
    r.check("sweep: and the classes are gone at the end", "sweep-" not in ends[-1]["load"]["cls"] and "sweep-" not in ends[-1]["disk"]["cls"], ends[-1]["load"]["cls"])
    fills = [f["disk"]["fill"] for f in rec if f["disk"] and f["disk"]["fill"] is not None]
    peak, low_after = max(fills), None
    i_peak = fills.index(peak)
    low_after = min(fills[i_peak:])
    st = os.statvfs("/")
    actual = round((1 - st.f_bavail / st.f_blocks) * 100, 1)
    r.check("sweep: the plain disk bar runs up to full, back to empty, and ends on the real reading",
            peak > 97 and low_after < 3 and abs(fills[-1] - actual) < 3, (peak, low_after, fills[-1], actual))
    t_disk_end = next(f["t"] for f in rec if f["disk"] and f["disk"]["fill"] is not None and f["disk"]["fill"] > 97)
    t_dial_full = next(f["t"] for f in rec if f["load"] and f["load"]["needle"] is not None and f["load"]["needle"] > 0.8)
    r.check("sweep: together means the disk bar and the dial reach full at about the same time",
            abs(t_disk_end - t_dial_full) < 700, (t_disk_end, t_dial_full))
    page.context.close()

    # On, in turn: the second panel waits for the first.
    page, rec = _record(browser, panels, wait=8, startup_sweep=True, colours=True, sweep_order="in-turn")
    t_disk_top = _first(rec, "disk", lambda g: g["fill"] is not None and g["fill"] > 97)
    t_load_wake = _first(rec, "load", lambda g: "sweep-noheader" not in g["cls"])
    r.check("sweep: in turn, the second panel stays blank until the first has finished",
            t_disk_top is not None and t_load_wake is not None and t_load_wake > t_disk_top + 700, (t_disk_top, t_load_wake))
    r.check("sweep: and it has finished by the end", "sweep-" not in [f for f in rec if f["load"]][-1]["load"]["cls"])
    page.context.close()

    # Changing the view of a panel wakes that panel, only that one.
    page, rec = _record(browser, panels, wait=3.5, startup_sweep=True, colours=True)
    h.enter_modify(page)
    page.locator("#disk-panel .panel-view").select_option("gauge")
    run_ids = page.evaluate("[...sweeping]")
    needles = page.evaluate("""() => new Promise((res) => { const out = []; const t0 = performance.now();
      const tick = () => { const n = document.querySelector('#disk-panel .gauge-needle'); const l = document.querySelector('#load-panel .gauge-needle');
        const frac = (e) => e ? 1 - Math.atan2(100 - e.getAttribute('y2'), e.getAttribute('x2') - 100) / Math.PI : null;
        out.push([frac(n), frac(l)]);
        if (performance.now() - t0 < 3200) requestAnimationFrame(tick); else res(out); };
      requestAnimationFrame(tick); })""")
    disk_n = [a for a, b in needles if a is not None]
    load_n = [b for a, b in needles if b is not None]
    r.check("sweep: changing a panel's view sweeps that panel and no other", run_ids == ["disk"], run_ids)
    r.check("sweep: the new disk dial runs to full", max(disk_n) > 0.8, max(disk_n))
    r.check("sweep: the other panel is left alone", max(load_n) - min(load_n) < 0.2, (min(load_n), max(load_n)))
    h.shot(page, "sweep_01_after_view_change")

    # The option and its sub-option.
    r.check("sweep: the startup sweep switch is in modify mode, ticked", page.locator(".sweep-toggle input").is_checked())
    r.check("sweep: and offers simultaneous or sequential",
            page.eval_on_selector_all(".sweep-order option", "e => e.map(x => [x.value, x.textContent])") == [["together", "Simultaneous"], ["in-turn", "Sequential"]])
    page.locator(".sweep-order").select_option("in-turn")
    time.sleep(0.6)
    r.check("sweep: the choice is saved", h.read_user_config().get("sweep_order") == "in-turn")
    page.uncheck(".sweep-toggle input")
    time.sleep(0.6)
    r.check("sweep: unticking saves it off and hides the sub-option",
            h.read_user_config().get("startup_sweep") is False and page.locator(".sweep-order").count() == 0)
    page.check(".sweep-toggle input")
    time.sleep(0.4)
    r.check("sweep: ticking runs one now, so it can be seen", page.evaluate("sweeping.size") > 0)
    page.context.close()

    # A click ends it on the real readings.
    page, rec = _record(browser, panels, wait=0.9, startup_sweep=True, colours=True)
    r.check("sweep: it is running before the click", page.evaluate("sweeping.size") > 0)
    page.mouse.click(5, 5)
    time.sleep(0.3)
    left = page.evaluate("""() => [sweeping.size, document.querySelectorAll('.sweep-noheader, .sweep-nocolour, .sweep-nofooter').length,
                                     parseFloat(document.querySelector('#disk-bars .disk-fill').style.width)]""")
    st = os.statvfs("/")
    actual = round((1 - st.f_bavail / st.f_blocks) * 100, 1)
    r.check("sweep: a click ends it at once, classes cleared, the bar on the real reading", left[0] == 0 and left[1] == 0 and abs(left[2] - actual) < 3, (left, actual))
    page.context.close()

    # Reduced motion: no sweep at all, whatever the option says.
    h.reset_user_config()
    _config(panels, startup_sweep=True)
    ctx = browser.new_context(viewport={"width": 1200, "height": 1000}, extra_http_headers=h.auth_header(h.TEST_USER), reduced_motion="reduce")
    page = ctx.new_page()
    page.dd_errors = []
    page.goto(h.URL)
    page.wait_for_selector("#meters .panel")
    time.sleep(1.5)
    r.check("sweep: with reduced motion asked for, nothing sweeps", page.evaluate("sweeping.size") == 0 and page.evaluate("sweepAllowed()") is False)
    ctx.close()

    _cores(browser, r)
    _modify(browser, r)

    page = h.new_page(browser)
    page.goto(h.URL)
    page.wait_for_selector("#meters .panel")
    h.finish_page(r, page, "sweep")
    page.context.close()

"""
Graduated colours: an optional per-panel switch ("Colours"), off by default.

Colours depend on live values, so the checks compare what is on screen
against what gradeColor() says for that same value, instead of assuming
any particular reading.
"""

import json
import os
import time

import dd_harness as h


def _write_config(config):
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f)


def _choose(page, pid, selector, value):
    page.locator(f"#{pid}-panel {selector}").select_option(value)
    time.sleep(1.5)


GRADE_COMPARE = """(args) => {
  const [selector, fraction] = args;
  const el = document.querySelector(selector);
  const probe = document.createElement("div");
  probe.style.background = gradeColor(fraction);
  document.body.appendChild(probe);
  const want = getComputedStyle(probe).backgroundColor;
  probe.remove();
  const prop = el.matches(".disk-fill") ? "backgroundColor" : "color";
  return [getComputedStyle(el)[prop], want];
}"""


def run(browser, r):
    h.reset_user_config()
    _write_config({"launcher": [],                    "panels": ["cpu-composite", "mem", "net", "disk", "load"]})
    page = h.new_page(browser)
    h.open_dashboard(page)

    # The scale is the theme's own: its `up` colour until half, sliding to its `down` colour by 90%.
    colour = lambda c: page.evaluate("""(c) => { const d = document.createElement("div"); d.style.color = c; document.body.appendChild(d);
        const v = getComputedStyle(d).color.match(/\\d+/g).map(Number).slice(0, 3); d.remove(); return v; }""", c)
    near = lambda a, b: all(abs(x - y) <= 4 for x, y in zip(a, b))
    hue = lambda f: colour(page.evaluate(f"gradeColor({f})"))
    up, down = colour("var(--ok)"), colour("var(--bad)")
    r.check("levels: low values are the theme's up colour, high ones its down colour, the middle slides between",
            near(hue(0.2), up) and near(hue(0.5), up) and near(hue(0.9), down) and near(hue(1), down)
            and not near(hue(0.7), up) and not near(hue(0.7), down), [hue(0.2), hue(0.7), hue(0.9), up, down])

    # A green and a red whose hues are more than half the wheel apart (110 and 348 degrees) meet through yellow.
    middle = page.evaluate("""() => { const root = document.documentElement.style;
        root.setProperty("--ok", "#39ff14"); root.setProperty("--bad", "#ff1744");
        const hues = [0.6, 0.7, 0.8].map((f) => gradeHsl(f)[0]);
        root.removeProperty("--ok"); root.removeProperty("--bad"); return hues; }""")
    r.check("levels: the scale turns the short way round the colour wheel, through yellow and orange",
            all(10 <= m <= 110 for m in middle) and middle[0] > middle[1] > middle[2], middle)

    r.check("levels: no Colours control outside modify mode", page.locator(".colours-toggle").count() == 0)
    for locale, word in (("en-US", "Colors"), ("en-CA", "Colours"), ("en-GB", "Colours")):
        spelled = h.new_page(browser, locale=locale)
        h.open_dashboard(spelled)
        h.enter_modify(spelled)
        r.check(f"levels: the switch is spelled by the browser's language ({locale} says {word})",
                spelled.locator(".colours-toggle").inner_text().strip() == word, spelled.locator(".colours-toggle").inner_text())
        spelled.context.close()
    h.enter_modify(page)
    r.check("levels: one Colours switch for the whole dashboard, none on the panels",
            page.locator(".colours-toggle").count() == 1 and page.locator(".panel-levels").count() == 0)
    r.check("levels: off by default", not page.locator(".colours-toggle input").is_checked())

    # Bars (disk): the fill colour is the series colour until Colours is on.
    plain = page.eval_on_selector("#disk-panel .disk-fill", "e => getComputedStyle(e).backgroundColor")
    page.check(".colours-toggle input")
    time.sleep(2)
    frac = page.eval_on_selector("#disk-panel .disk-fill", "e => parseFloat(e.style.width) / 100")
    got, want = page.evaluate(GRADE_COMPARE, ["#disk-panel .disk-fill", frac])
    r.check("levels: disk bar is coloured by its own level", got == want, (got, want, frac))
    r.check("levels: the switch shows it is on", page.locator(".colours-toggle input").is_checked())
    r.check("levels: choice saved", h.read_user_config().get("colours") is True)
    r.check("levels: NET is graded against the link speed the host reports, DISK against its fill",
            page.evaluate("isGraded({id: 'net'})") is True and page.evaluate("isGraded({id: 'disk'})") is True)
    r.check("levels: NET scale is the link speed, not the busiest moment seen",
            page.evaluate("gradedScale(METRICS.net.series(latestSnap, {palette: readPalette(), cfg: {}, state: {peak: 1}}), true)[0].max") == 125000000)
    r.check("levels: without a known link speed NET is left uncoloured",
            page.evaluate("isGraded({id: 'net'}, {net: {rx_bytes_per_sec: 1, tx_bytes_per_sec: 1}})") is False)
    disk = lambda hidden: page.evaluate("""(hidden) => { const d = (path) => ({path, label: path, ok: true, percent: 50, used_bytes: 1, total_bytes: 2});
        return METRICS.disk.series({disk: [d("/a"), d("/b"), d("/c")]}, {palette: readPalette(), cfg: {hidden}, state: {}}).map(s => s.color); }""", hidden)
    disks, rest = disk([]), disk(["/a"])
    r.check("levels: each disk has its own colour, so merged needles and legend dots differ", len(set(disks)) == 3, disks)
    r.check("levels: hiding a disk does not recolour the others", rest == disks[1:], (rest, disks))
    r.check("levels: the plain colour is not the graded one", plain != got, (plain, got))

    # Number (mem): text colour follows the value.
    _choose(page, "mem", ".panel-view", "number")
    time.sleep(1.5)
    frac = float(page.locator("#mem-panel .num-big").first.inner_text().rstrip("%")) / 100
    got, want = page.evaluate(GRADE_COMPARE, ["#mem-panel .num-big", frac])
    r.check("levels: memory number is coloured by its level", got == want, (got, want, frac))

    # Gauge (load): coloured zones appear on the dial, only with Colours on.
    _choose(page, "load", ".panel-view", "gauge")
    page.uncheck(".colours-toggle input")
    time.sleep(1.5)
    r.check("levels: gauge has no zones while Colours is off", page.locator("#load-panel .gauge-zone").count() == 0)
    page.check(".colours-toggle input")
    time.sleep(1.5)
    r.check("levels: gauge shows 30 coloured zones", page.locator("#load-panel .gauge-zone").count() == 30)
    r.check("levels: gauge zones run green to red",
            page.eval_on_selector_all("#load-panel .gauge-zone", "e => [e[0].getAttribute('stroke'), e[e.length-1].getAttribute('stroke')]") ==
            [page.evaluate("gradeColor(0.5/30)"), page.evaluate("gradeColor(29.5/30)")])
    zone = page.eval_on_selector("#load-panel .gauge-zone", "e => { const c = getComputedStyle(e); return [parseFloat(c.strokeWidth), c.fill]; }")
    track = page.eval_on_selector("#load-panel .gauge-arc", "e => parseFloat(getComputedStyle(e).strokeWidth)")
    r.check("levels: gauge zones are drawn as a solid strip, as thick as the dial track, not hairlines",
            zone[0] >= 10 and zone[0] >= track and zone[1] == "none", (zone, track))
    r.check("levels: gauge still has its three needles", page.locator("#load-panel .gauge-needle").count() == 3)
    h.shot(page, "levels_01_gauge")

    # Strip (cpu): still draws live with the gradient.
    time.sleep(3)
    r.check("levels: graded strip chart is live", h.chart_is_live(h.canvas_state(page, "cpu-canvas")))

    # Persists, and turns off again.
    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(2)
    r.check("levels: graded look survives a reload", page.locator("#load-panel .gauge-zone").count() == 30)
    h.enter_modify(page)
    page.uncheck(".colours-toggle input")
    time.sleep(1.5)
    r.check("levels: switching off removes the zones", page.locator("#load-panel .gauge-zone").count() == 0)

    # Config hygiene: a panel carries no colour setting of its own any more.
    cleaned = page.evaluate("""normalizePanels([{id: "net", levels: true}, {id: "mem", levels: true}]).map(p => "levels" in p)""")
    r.check("levels: panels no longer store a colour choice", cleaned == [False, False], cleaned)
    h.finish_page(r, page, "levels")
    page.context.close()

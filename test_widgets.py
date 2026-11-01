"""
Widget views, merge and size.

Per panel: a view (strip, bars, gauge, number), a merge switch for
multi-series metrics, a size (full, half, third, quarter). All of it is
editable in Modify mode only, saved per user, and the legacy config
(a bare list of panel ids) still loads.
"""

import re
import json
import os
import time

import dd_harness as h

VIEWS = ["strip", "bars", "gauge", "ring", "steps", "flip", "dots", "number"]
IDS = {"cpu-composite": "cpu-panel", "cpu-cores": "cpu-cores-panel", "mem": "mem-panel",
       "net": "net-panel", "disk": "disk-panel", "load": "load-panel"}
CAN_MERGE = {"cpu-cores", "mem", "net", "disk"}
# What proves each view is on screen and carries data.
MARKER = {"strip": "canvas", "bars": ".disk-row", "gauge": "svg.gauge-svg", "ring": "svg.ring-svg", "steps": "svg.steps-svg", "flip": ".flip-cell", "dots": ".dots-canvas", "number": ".num-big"}


def _write_config(config):
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f)


def _panel(page, pid):
    return page.locator(f"#{IDS[pid]}")


def _box(page, pid):
    return page.locator(f"#{IDS[pid]}").bounding_box()


def _choose(page, pid, selector, value):
    _panel(page, pid).locator(selector).select_option(str(value))
    time.sleep(1.5)


def _saved(pid):
    return next(p for p in h.read_user_config()["panels"] if p["id"] == pid)


def run(browser, r):
    # Legacy config: a bare list of ids, one of them unknown.
    h.reset_user_config()
    _write_config({"launcher": [], "panels": ["mem", "bogus", "net", "mem"]})
    page = h.new_page(browser)
    h.open_dashboard(page)
    r.check("widgets: legacy id list loads, unknown and repeated ids dropped",
            h.panel_order(page) == ["mem-panel", "net-panel"], h.panel_order(page))
    r.check("widgets: legacy panels keep today's look (strip charts)",
            all(_panel(page, p).locator("canvas").count() >= 1 for p in ("mem", "net")))
    r.check("widgets: no view, size or merge controls outside modify mode",
            page.locator(".panel-view, .panel-size, .panel-merge").count() == 0)
    page.context.close()

    # Fresh user, all six panels.
    h.reset_user_config()
    _write_config({"launcher": [],                    "panels": ["cpu-composite", "mem", "net", "load", "cpu-cores", "disk"]})
    page = h.new_page(browser)
    h.open_dashboard(page)
    h.enter_modify(page)
    r.check("widgets: every panel has a view and a size chooser in modify mode",
            page.locator(".panel-view").count() == 6 and page.locator(".panel-size").count() == 6)
    r.check("widgets: merge switch only on multi-series metrics",
            sorted(page.eval_on_selector_all(".panel-merge", "e => e.map(x => x.closest('.panel').id)")) ==
            sorted(IDS[p] for p in CAN_MERGE))

    # Every metric in every view, with real data on screen.
    for pid in IDS:
        for view in VIEWS:
            _choose(page, pid, ".panel-view", view)
            time.sleep(1.5)
            panel = _panel(page, pid)
            r.check(f"widgets: {pid} as {view} renders", panel.locator(MARKER[view]).count() >= 1)
            text = panel.inner_text()
            r.check(f"widgets: {pid} as {view} shows no NaN or undefined", "NaN" not in text and "undefined" not in text, text)
            if view == "strip":
                cid = panel.locator("canvas").first.get_attribute("id")
                for _ in range(8):
                    if not cid or h.chart_is_live(h.canvas_state(page, cid)):
                        break
                    time.sleep(0.5)
                r.check(f"widgets: {pid} strip is nonzero in size and painting",
                        h.chart_is_live(h.canvas_state(page, panel.locator("canvas").first.get_attribute("id") or "")) if panel.locator("canvas").first.get_attribute("id") else _box(page, pid)["width"] > 0)
            if view in ("gauge", "number"):
                r.check(f"widgets: {pid} as {view} shows values", any(c.isdigit() for c in text), text)
            r.check(f"widgets: {pid} view saved as {view}", _saved(pid)["view"] == view, _saved(pid))
    h.shot(page, "widgets_01_all_number")

    # Multi-needle gauges.
    _choose(page, "load", ".panel-view", "gauge")
    ends = page.eval_on_selector_all("#load-panel .gauge-needle", "e => e.map(n => [n.getAttribute('x2'), n.getAttribute('y2')])")
    r.check("widgets: LOAD gauge has three needles with real coordinates",
            len(ends) == 3 and all(x and y and "NaN" not in x + y for x, y in ends), ends)
    r.check("widgets: LOAD gauge legend names 1 min, 5 min, 15 min",
            page.eval_on_selector_all("#load-panel .detail-bottom .detail-name", "e => e.map(x => x.textContent)") == ["1 min", "5 min", "15 min"])
    cores = h.run_count_cores() if hasattr(h, "run_count_cores") else os.cpu_count()
    _choose(page, "cpu-cores", ".panel-view", "gauge")
    svgs = page.locator("#cpu-cores-panel .gauge-svg").count()
    needles = page.locator("#cpu-cores-panel .gauge-needle").count()
    r.check("widgets: separate cores gauge is one small gauge per core, each with its own needle", svgs == cores and needles == cores, (svgs, needles, cores))
    r.check("widgets: each small gauge names its core", page.eval_on_selector_all("#cpu-cores-panel .detail-bottom .detail-name", "e => e.map(x => x.textContent)")
            == [f"core{i}" for i in range(cores)])
    h.shot(page, "widgets_02_gauges")

    # Merge: the parts are laid over each other on one display. Separate gives each its own.
    _choose(page, "net", ".panel-view", "gauge")
    r.check("widgets: NET gauge separate is two gauges", _panel(page, "net").locator(".gauge-svg").count() == 2 and _panel(page, "net").locator(".gauge-needle").count() == 2)
    _panel(page, "net").locator(".panel-merge").click()
    time.sleep(1.5)
    r.check("widgets: NET gauge merged is one gauge with both needles", _panel(page, "net").locator(".gauge-svg").count() == 1 and _panel(page, "net").locator(".gauge-needle").count() == 2)
    r.check("widgets: NET merge saved", _saved("net")["merge"] is True)
    r.check("widgets: merged button says so", _panel(page, "net").locator(".panel-merge").inner_text() == "Merged")
    _choose(page, "net", ".panel-view", "number")
    r.check("widgets: numbers cannot be merged, so there is no merge button in the number view", _panel(page, "net").locator(".panel-merge").count() == 0)
    r.check("widgets: and the number view shows each part on its own even though NET is merged", _panel(page, "net").locator(".num-big").count() == 2)
    _choose(page, "cpu-cores", ".panel-view", "bars")
    r.check("widgets: separate cores bars are one row per core", _panel(page, "cpu-cores").locator(".disk-row").count() == cores)
    _panel(page, "cpu-cores").locator(".panel-merge").click()
    time.sleep(1.5)
    r.check("widgets: merged cores bars are a stack with a bar for every core",
            _panel(page, "cpu-cores").locator(".stack-tracks").count() == 1 and _panel(page, "cpu-cores").locator(".stack-tracks .disk-track").count() == cores
            and _panel(page, "cpu-cores").locator(".disk-row").count() == 0)
    _panel(page, "cpu-cores").locator(".panel-merge").click()
    time.sleep(1.5)
    r.check("widgets: un-merged brings the rows back", _panel(page, "cpu-cores").locator(".disk-row").count() == cores)
    _choose(page, "cpu-cores", ".panel-view", "gauge")
    _panel(page, "cpu-cores").locator(".panel-merge").click()
    time.sleep(1.5)
    r.check("widgets: merged cores gauge is one dial with a needle per core",
            _panel(page, "cpu-cores").locator(".gauge-svg").count() == 1 and _panel(page, "cpu-cores").locator(".gauge-needle").count() == cores)
    h.shot(page, "widgets_04_merged_cores_gauge")
    r.check("widgets: merged cores gauge drops its readings only past six",
            _panel(page, "cpu-cores").locator(".detail-bottom .detail-row").count() == (cores if cores <= 6 else 0))
    _panel(page, "cpu-cores").locator(".panel-merge").click()
    time.sleep(1)
    _choose(page, "disk", ".panel-view", "bars")
    _panel(page, "disk").locator(".panel-merge").click()
    time.sleep(1.5)
    r.check("widgets: merged disks are a stack of bars", _panel(page, "disk").locator(".stack-tracks .disk-fill").count() >= 1 and _panel(page, "disk").locator(".disk-row").count() == 0)

    # Many rows flow across the panel, a few stay stacked.
    flow = lambda n: page.evaluate("""(n) => { const panel = document.createElement('div'); panel.className = 'panel'; panel.dataset.size = '12'; panel.style.width = '900px'; document.body.appendChild(panel);
      const host = document.createElement('div'); panel.appendChild(host);
      const v = createView('bars', host, {layout: 'separate'});
      v.update(Array.from({length: n}, (_, i) => ({key: 'c' + i, label: 'core' + i, value: i * 10, max: 100, color: '#fff', text: i * 10 + '%'})));
      const rows = [...host.querySelectorAll('.disk-row')].map((r) => r.getBoundingClientRect());
      const tracks = [...host.querySelectorAll('.disk-track')].map((t) => Math.round(t.getBoundingClientRect().left));
      panel.remove();
      return { columns: new Set(rows.map((r) => Math.round(r.left))).size, rows: rows.length, trackStarts: new Set(tracks).size }; }""", n)
    many, few = flow(8), flow(3)
    r.check("widgets: eight rows flow across the panel, core 0 | core 1 | core 2 and on", many["columns"] >= 2 and many["rows"] == 8, many)
    r.check("widgets: and the bars in each column start in the same place", many["trackStarts"] == many["columns"], many)
    r.check("widgets: three rows stay stacked in one column", few["columns"] == 1, few)

    # Size decides how many sit across: full 4, half 3, third 2, quarter 1. One rule for every view.
    across = lambda size, kind: page.evaluate("""([size, kind]) => { const panel = document.createElement('div'); panel.className = 'panel'; panel.dataset.size = size;
      panel.style.width = '1000px'; document.body.appendChild(panel); const host = document.createElement('div'); panel.appendChild(host);
      let sel;
      if (kind === 'gauge') { const v = createView('gauge', host, {layout: 'separate'});
        v.update(Array.from({length: 12}, (_, i) => ({key: 'c' + i, label: 'core' + i, value: 10, max: 100, color: '#fff', text: '10%'}))); sel = '.split-cell'; }
      if (kind === 'number') { const v = createView('number', host, {});
        v.update(Array.from({length: 12}, (_, i) => ({key: 'c' + i, label: 'core' + i, value: 10, max: 100, color: '#fff', text: '10%'}))); sel = '.num-cell'; }
      if (kind === 'table') { const t = detailTable('bottom'); host.appendChild(t.el);
        t.set(Array.from({length: 12}, (_, i) => ({label: 'core' + i, value: '1%', color: '#fff'}))); sel = '.detail-row'; }
      const lefts = new Set([...host.querySelectorAll(sel)].map((e) => Math.round(e.getBoundingClientRect().left / 4)));
      panel.remove(); return lefts.size; }""", [size, kind])
    for kind in ("gauge", "number", "table"):
        got = [across(sz, kind) for sz in (12, 6, 4, 3)]
        r.check(f"widgets: {kind} fits 4, 3, 2 and 1 across at full, half, third and quarter", got == [4, 3, 2, 1], got)
    steady = page.evaluate("""() => { const panel = document.createElement('div'); panel.className = 'panel'; panel.dataset.size = '3'; panel.style.width = '300px';
      document.body.appendChild(panel); const host = document.createElement('div'); panel.appendChild(host);
      const v = createView('number', host, {}); const mk = (t) => [{key: 'a', label: 'a', value: 1, max: 100, color: '#fff', text: t}, {key: 'b', label: 'b', value: 1, max: 100, color: '#fff', text: t}];
      const widths = []; for (const t of ['1%', '100%', '45.5%', '8%']) { v.update(mk(t)); widths.push([...host.querySelectorAll('.num-cell')].map((e) => Math.round(e.getBoundingClientRect().width * 10)).join()); }
      const sizes = new Set(); panel.remove(); return new Set(widths).size; }""")
    r.check("widgets: numbers keep their cell width whatever the reading, so nothing jumps about", steady == 1, steady)

    # Every view is named for one series or for several.
    names = page.evaluate("['strip', 'bars', 'gauge', 'ring', 'steps', 'flip', 'dots', 'number'].map((v) => [viewLabel(v, 1), viewLabel(v, 2)])")
    r.check("widgets: every view menu entry is singular for one series and plural for several",
            names == [["Strip", "Strips"], ["Bar", "Bars"], ["Gauge", "Gauges"], ["Ring", "Rings"], ["Steps", "Steps"], ["Flip board", "Flip boards"], ["Dot matrix", "Dot matrix"], ["Number", "Numbers"]], names)
    _choose(page, "cpu-composite", ".panel-view", "bars")
    time.sleep(1.2)
    lab = lambda pid: page.eval_on_selector(f"#{pid}-panel .panel-view option[value=bars]", "e => e.textContent")
    r.check("widgets: a one-bar panel (composite CPU) says Bar and a two-bar panel (MEM) says Bars", lab("cpu") == "Bar" and lab("mem") == "Bars", (lab("cpu"), lab("mem")))
    allopts = lambda pid: page.eval_on_selector_all(f"#{pid}-panel .panel-view option", "e => e.map(x => x.textContent)")
    r.check("widgets: the whole menu follows the count, one series singular and two plural",
            allopts("cpu") == ["Strip", "Bar", "Gauge", "Ring", "Steps", "Flip board", "Dot matrix", "Number"] and allopts("mem") == ["Strips", "Bars", "Gauges", "Rings", "Steps", "Flip boards", "Dot matrix", "Numbers"], (allopts("cpu"), allopts("mem")))

    # The ring: segments light up round to the value, the LED readout and the label say it.
    ring = page.evaluate("""() => { const host = document.createElement('div'); document.body.appendChild(host);
      const v = createView('ring', host, {layout: 'separate'});
      const at = (value, text) => { v.update([{key: 'a', label: 'CPU', value, max: 100, color: '#4af', text}]);
        return [host.querySelectorAll('.ring-seg.on').length, host.querySelectorAll('.led > g').length, host.querySelector('.ring-label').textContent]; };
      const out = [at(0, '0%'), at(50, '50%'), at(100, '100%'), at(50, '2.8G')];
      v.destroy(); host.remove(); return out; }""")
    r.check("widgets: the ring lights none, half and all of its segments and shows a LED cell per character",
            ring[0][0] == 0 and ring[1][0] == 15 and ring[2][0] == 30 and [x[1] for x in ring] == [2, 3, 4, 4] and ring[1][2] == "CPU", ring)
    two = page.evaluate("""() => { const host = document.createElement('div'); document.body.appendChild(host);
      const v = createView('ring', host, {layout: 'separate'});
      v.update([{key: 'a', label: 'a', value: 10, max: 100, color: '#fff', text: '10%'}, {key: 'b', label: 'b', value: 90, max: 100, color: '#fff', text: '90%'}]);
      const out = [...host.querySelectorAll('.ring-svg')].map((s) => s.querySelectorAll('.ring-seg.on').length); v.destroy(); host.remove(); return out; }""")
    r.check("widgets: several series get a ring each", two == [3, 27], two)

    # Flip cells: a clock cell flips once, a board cell clacks through the alphabet, and fast changes skip ahead.
    flip = page.evaluate("""async () => {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const out = {};
      out.path = [boardPath('A', 'D'), boardPath('A', 'A'), boardPath(' ', '9').length, boardPath(' ', '9').slice(-1)[0]];
      const host = document.createElement('div'); document.body.appendChild(host);
      const clock = createView('flip', host, {layout: 'separate'});
      const at = (text) => clock.update([{key: 'a', label: 'CPU', value: 50, max: 100, color: '#4af', text}]);
      at('89%');
      out.clockFirst = [...host.querySelectorAll('.fc-top span')].map((e) => e.textContent).join('');
      at('90%'); at('91%'); at('92%');
      await wait(FLIP_MS * 3 + 150);
      out.clockLast = [...host.querySelectorAll('.fc-bottom span')].map((e) => e.textContent).join('');
      clock.destroy(); host.remove();
      const host2 = document.createElement('div'); document.body.appendChild(host2);
      const board = createView('flip', host2, {layout: 'separate', style: 'letters'});
      board.update([{key: 'a', label: 'rx', value: 50, max: 100, color: '#4af', text: '1.5K/s'}]);
      out.boardStart = host2.querySelectorAll('.flip-reading .flip-cell').length;
      await wait(1300);
      out.boardReading = [...host2.querySelectorAll('.flip-reading .fc-bottom span')].map((e) => e.textContent).join('');
      out.boardName = [...host2.querySelectorAll('.flip-name .fc-bottom span')].map((e) => e.textContent).join('');
      board.destroy(); host2.remove();
      out.fixed = ['5%', '89.1%', '100%', '99.9%', '0B/s', '2.8G', 'n/a'].map(fixedReading);
      const host3 = document.createElement('div'); document.body.appendChild(host3);
      const wide = createView('flip', host3, {layout: 'separate'});
      const counts = [];
      for (const text of ['0%', '5%', '89.1%', '100%', '99.9%']) { wide.update([{key: 'a', label: 'CPU', value: 1, max: 100, color: '#fff', text}]); counts.push(host3.querySelectorAll('.flip-reading .flip-cell').length); }
      out.counts = counts;
      const faces = [];
      for (const v of [10, 70, 95]) {
        const g = document.createElement('div'); document.body.appendChild(g);
        const view = createView('flip', g, {layout: 'separate', graded: true, style: v === 70 ? 'letters' : 'numbers'});
        view.update([{key: 'a', label: 'CPU', value: v, max: 100, color: '#fff', text: v + '%'}]);
        const bg = getComputedStyle(g.querySelector('.fc-half')).backgroundColor, ink = getComputedStyle(g.querySelector('.flip-row')).color;
        faces.push([bg, ink]); view.destroy(); g.remove();
      }
      const plain = document.createElement('div'); document.body.appendChild(plain);
      const pv = createView('flip', plain, {layout: 'separate'});
      pv.update([{key: 'a', label: 'CPU', value: 95, max: 100, color: '#fff', text: '95%'}]);
      out.faces = faces; out.plainFace = plain.querySelector('.flip-row').style.getPropertyValue('--flip-face');
      pv.destroy(); plain.remove();
      wide.destroy(); host3.remove();
      return out; }""")
    r.check("widgets: the board's path runs through the alphabet to the character and is never long",
            flip["path"] == [["B", "C", "D"], [], 10, "9"], flip["path"])
    r.check("widgets: a clock shows its first reading at once and, changed faster than it flips, lands on the last",
            flip["clockFirst"] == "089.0%" and flip["clockLast"] == "092.0%", (flip["clockFirst"], flip["clockLast"]))
    r.check("widgets: the fixed width pads to three digits and a decimal, and leaves non-numbers alone",
            flip["fixed"] == ["005.0%", "089.1%", "100.0%", "099.9%", "000.0B/s", "002.8G", "n/a"], flip["fixed"])
    r.check("widgets: a flip display always has the same number of cells from 0 to 100",
            flip["counts"] == [6] * 5, flip["counts"])
    inks = [(0, 174, 239), (255, 242, 0), (236, 0, 140)]
    channels = lambda c: tuple(int(x) for x in re.findall(r"\d+", c)[:3])
    dist = lambda a, b: sum((x - y) ** 2 for x, y in zip(a, b))
    nearest = [min(range(3), key=lambda i: dist(channels(f[0]), inks[i])) for f in flip["faces"]]
    r.check("widgets: with Colours on the flaps are the printer's cyan, yellow and magenta by level (taken a little towards the theme), with dark type, and plain without",
            nearest == [0, 1, 2] and len({f[0] for f in flip["faces"]}) == 3
            and all(sum(channels(f[1])) < 300 for f in flip["faces"]) and flip["plainFace"] == "", (flip["faces"], flip["plainFace"]))
    r.check("widgets: a board arrives at its reading and its name by flipping",
            flip["boardStart"] == 8 and flip["boardReading"] == "001.5K/S" and flip["boardName"] == "RX", flip)

    # Stepped bars: ten steps lit up to the value, the reading and the name under them.
    steps = page.evaluate("""() => { const host = document.createElement('div'); document.body.appendChild(host);
      const v = createView('steps', host, {layout: 'separate'});
      const at = (value, text) => { v.update([{key: 'a', label: 'rx', value, max: 100, color: '#4af', text}]);
        return [host.querySelectorAll('.steps-bar.on').length, host.querySelector('.steps-label').textContent]; };
      const out = [at(0, '0B/s'), at(50, '1.5K/s'), at(100, '9M/s')]; v.destroy(); host.remove(); return out; }""")
    r.check("widgets: the steps light none, half and all of their bars and say the name, with no reading of their own",
            [x[0] for x in steps] == [0, 5, 10] and steps[1][1] == "rx", steps)

    # The reading table: three or more sit side by side, one or two stay a table.
    tab = lambda n: page.evaluate("""(n) => { const panel = document.createElement('div'); panel.className = 'panel'; panel.dataset.size = '12'; panel.style.width = '900px'; document.body.appendChild(panel);
      const host = document.createElement('div'); panel.appendChild(host);
      const t = detailTable('bottom'); host.appendChild(t.el);
      t.set(Array.from({length: n}, (_, i) => ({label: 'core' + i, value: i + '%', color: '#fff'})));
      const tops = new Set([...host.querySelectorAll('.detail-label')].map((x) => Math.round(x.getBoundingClientRect().top)));
      panel.remove(); return tops.size; }""", n)
    r.check("widgets: four readings share one line, core0 | core1 | core2 | core3", tab(4) == 1, tab(4))
    r.check("widgets: two readings stay a stacked table", tab(2) == 2, tab(2))

    # Layout. Put four panels at quarter width and check they share a row.
    for pid in ("cpu-composite", "mem", "net", "load"):
        _choose(page, pid, ".panel-view", "number")
        _choose(page, pid, ".panel-size", 3)
    boxes = [_box(page, p) for p in ("cpu-composite", "mem", "net", "load")]
    r.check("widgets: four quarter panels sit side by side on one row",
            len({round(b["y"]) for b in boxes}) == 1 and len({round(b["x"]) for b in boxes}) == 4, boxes)
    outside = page.evaluate("""() => [...document.querySelectorAll("#meters .panel")].flatMap(p => {
        const pr = p.getBoundingClientRect();
        return [...p.querySelectorAll(".panel-head > *, .panel-controls > *")]
          .filter(c => c.offsetParent !== null)
          .filter(c => { const r = c.getBoundingClientRect(); return r.right > pr.right + 1 || r.left < pr.left - 1; })
          .map(c => p.id + ":" + c.className);
    })""")
    r.check("widgets: header controls stay inside narrow panels", outside == [], outside)
    full = _box(page, "disk")
    r.check("widgets: a quarter is a quarter of a full panel",
            abs(boxes[0]["width"] * 4 - full["width"]) < 24, (boxes[0]["width"], full["width"]))
    r.check("widgets: size saved", _saved("mem")["size"] == 3)
    h.shot(page, "widgets_03_quarters")

    _choose(page, "cpu-cores", ".panel-size", 6)
    _choose(page, "disk", ".panel-size", 6)
    a, b = _box(page, "cpu-cores"), _box(page, "disk")
    r.check("widgets: two half panels share a row",
            abs(a["y"] - b["y"]) < 2 and a["x"] != b["x"], (a, b))

    # Scaled, not stretched: a gauge keeps its proportions at any width.
    _choose(page, "mem", ".panel-view", "gauge")
    _choose(page, "mem", ".panel-size", 12)
    wide = page.locator("#mem-panel svg.gauge-svg").first.bounding_box()
    _choose(page, "mem", ".panel-size", 3)
    narrow = page.locator("#mem-panel svg.gauge-svg").first.bounding_box()
    ratio = lambda b: b["width"] / b["height"]
    r.check("widgets: gauge keeps its proportions when the panel narrows",
            abs(ratio(wide) - ratio(narrow)) < 0.05 and narrow["width"] < wide["width"], (wide, narrow))
    r.check("widgets: a full-width gauge is capped, not stretched edge to edge",
            wide["width"] <= 321, wide)

    # Phone width: every size stacks to full width.
    page.set_viewport_size({"width": 480, "height": 900})
    time.sleep(1.5)
    widths = {round(_box(page, p)["width"]) for p in IDS}
    r.check("widgets: on a narrow screen all panels stack full width", len(widths) == 1, widths)
    page.set_viewport_size({"width": 1200, "height": 1000})
    time.sleep(1)

    # Everything survives a reload, and leaving Modify hides the controls.
    before = {p: _saved(p) for p in IDS}
    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(2)
    r.check("widgets: views, merge and sizes survive a reload",
            all(page.locator(f"#{IDS[p]}").get_attribute("data-view") == before[p]["view"]
                and page.locator(f"#{IDS[p]}").get_attribute("data-size") == str(before[p]["size"]) for p in IDS))
    r.check("widgets: merge survives a reload", _saved("net")["merge"] is True)
    r.check("widgets: controls gone again after reload", page.locator(".panel-view").count() == 0)

    # A strip chart that went away and came back is still alive.
    h.enter_modify(page)
    _choose(page, "cpu-composite", ".panel-view", "gauge")
    _choose(page, "cpu-composite", ".panel-view", "strip")
    time.sleep(2.5)
    r.check("widgets: strip chart is live again after a round trip through other views",
            h.chart_is_live(h.canvas_state(page, "cpu-canvas")))

    h.finish_page(r, page, "widgets")
    page.context.close()

    # Strips: separate is the layout of the bars, a name, a chart and a reading to a row; merged stacks
    # the charts, the names above and the readings below. One chart, one series.
    for merge in (False, True):
        h.reset_user_config()
        _write_config({"launcher": [], "panels": [{"id": "mem", "view": "strip", "merge": merge, "size": 12}, {"id": "net", "view": "strip", "merge": merge, "size": 12}]})
        page = h.new_page(browser)
        h.open_dashboard(page, settle=3)
        tag = "merged" if merge else "separate"
        for pid in ("mem", "net"):
            charts = page.locator(f"#{pid}-panel canvas").count()
            r.check(f"widgets: {tag} {pid} strip has a chart for each of its two series, not both on one", charts == 2, charts)
        ink = page.eval_on_selector_all("#mem-panel canvas", "e => e.map(c => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return [c.width > 20 && c.height > 10, n]; })")
        r.check(f"widgets: {tag} strip charts have a real size and have drawn a line", all(x[0] and x[1] > 5 for x in ink), ink)
        if merge:
            r.check("widgets: merged strips are one stack of two chart tracks, not rows", page.locator("#mem-panel .stack-tracks .chart-track").count() == 2 and page.locator("#mem-panel .disk-row").count() == 0)
            ys = page.eval_on_selector_all("#mem-panel .detail-top, #mem-panel .stack-tracks, #mem-panel .detail-bottom", "e => e.map(x => x.getBoundingClientRect().top)")
            r.check("widgets: names above, charts, readings below", ys == sorted(ys) and len(set(ys)) == 3, ys)
            tops = page.eval_on_selector_all("#mem-panel .chart-track", "e => e.map(x => Math.round(x.getBoundingClientRect().top))")
            r.check("widgets: the two charts sit one above the other", tops[0] < tops[1], tops)
        else:
            r.check("widgets: separate strips are rows, a name, a chart and a reading each",
                    page.locator("#mem-panel .disk-row").count() == 2 and page.locator("#mem-panel .disk-row .chart-track canvas").count() == 2
                    and page.eval_on_selector_all("#mem-panel .disk-row .disk-label", "e => e.map(x => x.textContent)") == ["physical", "swap"])
            lefts = page.eval_on_selector_all("#mem-panel .chart-track", "e => e.map(x => Math.round(x.getBoundingClientRect().left))")
            r.check("widgets: and the charts line up", len(set(lefts)) == 1, lefts)
            h.shot(page, "widgets_06_strip_rows")
        page.context.close()

    # Three gauge panels side by side: the dials are the same size and start at the same height, even
    # though one has two lines of totals above it and the others have one. And a lone gauge is not squeezed
    # into a share of the panel meant for several.
    h.reset_user_config()
    _write_config({"launcher": [],                    "panels": [{"id": "cpu-composite", "view": "gauge", "size": 4}, {"id": "mem", "view": "gauge", "size": 4, "amount": "both"},
                              {"id": "disk", "view": "gauge", "size": 4, "amount": "both"}]})
    page = h.new_page(browser, width=1000)
    h.open_dashboard(page)
    dials = page.eval_on_selector_all("#meters .panel .gauge-svg", "e => e.map(x => { const r = x.getBoundingClientRect(); return [Math.round(r.top + r.height / 2), Math.round(r.width)]; })")
    r.check("widgets: gauges in one row are centred on one line", max(d[0] for d in dials) - min(d[0] for d in dials) <= 2, dials)
    panel_w = page.eval_on_selector("#disk-panel", "e => e.getBoundingClientRect().width")
    disk_w = page.eval_on_selector("#disk-panel .gauge-svg", "e => e.getBoundingClientRect().width")
    cpu_w = page.eval_on_selector("#cpu-panel .gauge-svg", "e => e.getBoundingClientRect().width")
    r.check("widgets: a lone gauge (the disk) is as wide as the composite one, not squeezed into a share of the panel", abs(disk_w - cpu_w) < 2 and disk_w > panel_w * 0.8, (disk_w, cpu_w, panel_w, dials))
    tall = page.eval_on_selector("#mem-panel .detail-bottom .detail-val", "e => e.getBoundingClientRect().height")
    r.check("widgets: a long reading in a narrow cell wraps on its words, not a letter to a line", tall < 50, tall)
    h.shot(page, "widgets_05_gauges_aligned")
    page.context.close()

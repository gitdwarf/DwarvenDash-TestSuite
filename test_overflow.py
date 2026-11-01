"""
No text runs out of its panel. Readings ("18.7G used / 4.7G free") have three rules, and each was a bug on its own:
the cell is sized from the unit as it is shown (with its " / "), a line may break between two units (a <wbr>, since
the units themselves do not break), and a merged display counts as a narrow cell like a split one does.
Measured over every view, merged and separate, at the half, third and quarter sizes of a narrow window.
"""

import dd_harness as h
import test_gpu
import test_widgets as w

OVERFLOW = """() => { const out = [];
  for (const p of document.querySelectorAll("#meters .panel")) { const pr = p.getBoundingClientRect();
    for (const e of p.querySelectorAll(".detail-val, .detail-label, .detail-name, .detail-reading, .reading-unit, .detail-head, .num-big, .num-label")) {
      const r = e.getBoundingClientRect(); if (!r.width) continue;
      if (r.right > pr.right + 1 || r.left < pr.left - 1) out.push([p.id, e.className, Math.round(r.left - pr.left), Math.round(r.right - pr.right)]); } }
  return out; }"""

VIEWS = ("bars", "gauge", "number", "strip", "ring", "steps")


def run(browser, r):
    # A machine with a graphics card, so the GPU panel (load, memory, temperature) is on the page and in the scan.
    test_gpu._say(h.FAKE_SMI, test_gpu.ONE)
    bad = {}
    page_has_gpu = True
    for view in VIEWS:
        for merge in (False, True):
            for size in (6, 4, 3):
                cfg = [{"id": i, "view": view, "merge": merge and i == "mem", "pct": "used", "amount": "both", "total": True, "size": size}
                       for i in ("mem", "gpu", "disk", "net")]
                h.reset_user_config()
                w._write_config({"launcher": [], "panels": cfg})
                page = h.new_page(browser, 720, 900)
                h.open_dashboard(page, 1.5)
                found = page.evaluate(OVERFLOW)
                page_has_gpu = page_has_gpu and page.locator("#gpu-panel .framed-view, #gpu-panel .bars-view, #gpu-panel .number-view, #gpu-panel .split-view").count() > 0
                if found:
                    bad[f"{view} {'merged' if merge else 'separate'} size {size}"] = found[:2]
                page.context.close()
    r.check("overflow: the GPU panel is on the page, so the scan covers it", page_has_gpu, None)
    r.check("overflow: no reading or name runs out of its panel, in any view, merged or separate, at half, third and quarter size",
            not bad, bad)

    # The pieces, directly.
    page = h.new_page(browser)
    h.open_dashboard(page)
    got = page.evaluate("() => [widestUnit(['18.7G used / 4.7G free']), widestUnit(['a | bb / c']), widestUnit(['', null])]")
    r.check("overflow: a unit is measured as it is shown, with its ' / ' unless it ends the line", got == [13, 5, 0], got)
    got = page.evaluate("""() => { const b = document.createElement("div"); setReading(b, "50% used | 3.8G used / 3.8G free");
        return [b.querySelectorAll("wbr").length, b.querySelectorAll(".reading-unit").length]; }""")
    r.check("overflow: a line break is allowed after each ' / ' and nowhere else", got == [1, 3], got)
    page.close()
    test_gpu._say(h.FAKE_SMI, "")  # no GPUs, not a failure: a failing tool is waited on for 30s and would hide the next fake

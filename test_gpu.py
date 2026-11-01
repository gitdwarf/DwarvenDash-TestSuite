"""
NVIDIA GPUs through nvidia-smi.

Two halves. The reader is run against scripts standing in for nvidia-smi
(good output, fields a card cannot report, nonsense, a failing tool, a hung
tool, no tool at all), because this machine has no GPU and a VPS must stay
quiet. Then the real page is checked against a server running the same fake
tool: what each panel shows, one GPU against several, and that the panels are
offered only while the machine has a GPU.
"""

import os
import shutil
import stat
import sys
import tempfile
import time

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import gpu  # noqa: E402

ONE = "0, NVIDIA GeForce RTX 3080, 37, 2048, 10240, 61\n"
TWO = ONE + "1, NVIDIA GeForce GTX 1060, 90, 5120, 6144, 80\n"
MIB = 1024 * 1024


def _tool(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)


def _say(path, text):
    _tool(path, f"cat <<'EOF'\n{text}EOF\n")


def _bars(page, bars_id):
    return page.eval_on_selector_all(
        f"#{bars_id} .disk-row", "rows => rows.map(r => [r.querySelector('.disk-label').textContent, r.querySelector('.disk-percent').textContent])")


def _offered(page):
    return page.eval_on_selector_all("#available-panels .available-app-row span", "e => e.map(x => x.textContent)")


def _readers(r):
    one = gpu.parse(ONE)
    r.check("gpu: a row reads as load, memory in bytes and temperature",
            one == [{"index": 0, "name": "NVIDIA GeForce RTX 3080", "util_percent": 37.0, "mem_used_bytes": 2048 * MIB,
                     "mem_total_bytes": 10240 * MIB, "temp_c": 61.0}], one)
    r.check("gpu: two cards are two rows", [g["index"] for g in gpu.parse(TWO)] == [0, 1], gpu.parse(TWO))
    na = gpu.parse("0, Quadro, [N/A], [N/A], [N/A], 44\n")
    r.check("gpu: a field the card cannot report is None and the rest is kept",
            na and na[0]["util_percent"] is None and na[0]["mem_total_bytes"] is None and na[0]["temp_c"] == 44.0, na)
    r.check("gpu: a row that reports nothing is dropped", gpu.parse("0, Nothing, [N/A], [N/A], [N/A], [N/A]\n") == [])
    for bad in ("", "No devices were found\n", "a, b\n", "x, Card, 5, 5, 5, 5\n", "0, Card, 5, 5, 5, 5, 5\n"):
        r.check(f"gpu: {bad[:24]!r} reads as no GPU, never an error", gpu.parse(bad) == [], gpu.parse(bad))
    lie = gpu.parse("0, Liar, 250, 9000, 100, 900\n")
    r.check("gpu: a load over 100, memory over its total and a temperature of 900 are not believed", lie == [], lie)
    named = gpu.parse("0, Card\x1b[31m" + "x" * 200 + ", 5, 1, 2, 30\n")
    r.check("gpu: a name loses control characters and is kept short", named and "\x1b" not in named[0]["name"] and len(named[0]["name"]) <= 60, named)

    work = tempfile.mkdtemp(prefix="dd-gpu-")
    tool = os.path.join(work, "nvidia-smi")
    count = os.path.join(work, "runs")
    saved = os.environ.get("DWARVENDASH_NVIDIA_SMI")
    os.environ["DWARVENDASH_NVIDIA_SMI"] = tool
    runs = lambda: len(open(count).read().split()) if os.path.exists(count) else 0
    try:
        gpu.forget()
        r.check("gpu: no tool at all is no GPUs", gpu.nvidia() == [])
        _tool(tool, f"echo x >> {count}\ncat <<'EOF'\n{ONE}EOF\n")
        gpu.forget()
        r.check("gpu: the tool's answer is read", len(gpu.nvidia()) == 1)
        gpu.nvidia(); gpu.nvidia()
        r.check("gpu: pages opened together share one run", runs() == 1, runs())
        gpu.forget(); gpu.nvidia()
        r.check("gpu: a stale reading is read again", runs() == 2, runs())

        _tool(tool, f"echo x >> {count}\nexit 9\n")
        gpu.forget(); before = runs()
        r.check("gpu: a failing tool is no GPUs", gpu.nvidia() == [])
        gpu.nvidia(); gpu.nvidia()
        r.check("gpu: a failing tool is not run again every sample", runs() == before + 1, (before, runs()))

        _tool(tool, "sleep 5\n")
        gpu.forget()
        gpu.TIMEOUT_SECONDS = 0.4
        started = time.monotonic()
        hung = gpu.nvidia()
        r.check("gpu: a hung tool is given up on quickly", hung == [] and time.monotonic() - started < 3, time.monotonic() - started)
        gpu.TIMEOUT_SECONDS = 3.0

        os.remove(tool)
        gpu.forget()
        r.check("gpu: a tool that goes away is no GPUs", gpu.nvidia() == [])
    finally:
        gpu.TIMEOUT_SECONDS = 3.0
        gpu.forget()
        if saved is None:
            os.environ.pop("DWARVENDASH_NVIDIA_SMI", None)
        else:
            os.environ["DWARVENDASH_NVIDIA_SMI"] = saved
        for name in os.listdir(work):
            os.remove(os.path.join(work, name))
        os.rmdir(work)


def _amd_tree(root, cards):
    """cards: {name: {file: content}}, written under sys/class/drm/<name>/device."""
    for name, files in cards.items():
        device = os.path.join(root, "sys", "class", "drm", name, "device")
        os.makedirs(device, exist_ok=True)
        for fname, content in files.items():
            os.makedirs(os.path.dirname(os.path.join(device, fname)), exist_ok=True)
            with open(os.path.join(device, fname), "w") as f:
                f.write(content + "\n")


AMD = {"vendor": "0x1002", "hwmon/hwmon3/temp1_input": "55000", "hwmon/hwmon3/temp1_label": "edge", "gpu_busy_percent": "42", "mem_info_vram_used": str(4096 * MIB), "mem_info_vram_total": str(8192 * MIB)}


def _amd(r):
    root = tempfile.mkdtemp(prefix="dd-amd-")
    try:
        r.check("gpu: no drm tree is no AMD cards", gpu.amd(root) == [])
        _amd_tree(root, {"card0": AMD, "card0-DP-1": AMD, "card1": dict(AMD, vendor="0x8086"),
                         "card2": {"vendor": "0x1002"}, "card3": dict(AMD, gpu_busy_percent="900", mem_info_vram_used="9" * 20, **{"hwmon/hwmon3/temp1_input": "300000"})})
        found = gpu.amd(root)
        r.check("gpu: an AMD card reads its load and memory from sysfs",
                len(found) == 1 and found[0]["util_percent"] == 42.0 and found[0]["mem_used_bytes"] == 4096 * MIB
                and found[0]["mem_total_bytes"] == 8192 * MIB and found[0]["temp_c"] == 55.0, found)
        r.check("gpu: connectors, other vendors, cards with no counters and impossible numbers are not AMD cards",
                [g["name"] for g in found] == ["AMD GPU"], found)
        _amd_tree(root, {"card3": {"gpu_busy_percent": "55", "mem_info_vram_used": str(8 * MIB), "mem_info_vram_total": str(2 * MIB)}})
        lied = [g for g in gpu.amd(root) if g["util_percent"] == 55.0]
        r.check("gpu: memory used above its total is not believed but the load beside it is",
                len(lied) == 1 and lied[0]["mem_total_bytes"] is None and lied[0]["mem_used_bytes"] is None, lied)
        _amd_tree(root, {"card4": dict(AMD, **{"hwmon/hwmon3/temp1_input": "300000"}), "card5": {"vendor": "0x1002", "hwmon/hwmon1/temp1_input": "47000"}})
        extra = {g["name"]: g for g in gpu.amd(root)}
        r.check("gpu: an impossible AMD temperature is dropped, and a card with only a temperature is still a card",
                any(g["temp_c"] is None and g["util_percent"] == 42.0 for g in gpu.amd(root)) and any(g["temp_c"] == 47.0 and g["util_percent"] is None for g in gpu.amd(root)), gpu.amd(root))
        shutil.rmtree(os.path.join(root, "sys", "class", "drm", "card4"))
        shutil.rmtree(os.path.join(root, "sys", "class", "drm", "card5"))
        os.environ["DWARVENDASH_NVIDIA_SMI"] = "/nonexistent/nvidia-smi"
        gpu.forget()
        both = gpu.readings(root)
        r.check("gpu: the cards are numbered from zero, and a reading is a copy so numbering never leaks into the cache",
                [g["index"] for g in both] == list(range(len(both))) and gpu.nvidia() == [], both)
    finally:
        os.environ.pop("DWARVENDASH_NVIDIA_SMI", None)
        shutil.rmtree(root, ignore_errors=True)


def run(browser, r):
    _readers(r)
    _amd(r)

    def write_panels(panels):
        import json
        path = h.user_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"launcher": [], "panels": panels}, f)

    h.reset_user_config()
    _say(h.FAKE_SMI, ONE)
    write_panels([{"id": "gpu", "view": "bars"}, {"id": "temps", "view": "bars"}])
    page = h.new_page(browser)
    h.open_dashboard(page)
    time.sleep(3)
    h.shot(page, "gpu_01_one")
    r.check("gpu: one card is one panel with its load, memory and temperature",
            _bars(page, "gpu-bars") == [["load", "37%"], ["mem", "20%"], ["temp", "61°C"]], _bars(page, "gpu-bars"))
    temps = dict(_bars(page, "temps-bars"))
    r.check("gpu: its temperature is in the GPU panel and not in TEMPS, which keeps the kernel's sensors",
            "NVIDIA GeForce RTX 3080" not in temps and "CPU Package id 0" in temps, temps)

    _say(h.FAKE_SMI, TWO)
    time.sleep(3)
    rows = _bars(page, "gpu-bars")
    r.check("gpu: two cards are told apart by number, each with its parts",
            [x[0] for x in rows] == ["gpu0 load", "gpu0 mem", "gpu0 temp", "gpu1 load", "gpu1 mem", "gpu1 temp"], rows)
    r.check("gpu: and each memory is its own", dict(rows).get("gpu0 mem") == "20%" and dict(rows).get("gpu1 mem") == "83.3%", rows)

    h.enter_modify(page)
    r.check("gpu: Load, Memory and Temp switches are on the panel, all on",
            page.eval_on_selector_all("#gpu-panel .panel-part", "e => e.map(x => [x.textContent, x.classList.contains('on')])") == [["Load", True], ["Memory", True], ["Temp", True]])
    page.click("#gpu-panel .panel-part-temp")
    page.click("#gpu-panel .panel-part-mem")
    time.sleep(2.5)
    rows = _bars(page, "gpu-bars")
    r.check("gpu: switching Memory and Temp off leaves the load of each card", [x[0] for x in rows] == ["gpu0 load", "gpu1 load"], rows)
    r.check("gpu: and the last one on cannot be switched off", page.locator("#gpu-panel .panel-part-load").is_disabled())
    r.check("gpu: the choice is saved", next(p for p in h.read_user_config()["panels"] if p["id"] == "gpu")["parts"] == ["load"])
    page.click("#gpu-panel .panel-part-mem")
    page.evaluate("changePanel('gpu', {amount: 'both', pct: 'off', total: true})")
    time.sleep(2.5)
    text = page.inner_text("#gpu-panel")
    r.check("gpu: memory can show sizes and totals like the other capacity panels",
            "2.0G" in text and "10.0G" in text and "5.0G" in text and "6.0G" in text, text[:200])
    page.click("#launcher-modify-toggle")

    # An AMD card in the server's fake tree joins the NVIDIA ones.
    _amd_tree(h.HOST_DIR, {"card0": AMD})
    time.sleep(3)
    r.check("gpu: an AMD card is another card after the NVIDIA ones", "gpu2 load" in [x[0] for x in _bars(page, "gpu-bars")], _bars(page, "gpu-bars"))
    r.check("gpu: and its temperature reaches the page with the card", page.evaluate("latestSnap.gpu.map(g => g.temp_c)")[2] == 55, page.evaluate("latestSnap.gpu"))
    shutil.rmtree(os.path.join(h.HOST_DIR, "sys", "class", "drm"), ignore_errors=True)

    h.enter_modify(page)
    page.locator(f"#{h.PANEL_EL['gpu']} .panel-remove").click()
    time.sleep(0.5)
    r.check("gpu: with a GPU, GPU is offered", "GPU" in _offered(page), _offered(page))
    r.check("gpu: and there is no separate GPU-MEM", "GPU-MEM" not in _offered(page), _offered(page))

    os.remove(h.FAKE_SMI)
    time.sleep(3)
    page.click("#launcher-modify-toggle")
    page.click("#launcher-modify-toggle")
    time.sleep(0.5)
    offered = _offered(page)
    r.check("gpu: without one it is not offered", "GPU" not in offered, offered)
    r.check("gpu: no browser errors", page.dd_errors == [], page.dd_errors)
    h.reset_user_config()
    page.context.close()

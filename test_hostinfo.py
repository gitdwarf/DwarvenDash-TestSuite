"""
Host information: memory with swap, CPU frequency, temperatures, host facts.

Two halves. The readers are checked directly against a fake /proc and /sys
(fakehost.py has the known numbers), including the machines that cannot
report things, because a VPS has no sensors and that must be quiet, not
an error. Then the real page is checked against a server reading the same
tree: what each panel shows, and that a panel the machine cannot feed is
not offered.
"""

import os
import shutil
import sys
import time

import dd_harness as h
import fakehost

sys.path.insert(0, h.APP_DIR)
import hostinfo  # noqa: E402
import stats  # noqa: E402


def _bars(page, bars_id):
    """(label, text) per row of a bars view."""
    return page.eval_on_selector_all(
        f"#{bars_id} .disk-row", "rows => rows.map(r => [r.querySelector('.disk-label').textContent, r.querySelector('.disk-percent').textContent])")


def _facts(page):
    return dict(page.eval_on_selector_all(
        "#host-list .fact-row", "rows => rows.map(r => [r.querySelector('.fact-label').textContent, r.querySelector('.fact-text').textContent])"))


def _write_panels(panels):
    import json
    path = h.user_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"launcher": [], "panels": panels}, f)


def _offered(page):
    return page.eval_on_selector_all("#available-panels .available-app-row span", "e => e.map(x => x.textContent)")


def _readers(r):
    root = fakehost.build()
    try:
        mem = stats.mem_stats(root)
        r.check("hostinfo: ram percent from the tree", mem["percent"] == 50.0, mem)
        r.check("hostinfo: swap percent from the tree", mem["swap_percent"] == 25.0, mem)

        r.check("hostinfo: uptime in seconds", hostinfo.uptime_seconds(root) == 93784, hostinfo.uptime_seconds(root))
        r.check("hostinfo: tasks", hostinfo.tasks(root) == {"running": 2, "total": 345}, hostinfo.tasks(root))
        r.check("hostinfo: os name", hostinfo.os_name(root) == "FakeOS 1.0 (Test)", hostinfo.os_name(root))
        r.check("hostinfo: cpu model and threads",
                hostinfo.cpu_model(root) == {"model": "Fake CPU 9000", "threads": 2}, hostinfo.cpu_model(root))
        r.check("hostinfo: battery found, mains adapter ignored",
                hostinfo.battery(root) == {"percent": 87, "status": "Discharging"}, hostinfo.battery(root))
        r.check("hostinfo: fan", hostinfo.fans(root) == [{"label": "ThinkPad fan", "rpm": 1200}], hostinfo.fans(root))
        for fname, content in (("fan1_max", "3000"), ("fan1_fault", "1")):
            fakehost._write(root, f"sys/class/hwmon/hwmon1/{fname}", content + "\n")
        r.check("hostinfo: a fan's own top speed and a reported fault come with it",
                hostinfo.fans(root) == [{"label": "ThinkPad fan", "rpm": 1200, "max_rpm": 3000, "fault": True}], hostinfo.fans(root))
        for fname in ("fan1_max", "fan1_fault"):
            os.remove(os.path.join(root, "sys/class/hwmon/hwmon1", fname))
        r.check("hostinfo: cpu frequency per core",
                hostinfo.cpu_freq(root) == {"cpu0": {"cur_khz": 1200000, "max_khz": 3600000},
                                            "cpu1": {"cur_khz": 2400000, "max_khz": 3600000}}, hostinfo.cpu_freq(root))
        temps = hostinfo.temperatures(root)
        r.check("hostinfo: temperatures with their own ceiling, unplugged reading ignored",
                temps == [{"label": "CPU Package id 0", "celsius": 54.0, "max_c": 100.0},
                          {"label": "ThinkPad", "celsius": 40.5, "max_c": 100.0}], temps)
        fakehost._write(root, "sys/class/hwmon/hwmon9/name", "amdgpu\n")
        fakehost._write(root, "sys/class/hwmon/hwmon9/temp1_input", "61000\n")
        r.check("hostinfo: a graphics card's own chip is left to the GPU panel, not listed twice",
                [t["label"] for t in hostinfo.temperatures(root)] == ["CPU Package id 0", "ThinkPad"], hostinfo.temperatures(root))
        shutil.rmtree(os.path.join(root, "sys/class/hwmon/hwmon9"))
        fakehost._write(root, "sys/class/hwmon/hwmon8/name", "acpitz\n")
        fakehost._write(root, "sys/class/hwmon/hwmon8/temp1_input", "27800\n")
        r.check("hostinfo: the firmware's ACPI zone is kept, as the Motherboard, and listed before other chips",
                [t["label"] for t in hostinfo.temperatures(root)] == ["CPU Package id 0", "Motherboard", "ThinkPad"], hostinfo.temperatures(root))
        shutil.rmtree(os.path.join(root, "sys/class/hwmon/hwmon8"))
        fakehost._write(root, "sys/class/hwmon/hwmon7/name", "k10temp\n")
        for n, (label, milli) in enumerate((("Tctl", 60000), ("Tccd1", 55000), ("Tccd2", 56000)), 1):
            fakehost._write(root, f"sys/class/hwmon/hwmon7/temp{n}_input", f"{milli}\n")
            fakehost._write(root, f"sys/class/hwmon/hwmon7/temp{n}_label", label + "\n")
        r.check("hostinfo: a chip's sensors list the cores first and the sensor that sums them up last",
                [t["label"] for t in hostinfo.temperatures(root) if t["label"].startswith("CPU T")] == ["CPU Tccd1", "CPU Tccd2", "CPU Tctl"], hostinfo.temperatures(root))
        shutil.rmtree(os.path.join(root, "sys/class/hwmon/hwmon7"))
        # A desktop: board chips are numbered before the CPU's by the kernel, and a CPU can have more than nine cores.
        hwmon, aside = (os.path.join(root, "sys/class", d) for d in ("hwmon", "hwmon-aside"))
        os.rename(hwmon, aside)
        fakehost._write(root, "sys/class/hwmon/hwmon9/name", "acpitz\n")
        fakehost._write(root, "sys/class/hwmon/hwmon9/temp1_input", "27800\n")
        fakehost._write(root, "sys/class/hwmon/hwmon1/name", "coretemp\n")
        fakehost._write(root, "sys/class/hwmon/hwmon1/temp1_input", "40000\n")
        fakehost._write(root, "sys/class/hwmon/hwmon1/temp1_label", "Package id 0\n")
        for n in range(2, 14):
            fakehost._write(root, f"sys/class/hwmon/hwmon1/temp{n}_input", f"{30000 + n * 1000}\n")
            fakehost._write(root, f"sys/class/hwmon/hwmon1/temp{n}_label", f"Core {n - 2}\n")
        fakehost._write(root, "sys/class/hwmon/hwmon10/name", "it8628\n")
        for n in (1, 2):
            fakehost._write(root, f"sys/class/hwmon/hwmon10/temp{n}_input", f"{35000 + n}\n")
        fakehost._write(root, "sys/class/hwmon/hwmon3/name", "nvme\n")
        fakehost._write(root, "sys/class/hwmon/hwmon3/temp1_input", "45000\n")
        fakehost._write(root, "sys/class/hwmon/hwmon3/temp1_label", "Composite\n")
        labels = [t["label"] for t in hostinfo.temperatures(root)]
        r.check("hostinfo: the CPU's cores in numeric order, then the CPU as a whole, then the board's sensors (chip 9 before chip 10), then the rest",
                labels == [f"CPU Core {n}" for n in range(12)] + ["CPU Package id 0", "Motherboard", "Unknown board temp 1", "Unknown board temp 2", "NVMe Composite"], labels)
        shutil.rmtree(hwmon)
        os.rename(aside, hwmon)
        r.check("hostinfo: chips are named in words, an unknown chip keeps its name, a sensor's own label is kept when the chip has several",
                [hostinfo.sensor_label(c, l, a) for c, l, a in (("nvme", "Composite", False), ("iwlwifi_1", "temp1", True), ("k10temp", "temp1", False), ("mychip", "temp1", True))]
                == ["NVMe Composite", "Wi-Fi", "CPU temp1", "mychip"], "")
        facts = hostinfo.host_facts(root)
        r.check("hostinfo: facts carry only what was read",
                set(facts) == {"hostname", "os", "kernel", "arch", "cpu_model", "cpu_threads",
                               "uptime_seconds", "tasks", "battery"}, sorted(facts))

        # A board chip's unwired input reads its register maximum, 127C, and is not a temperature either.
        fakehost._write(root, "sys/class/hwmon/hwmon6/name", "it8628\n")
        for n, milli in ((1, 39000), (2, 127000), (3, 126000)):
            fakehost._write(root, f"sys/class/hwmon/hwmon6/temp{n}_input", f"{milli}\n")
        board = [t["celsius"] for t in hostinfo.temperatures(root) if t["label"].startswith("Unknown board")]
        r.check("hostinfo: an input reading 127C is dropped, 126C is a temperature", board == [39.0, 126.0], board)
        shutil.rmtree(os.path.join(root, "sys/class/hwmon/hwmon6"))

        # A sensor stuck at a silly value is not a temperature.
        fakehost._write(root, "sys/class/hwmon/hwmon0/temp1_input", "-273000\n")
        r.check("hostinfo: an impossible reading is dropped",
                [t["label"] for t in hostinfo.temperatures(root)] == ["ThinkPad"], hostinfo.temperatures(root))

        # A VPS: nothing but /proc. Every optional reader says so quietly.
        fakehost.remove_sensors(root)
        r.check("hostinfo: no frequency scaling gives nothing", hostinfo.cpu_freq(root) == {})
        r.check("hostinfo: no sensors gives nothing", hostinfo.temperatures(root) == [] and hostinfo.fans(root) == [])
        r.check("hostinfo: no battery gives None", hostinfo.battery(root) is None)
        bare = hostinfo.host_facts(root)
        r.check("hostinfo: bare machine still has its basic facts, and no empty keys",
                {"hostname", "kernel", "uptime_seconds"} <= set(bare) and "battery" not in bare and "fans" not in bare, sorted(bare))

        # Thermal zones are the fallback when there are no hwmon chips.
        fakehost._write(root, "sys/class/thermal/thermal_zone0/type", "x86_pkg_temp\n")
        fakehost._write(root, "sys/class/thermal/thermal_zone0/temp", "61000\n")
        zone = hostinfo.temperatures(root)
        r.check("hostinfo: thermal zone used when no hwmon", zone == [{"label": "x86_pkg_temp", "celsius": 61.0, "max_c": 100.0}], zone)

        # An empty root is a machine that reports nothing at all: no crash.
        empty = os.path.join(root, "nothing")
        os.makedirs(empty)
        quiet = (hostinfo.uptime_seconds(empty), hostinfo.tasks(empty), hostinfo.os_name(empty),
                 hostinfo.cpu_model(empty), hostinfo.battery(empty), hostinfo.cpu_freq(empty),
                 hostinfo.temperatures(empty), hostinfo.fans(empty))
        r.check("hostinfo: an empty tree reads as nothing, never raises", quiet == (None, None, None, None, None, {}, [], []), quiet)
    finally:
        fakehost.destroy(root)
    _arm(r)


def _arm(r):
    """ARM boards and servers describe their CPU differently from x86."""
    import shutil
    import tempfile
    cases = {
        "a Raspberry Pi names the board, not the generic ARM core":
            ("processor\t: 0\nmodel name\t: ARMv7 Processor rev 3 (v7l)\nprocessor\t: 1\nHardware\t: BCM2711\nModel\t\t: Raspberry Pi 4 Model B Rev 1.4\n", None,
             {"model": "Raspberry Pi 4 Model B Rev 1.4", "threads": 2}),
        "a 64 bit board with only Model": ("processor\t: 0\nprocessor\t: 1\nprocessor\t: 2\nModel\t\t: Orange Pi 5\n", None, {"model": "Orange Pi 5", "threads": 3}),
        "an ARM server with no name has its threads and nothing more":
            ("processor\t: 0\nBogoMIPS\t: 50.00\nCPU implementer\t: 0x41\nprocessor\t: 1\n", None, {"model": None, "threads": 2}),
        "a device tree supplies the name when cpuinfo does not":
            ("processor\t: 0\nCPU part\t: 0xd0c\n", "Pine64 RockPro64\x00", {"model": "Pine64 RockPro64", "threads": 1}),
        "x86 still says its model name": ("processor\t: 0\nmodel name\t: Intel(R) Core(TM) i7\n", None, {"model": "Intel(R) Core(TM) i7", "threads": 1}),
    }
    for what, (cpuinfo, tree, want) in cases.items():
        root = tempfile.mkdtemp(prefix="dd-arm-")
        try:
            os.makedirs(os.path.join(root, "proc", "device-tree"))
            with open(os.path.join(root, "proc", "cpuinfo"), "w") as f:
                f.write(cpuinfo)
            if tree:
                with open(os.path.join(root, "proc", "device-tree", "model"), "w") as f:
                    f.write(tree)
            got = hostinfo.cpu_model(root)
            r.check(f"hostinfo: {what}", got == want, got)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def run(browser, r):
    _readers(r)

    # ---- the page, against the server's fake tree -----------------------------
    h.reset_user_config()
    _write_panels([{"id": "mem", "view": "bars"}, {"id": "cpu-freq"}, {"id": "temps"}, {"id": "fans"}, {"id": "host"}])
    page = h.new_page(browser)
    h.open_dashboard(page)
    h.shot(page, "hostinfo_01_panels")

    r.check("hostinfo: memory shows ram and swap rows", _bars(page, "mem-bars") == [["physical", "50%"], ["swap", "25%"]], _bars(page, "mem-bars"))
    r.check("hostinfo: memory headline names both", page.text_content("#mem-val") == "physical 50% / swap 25%", page.text_content("#mem-val"))
    r.check("hostinfo: cpu frequency rows per core",
            _bars(page, "cpu-freq-bars") == [["core0", "1.20GHz"], ["core1", "2.40GHz"]], _bars(page, "cpu-freq-bars"))
    r.check("hostinfo: temperature rows",
            _bars(page, "temps-bars") == [["CPU Package id 0", "54°C"], ["ThinkPad", "40.5°C"]], _bars(page, "temps-bars"))

    r.check("hostinfo: the fan is a FANS row, named for its chip and read in rpm", _bars(page, "fans-bars") == [["ThinkPad fan", "1200 rpm"]], _bars(page, "fans-bars"))
    for text, files in (("stopped", {"fan1_input": "0"}), ("fault", {"fan1_input": "900", "fan1_fault": "1"}), ("1200 rpm", {"fan1_input": "1200", "fan1_fault": "0"})):
        for fname, content in files.items():
            fakehost._write(h.HOST_DIR, f"sys/class/hwmon/hwmon1/{fname}", content + "\n")
        time.sleep(2.5)
        r.check(f"hostinfo: a fan at {files['fan1_input']} rpm reads '{text}'", _bars(page, "fans-bars")[0][1] == text, _bars(page, "fans-bars"))
    facts = _facts(page)
    r.check("hostinfo: host facts present", {"Host", "OS", "Kernel", "CPU", "Uptime", "Tasks", "Battery"} <= set(facts), sorted(facts))
    r.check("hostinfo: uptime reads as days hours minutes", facts.get("Uptime") == "1d 2h 3m", facts.get("Uptime"))
    r.check("hostinfo: cpu fact", facts.get("CPU") == "Fake CPU 9000 (2 threads)", facts.get("CPU"))
    r.check("hostinfo: os, tasks, battery", (facts.get("OS"), facts.get("Tasks"), facts.get("Battery"))
            == ("FakeOS 1.0 (Test)", "2 running / 345", "87% discharging"), facts)
    r.check("hostinfo: kernel names the architecture", "(" in facts.get("Kernel", "") and facts.get("Kernel", "").endswith(")"), facts.get("Kernel"))

    # ---- merge: the parts laid over each other on one bar, each still named below it ----
    h.enter_modify(page)
    for pid in ("mem", "cpu-freq", "temps"):
        page.locator(f"#{pid}-panel .panel-merge").click()
    time.sleep(0.5)
    rows = lambda pid: page.eval_on_selector_all(f"#{pid}-panel .detail-bottom .detail-row", "e => e.map(x => [x.children[0].textContent, x.children[1].textContent])")
    fills = lambda pid: page.locator(f"#{pid}-panel .stack-tracks .disk-fill").count()
    r.check("hostinfo: merged memory is a bar each for physical and swap, stacked", fills("mem") == 2 and page.locator("#mem-panel .disk-row").count() == 0)
    names = page.eval_on_selector_all("#mem-panel .detail-top .detail-row .detail-name", "e => e.map(x => x.textContent)")
    r.check("hostinfo: with the names above the bars and the readings below", names == ["physical", "swap"], names)
    ys = page.eval_on_selector_all("#mem-panel .detail-top, #mem-panel .stack-tracks, #mem-panel .detail-bottom", "e => e.map(x => x.getBoundingClientRect().top)")
    r.check("hostinfo: in that order, names, bars, readings", ys == sorted(ys) and len(set(ys)) == 3, ys)
    r.check("hostinfo: and each is still read out below", rows("mem") == [["physical", "50% used"], ["swap", "25% used"]], rows("mem"))
    r.check("hostinfo: merged frequency keeps every core", fills("cpu-freq") == 2 and rows("cpu-freq") == [["core0", "1.20GHz"], ["core1", "2.40GHz"]], rows("cpu-freq"))
    r.check("hostinfo: merged temperature keeps every sensor", fills("temps") == 2 and [x[1] for x in rows("temps")] == ["54\u00b0C", "40.5\u00b0C"], rows("temps"))

    r.check("hostinfo: host panel has no view choice (a list is all it is)",
            page.locator("#host-panel .panel-view").count() == 0 and page.locator("#temps-panel .panel-view").count() == 1)
    r.check("hostinfo: host panel has no merge or colour buttons",
            page.locator("#host-panel .panel-merge").count() == 0 and page.locator("#host-panel .panel-levels").count() == 0)

    # ---- saved settings are cleaned ------------------------------------------------
    cleaned = page.evaluate("""normalizePanels([{id: "host", view: "gauge", merge: true}, {id: "temps", view: "list"}])
                               .map(p => [p.id, p.view, p.merge])""")
    r.check("hostinfo: a host panel can only be a list, a series panel cannot be a list",
            cleaned == [["host", "list", False], ["temps", "bars", False]], cleaned)

    # ---- memory without swap is as it always was ---------------------------------
    solo = page.evaluate("""(() => {
      const snap = {mem: {percent: 50, swap_total_kb: 0, swap_percent: 0, used_kb: 1, total_kb: 2, swap_used_kb: 0}};
      const pal = ["a", "b", "c", "d", "e"];
      return [METRICS.mem.headline(snap, {}), METRICS.mem.series(snap, {palette: pal}).map(s => s.label)];
    })()""")
    r.check("hostinfo: no swap means one MEM series and the plain headline", solo == ["50%", ["MEM"]], solo)

    # ---- availability follows the machine -----------------------------------------
    h.enter_modify(page)
    for pid in ("cpu-freq", "temps", "fans", "host"):
        page.locator(f"#{h.PANEL_EL[pid]} .panel-remove").click()
    time.sleep(0.5)
    offered = _offered(page)
    r.check("hostinfo: every panel the machine can feed is offered",
            {"CPU-Freq", "TEMPS", "FANS", "HOST"} <= set(offered), offered)

    fakehost.remove_sensors(h.HOST_DIR)
    time.sleep(2.5)
    page.click("#launcher-modify-toggle")
    page.click("#launcher-modify-toggle")
    time.sleep(0.5)
    offered = _offered(page)
    r.check("hostinfo: a machine without sensors is not offered CPU-Freq or TEMPS",
            "CPU-Freq" not in offered and "TEMPS" not in offered and "FANS" not in offered, offered)
    r.check("hostinfo: HOST is still offered, every machine has a hostname", "HOST" in offered, offered)

    # A saved panel whose hardware has gone just stays empty, no errors.
    _write_panels([{"id": "cpu-freq"}, {"id": "temps"}, {"id": "host"}])
    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(2.5)
    r.check("hostinfo: panels with no data are empty, not broken",
            page.locator("#cpu-freq-bars > *").count() == 0 and page.locator("#temps-bars > *").count() == 0
            and "Uptime" in _facts(page), (page.locator("#temps-bars > *").count(), sorted(_facts(page))))
    r.check("hostinfo: a bare machine shows no battery or fan rows", "Battery" not in _facts(page), sorted(_facts(page)))
    r.check("hostinfo: no browser errors", page.dd_errors == [], page.dd_errors)

    fakehost.destroy(h.HOST_DIR)
    fakehost.build(h.HOST_DIR)
    h.reset_user_config()
    page.context.close()

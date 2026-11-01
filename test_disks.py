"""
Disks: by default every disk the machine has mounted, read from /proc/mounts, and only what a person listed
when they list them. (A desktop with eight drives showing one was the reason.)
"""

import os
import shutil
import sys
import tempfile

import dd_harness as h
import fakehost

sys.path.insert(0, h.APP_DIR)
import stats  # noqa: E402

MOUNTS = """proc /proc proc rw 0 0
sysfs /sys sysfs rw 0 0
/dev/nvme0n1p2 / ext4 rw 0 0
/dev/nvme0n1p1 /boot/efi vfat rw 0 0
/dev/sda1 /mnt/media ext4 rw 0 0
/dev/sdb1 /mnt/backup\\040disk xfs rw 0 0
/dev/sdc1 /data btrfs rw 0 0
/dev/sdc1 /data/snapshots btrfs rw,subvol=/snaps 0 0
/dev/sdd1 /home/a/data ext4 rw 0 0
/dev/sde1 /mnt/other/data ext4 rw 0 0
/dev/loop3 /snap/core/1 squashfs ro 0 0
/dev/sdf1 /snap/odd ext4 rw 0 0
tmpfs /run tmpfs rw 0 0
nas:/export /mnt/nas nfs rw 0 0
//server/share /mnt/smb cifs rw 0 0
/dev/mapper/crypt /vault ext4 rw 0 0
"""


def run(browser, r):
    root = tempfile.mkdtemp(prefix="dd-mounts-")
    try:
        fakehost._write(root, "proc/mounts", MOUNTS)
        got = stats.detect_mounts(root)
        paths = [m["path"] for m in got]
        r.check("disks: every real disk is found once, in mount order",
                paths == ["/", "/mnt/media", "/mnt/backup disk", "/data", "/home/a/data", "/mnt/other/data", "/vault"], paths)
        r.check("disks: the system's own mounts, the boot partition, snaps, images and network shares are left out",
                not any(p in paths for p in ("/proc", "/sys", "/boot/efi", "/snap/core/1", "/snap/odd", "/run", "/mnt/nas", "/mnt/smb")), paths)
        r.check("disks: a filesystem with several mounts of one device is one disk", "/data/snapshots" not in paths, paths)
        labels = {m["path"]: m["label"] for m in got}
        r.check("disks: / is root, others take their folder's name, and two with one name take their whole path",
                labels["/"] == "root" and labels["/mnt/media"] == "media" and labels["/vault"] == "vault"
                and labels["/home/a/data"] == "/home/a/data" and labels["/mnt/other/data"] == "/mnt/other/data" and labels["/mnt/backup disk"] == "backup disk", labels)
        r.check("disks: no /proc/mounts is no disks, not an error", stats.detect_mounts(os.path.join(root, "nothing")) == [])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    real = stats.disk_stats("/")
    r.check("disks: every disk of this machine is read, with readings", real and real[0]["path"] == "/" and real[0]["ok"] and real[0]["total_bytes"] > 0, real[:1])
    r.check("disks: no mountpoints setting is read or shipped, which disks a panel shows is the panel's own choice",
            "mountpoints" not in __import__("json").load(open(os.path.join(h.APP_DIR, "config.json"))))
    r.check("net: link capacity is the real NICs' speed in bytes per second (docker0 has no device, loopback is skipped)",
            stats.link_capacity(h.HOST_DIR) == 125000000, stats.link_capacity(h.HOST_DIR))
    r.check("net: no sys tree, no known capacity", stats.link_capacity(tempfile.mkdtemp(prefix="dd-nolink-")) is None)

    # Long disk names and readings stay inside the panel, whatever the view, by wrapping rather than overflowing.
    h.reset_user_config()
    with open(h.user_config_path(), "w") as fh:
        __import__("json").dump({"launcher": [], "panels": [
            {"id": "disk", "view": "gauge", "merge": True, "pct": "both", "amount": "both", "total": True, "size": 4}]}, fh)
    page = h.new_page(browser, width=700, height=1000)
    h.open_dashboard(page)
    r.check("disks: the panel under test is narrower than a bars cell's 240px, the case that used to overflow",
            page.evaluate("document.getElementById('disk-panel').getBoundingClientRect().width") < 240,
            page.evaluate("document.getElementById('disk-panel').getBoundingClientRect().width"))
    for view, merge in (("gauge", True), ("bars", True), ("number", True), ("bars", False), ("strip", False), ("gauge", False), ("ring", False)):
        out = page.evaluate("""([view, merge]) => {
            const live = panelViews.disk;
            live.cfg.view = view; live.cfg.merge = merge; reinitPanel(live);
            const d = (n, i) => ({path: "/mnt/" + n, label: n, ok: true, percent: 40 + i, used_bytes: 1.4e12, total_bytes: 2e12});
            const names = ["root", "criticaldata", "Storage00-WD2TB0", "Storage01-WD2TB1-with-a-very-long-name", "temp"];
            updatePanel(live, {...latestSnap, disk: names.map(d)}, readPalette());
            const box = document.getElementById("disk-panel").getBoundingClientRect();
            return [...document.querySelectorAll("#disk-panel *")].filter(e => e.getBoundingClientRect().width > 0)
              .map(e => [Math.round(e.getBoundingClientRect().right - box.right), e.tagName + "." + e.className.toString().slice(0, 40), e.textContent.slice(0, 30), Math.round(e.getBoundingClientRect().width)])
              .sort((a, b) => b[0] - a[0]).slice(0, 4);
        }""", [view, merge])
        r.check(f"disks: long names and readings stay inside the panel ({view}, {'merged' if merge else 'separate'})", out[0][0] <= 1, out)
    page.context.close()

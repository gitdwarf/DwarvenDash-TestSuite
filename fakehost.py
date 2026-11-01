"""
A fake /proc and /sys tree, for testing host readings.

One job: build, and take apart, a machine with known numbers. The test
machine has no swap, no CPU frequency scaling, no sensors and no battery,
so the readers are pointed at this tree instead (DWARVENDASH_HOST_ROOT for
the server, a root argument for the readers themselves).

Known numbers, so tests can assert exact text:
    memory     50% used, swap 25% used (of 2 GB), together 45%
    uptime     1d 2h 3m
    tasks      2 running / 345
    cpu        two threads, core0 1.2 GHz and core1 2.4 GHz of 3.6 GHz
    sensors    coretemp Package id 0 at 54.0 (crit 100), thinkpad temp1 at 40.5,
               a third reading of 0 that must be ignored as unplugged
    fan        thinkpad fan1 at 1200 rpm
    battery    87% discharging (and a mains adapter that must be ignored)
"""

import os
import shutil
import tempfile


def _write(root, relative, text):
    path = os.path.join(root, relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def build(root=None):
    """Create the tree (in a new temp directory unless a path is given) and return its path."""
    root = root or tempfile.mkdtemp(prefix="dd-host-")
    _write(root, "proc/meminfo",
           "MemTotal:        8000000 kB\nMemFree:          100000 kB\nMemAvailable:    4000000 kB\n"
           "SwapTotal:       2000000 kB\nSwapFree:        1500000 kB\n")
    _write(root, "proc/mounts", "/dev/sda1 / ext4 rw 0 0\n")
    _write(root, "sys/class/net/eth0/speed", "1000\n")
    os.makedirs(os.path.join(root, "sys/class/net/eth0/device"), exist_ok=True)
    _write(root, "sys/class/net/docker0/speed", "10000\n")
    _write(root, "proc/uptime", "93784.55 180000.00\n")
    _write(root, "proc/loadavg", "0.10 0.20 0.30 2/345 9999\n")
    _write(root, "proc/cpuinfo",
           "processor\t: 0\nmodel name\t: Fake CPU 9000\ncpu MHz\t\t: 1200.000\n\n"
           "processor\t: 1\nmodel name\t: Fake CPU 9000\ncpu MHz\t\t: 2400.000\n")
    _write(root, "etc/os-release", 'NAME="FakeOS"\nPRETTY_NAME="FakeOS 1.0 (Test)"\n')
    for n, cur in ((0, 1200000), (1, 2400000)):
        base = f"sys/devices/system/cpu/cpu{n}/cpufreq"
        _write(root, f"{base}/scaling_cur_freq", f"{cur}\n")
        _write(root, f"{base}/cpuinfo_max_freq", "3600000\n")
    _write(root, "sys/devices/system/cpu/cpuidle/current_driver", "none\n")
    _write(root, "sys/class/hwmon/hwmon0/name", "coretemp\n")
    _write(root, "sys/class/hwmon/hwmon0/temp1_input", "54000\n")
    _write(root, "sys/class/hwmon/hwmon0/temp1_label", "Package id 0\n")
    _write(root, "sys/class/hwmon/hwmon0/temp1_crit", "100000\n")
    _write(root, "sys/class/hwmon/hwmon0/temp2_input", "0\n")
    _write(root, "sys/class/hwmon/hwmon1/name", "thinkpad\n")
    _write(root, "sys/class/hwmon/hwmon1/temp1_input", "40500\n")
    _write(root, "sys/class/hwmon/hwmon1/fan1_input", "1200\n")
    _write(root, "sys/class/power_supply/BAT0/type", "Battery\n")
    _write(root, "sys/class/power_supply/BAT0/capacity", "87\n")
    _write(root, "sys/class/power_supply/BAT0/status", "Discharging\n")
    _write(root, "sys/class/power_supply/AC/type", "Mains\n")
    return root


def remove_sensors(root):
    """What a VPS looks like: no hwmon chips, no CPU frequency scaling, no battery."""
    shutil.rmtree(os.path.join(root, "sys/class/hwmon"), ignore_errors=True)
    shutil.rmtree(os.path.join(root, "sys/class/power_supply"), ignore_errors=True)
    for n in (0, 1):
        shutil.rmtree(os.path.join(root, f"sys/devices/system/cpu/cpu{n}/cpufreq"), ignore_errors=True)


def destroy(root):
    shutil.rmtree(root, ignore_errors=True)

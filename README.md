# Tests

Everything here is optional and is not part of the main repository. This directory is the DwarvenDash-TestSuite repository; clone it into the source directory as `tests/`, so that it sits next to `app/`.

```bash
sudo python3 tests/run.py            # everything
sudo python3 tests/run.py layout     # one module
```

Needs root and Python Playwright with a browser. Chromium is the default; `DD_BROWSER=firefox` or `DD_BROWSER=webkit` runs the same checks in Gecko or WebKit, and `DD_BROWSER_PATH` points at that browser when Playwright cannot find its own (`DD_CHROMIUM` still works for Chromium). Playwright drives its own patched builds, installed with `python3 -m playwright install firefox`, not a stock Firefox. Root is needed because the per-user config code works on real home directories: the suite creates a temporary account called `ddtest` and removes it afterwards. The server under test runs on port 18090 (`DD_TEST_PORT` to change it), with the real login helper on 18091 (only PAM, the group check and first-time folder setup replaced). Screenshots land in `tests/screenshots/`. The server under test reads its memory, sensors and uptime from a fake tree built by `fakehost.py` (`DWARVENDASH_HOST_ROOT`), because the machines tests run on rarely have swap, CPU frequency scaling, sensors or a battery; its numbers are listed at the top of that file. The exit code is 0 only if every check passes.

None of this is needed to install or use DwarvenDash.

## Modules

Pass any of these names to `run.py`. Each `test_<name>.py` holds only checks; `dd_harness.py` holds everything that is not a check (server and user lifecycle, the login helper with PAM replaced, the fake host tree, browser and canvas helpers).

### Drives the real page in a browser

| Module | What it checks |
|--------|----------------|
| `panels` | Remove, re-add and reorder for every panel type. A removed panel has no DOM node and a re-added chart is non-zero and painting live data (an older hide and show design left charts 0x0). |
| `widgets` | The eight views, merge and size, editable in Modify mode only, saved per user; the legacy config (a bare list of panel ids) still loads. |
| `levels` | Graduated colours, off by default. On-screen colour compared with what `gradeColor()` says for the same value. |
| `absolute` | Used/free and total on MEM and DISK: exact wording from a known snapshot, the real total against the filesystem, saving, narrow-panel layout. |
| `sweep` | The startup sweep: timetable and arithmetic exactly, then a frame-by-frame recording of the page from load (stages in order, panels waiting their turn, ending on the real readings, a view change waking one panel). |
| `status` | App status dots, off by default, only ever the user's own instances. With the option off nothing connects at all. |
| `icons` | App icons: the app's own icon, the favicon fallback, a letter tile, and that the route cannot be aimed at another host, a redirect off the host or an oversized file. Also, without credentials the route gives 401. |
| `version` | One `VERSION` file, reported the same everywhere. |
| `bookmarks` | Free-form URLs with no backing process. Removing one never calls `/deprovision-app`, checked at the network level. Page order is panels, apps, bookmarks. |
| `theme` | The theme XML checked directly (the shipped files, and every way a file can be wrong: bad XML, a missing or non-hex colour, CSS smuggled in a value, a DTD, a bad name, oversize), the `/themes`, `/theme.css` and `/theme` routes, a file dropped in appearing when Modify is opened, the rendered colours of every theme, readable text, a chrome accent that is not the colour of healthy or bad, no overflow at phone width. |
| `header` | The title bar, measured: version under the name, Log out beside Modify at the right end, no footer, the hostname option (off by default, centred when on, saved, on its own row on a phone). |
| `layout` | Where panels, apps and bookmarks sit, and flow against list, from bounding boxes the browser laid out. The 900px breakpoint in CSS and JavaScript agree. |
| `hostinfo` | Memory with swap, CPU frequency, temperatures and host facts. The readers are checked against a fake `/proc` and `/sys` (`fakehost.py`), including a VPS with no sensors, an unplugged sensor and an empty tree. Then the page: exact rows and text, merge, and that a panel the machine cannot feed is not offered. |
| `gpu` | The nvidia-smi reader against stand-in tools (good, partial, nonsense, failing, hung, missing), one run shared by pages, then the page against a server running the fake tool: GPU, GPU-MEM and the GPU row in TEMPS, one card and two, offered only while a GPU exists. |
| `login` | The sign-in form and its cookie. The session store (expiry, revocation, a per-person limit), the cookie's attributes, where a login may redirect to (no open redirect, no header injection, no loop), the page (escaping, no script), the real login helper over HTTP (wrong and right password, `Secure` over HTTPS, cookie beats Basic, a bearer token is not a login, leaving the group ends a session at once, logout kills the cookie even if copied), the dashboard accepting the cookie and not popping a native box when it is dead, the nginx templates and the cookie-removal patterns run on real cookie strings, the fail2ban filter, and the Log out button. |
| `numsize` | A single number (Composite-CPU) fills the panel width and is sized from it, numbers across a row line up, a bars panel sits in the middle of its room, and the Ring view renders (screenshot). |
| `temps` | The TEMPS panel with a desktop's number of sensors (fourteen, long names included): the Show list (counts, hiding, saved, open while used, closed by a press elsewhere or Escape, one open at a time), renaming the unknown board inputs (saved against the original name, cleaned, Escape drops the edit), legends and colours for a merged gauge, separate strips and bars staying usable at every size, a page of displays not moving when a list is used far down it, and the temperature unit (Auto by locale, Celsius, Fahrenheit, saved). |
| `disks` | DISK lists every real disk the machine has mounted, once and in mount order (system mounts, boot, snaps, images and network shares left out; one device with several mounts is one disk; names from the mount point), no `/proc/mounts` is no disks, NET's link capacity from the real NICs, and long names and readings staying inside a narrow panel in every view. |
| `dots` | The dot matrix view: the grid a reading becomes (font, bar, blanks), the saved style, the View and style lists, black dots in every style, plain paper lighter than the LCD, Colours giving the printer paper and the LCD overlay the flip board's process ink. Also: tapping a panel (dot matrix, gauge, ring) does not move its row, and the startup sequences of the dot matrix (the pure timetable, and every picture painted on the page for the LCD and the printer, with Colours on and off). |
| `overflow` | No reading or name runs out of its panel: every view, merged and separate, at half, third and quarter size of a narrow window (measured by element position), and the two rules behind it (a unit is measured as shown, a line may break after each " / "). |
| `flipboard` | The Flip board view (the flip clock and the split-flap board as its Numbers and Letters looks): the list of looks, what each draws, the choice saved under `flip` and remembered, no separate Board view. |

### Plain Python, no browser

| Module | What it checks |
|--------|----------------|
| `static` | Only files inside `static/` are served, including a sibling directory whose name merely starts with `static`. |
| `probe` | The app probe against stand-in servers that each behave like one kind of real app (relative links, root links, script-name aware, base path, nothing at /, stray links and examples, Host check, own login, generic cookie, nothing listening), and the own-port nginx text: main-site redirect, port server (plain and TLS, IPv4 and IPv6), shared sign-in wall, one copy of the proxy headers, writes only when changed, removal, a missing port never reaching nginx, and the shipped configs including the wall; and registering without --prefix-mode (the probe's answer becomes the registration, an explicit --url-prefix is kept, nothing running means the default and a hint). |
| `installer` | The installer's prerequisite check run on its own with a stand-in python3: a missing python-pam is explained (it used to stop silently under set -e). |
| `sysvinit` | Detection of a stale system-wide service on sysvinit, against fake rc scripts in a temp directory. DwarvenDash's own per-user lines never make the original look enabled. |
| `stoptree` | Stopping an instance stops the whole process tree, with real processes in the shape of Jackett's launcher, including instances made by older versions. |
| `identity` | Credentials, never a header, decide who is calling: no login, a forged `X-Authenticated-User`, a wrong password, the short success-only cache, and failing closed when the helper cannot be reached. |
| `reload` | nginx is reloaded after every port-map change (a second user of an app, a removal), `nginx -s reload` is tried first, a failure is reported, unregistering reloads once. `subprocess.run` is replaced by a recorder. |
| `proxy` | What the generated nginx routing does to an app's traffic: WebSocket upgrade headers, no upload cap, the login not forwarded, the verified user passed as `X-Remote-User`, `{port}` and `{home}` in start commands, old location files refreshed, and the stock configs (login-check size limit, failed-login log). Text checks in a temp directory; the real-nginx runs are in the development log. |
| `cleanup` | Leftovers of removed users and apps, in a fake world: what is removed and, as important, what is kept. User data is never deleted. |
| `logo` | One logo geometry (`app/logo.py`): the favicon file, the dashboard header and the sign-in page carry the same four parts, with the theme's colours through classes. |
| `sensorprobe` | `tools/sensor-probe.sh` against a throwaway hwmon tree: every input listed, the one that rose with the CPU called the CPU, 127C or more called implausible, the input's own type shown, no sensors said plainly, and no busy loop left behind. |
| `uninstall` | `install.sh uninstall`: the plan and confirmation (no terminal, `--yes`), the step order, every group member removed, and the nginx step against a fake tree (default site that serves the welcome page, HTTPS kept, welcome page restored only when none exists, nothing named dwarvendash left, an edited config and its files left alone, a rejected config reported). Stand-in nginx, systemctl, getent and gpasswd; nothing real is touched. The whole `uninstall --yes` runs against a fake root (`DWARVENDASH_ROOT`) on both init systems. A run on a real machine is not covered. |

## Not automated

The cross-user checks against a real stack (nginx, PAM, the dashboard, several apps for several users, a local account attacking the backends directly) were run by hand and are written up in `docs/development-log.md`, entries 37 and 38. They need an nginx and real accounts, so they are not in this suite.

## Lessons that shaped these

- Poll for the expected state, never sleep and hope.
- Check what the browser laid out and painted, not the attribute or class that was set.
- Every pass needs a way to fail. Break the code on purpose (a mutation) and confirm the test goes red.
- Test a fix against the old code too: a test the old code also passes is vacuous.
- Every browser page must finish with zero console errors, and layout work is checked by looking at the screenshots as well as the assertions.

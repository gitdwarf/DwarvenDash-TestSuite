"""
Themes: one XML file each, checked, written out as CSS in the user's own directory.

Three halves. The module (themes.py) is checked directly against files made for
the purpose: the shipped ones, the way a good file looks, and every way a file
can be wrong, because a bad theme must be ignored completely and a theme file
must never be able to put anything but colours into a stylesheet. Then the
routes: the list, the user's own stylesheet, choosing one. Then the page, which
checks the rendered colours rather than a flag, because a flag that flips with
no visual effect would pass a weaker test.
"""

import json
import os
import shutil
import sys
import tempfile
import time

import dd_harness as h

sys.path.insert(0, h.APP_DIR)
import themes  # noqa: E402

SHIPPED = ["chalk", "dusk", "forge", "lichen", "mithril", "moss"]
LABEL = {"dusk": "Dusk", "mithril": "Mithril", "forge": "Forge", "moss": "Moss", "chalk": "Chalk", "lichen": "Lichen", "system": "System"}
NEW_LOOKS = ["mithril", "forge", "chalk"]

CONTRAST_JS = """() => {
  const rgb = (c) => { const m = c.match(/\\d+(\\.\\d+)?/g).map(Number); return m.slice(0, 3); };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const probe = (prop, name) => { const d = document.createElement("div"); d.style[prop] = `var(${name})`; document.body.appendChild(d);
    const v = getComputedStyle(d)[prop === "color" ? "color" : "backgroundColor"]; d.remove(); return rgb(v); };
  const panel = probe("background", "--panel-bg");
  return { text: ratio(probe("color", "--text"), panel), dim: ratio(probe("color", "--text-dim"), panel),
           chrome: probe("color", "--chrome"), ok: probe("color", "--ok"), bad: probe("color", "--bad") };
}"""

# What forge gives the stylesheet that its file chooses; the rest is worked out from these and the palette.
FORGE = {"bg": "#14110e", "panel-bg": "#1d1915", "border": "#3a322a", "text": "#ddd2c3", "text-dim": "#8c7e6c", "chrome": "#d98a3d"}
FORGE_PALETTE = ["#d98a3d", "#7fa3a8", "#c9b48a", "#c76a5a", "#b8a07a"]
PALETTE_NAMES = ["ember", "steel", "sand", "brick", "tan"]
GROUP_OF = {"bg": ("background", 0), "bg-end": ("background", 1), "text": ("texts", 0), "text-dim": ("texts", 1),
            "panel-bg": ("panels", 0), "panel-bg-end": ("panels", 1), "border": ("panel-borders", 0), "border-end": ("panel-borders", 1)}


def _xml(name="test", colors=None, extra="", palette=FORGE_PALETTE):
    """
    A theme file in forge's colours. colors overrides by short key (bg, bg-end, text, text-dim, panel-bg, panel-bg-end,
    border, border-end), a value of None leaves that whole group out; palette=None leaves the palette out.
    """
    groups = {"background": ["#14110e", "#14110e"], "texts": ["#ddd2c3", "#8c7e6c"], "panels": ["#1d1915", "#1d1915"],
              "panel-borders": ["#3a322a", "#3a322a"]}
    for key, value in (colors or {}).items():
        group, i = GROUP_OF[key]
        if value is None:
            groups[group] = None
        elif groups[group] is not None:
            groups[group][i] = value
            if i == 0 and f"{key}-end" not in (colors or {}):
                groups[group][1] = value if group != "texts" else groups[group][1]
    body = "".join(f"    <{g}>\n      <start>{v[0]}</start>\n      <end>{v[1]}</end>\n    </{g}>\n" for g, v in groups.items() if v is not None)
    pal = "" if palette is None else "  <palette>\n" + "".join(
        f'    <color name="{PALETTE_NAMES[i] if i < 5 and palette is FORGE_PALETTE else ""}">{c}</color>\n' for i, c in enumerate(palette)) + "  </palette>\n"
    return f'<theme name="{name}">\n{pal}  <colors>\n{body}{extra}  </colors>\n</theme>\n'


def _rgb(hex_color):
    return "rgb({}, {}, {})".format(*(int(hex_color[i:i + 2], 16) for i in (1, 3, 5)))


# The theme's page colour (the top one, when the theme gives a gradient), as the browser sees it.
BG_JS = """() => { const d = document.createElement("div"); d.style.backgroundColor = "var(--bg)"; document.body.appendChild(d);
  const c = getComputedStyle(d).backgroundColor; d.remove(); return c; }"""


def _bg(page):
    return page.evaluate(BG_JS)


def _wait_bg(page, expected):
    page.wait_for_function(BG_JS, timeout=5000)
    page.wait_for_function("([js, c]) => eval(js)() === c", arg=[BG_JS, expected], timeout=5000)


def _click(page, label, expected_bg):
    page.select_option(".theme-switcher-select", label=label)
    _wait_bg(page, expected_bg)
    time.sleep(0.3)


def _json(path, user=None, data=None, method=None):
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(h.request(path, user, data, method), timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


# ---- the module ---------------------------------------------------------------------

def _module_checks(r):
    shipped = themes.load_themes(h.SHIPPED_THEME_DIR)
    r.check("themes: the six shipped files are all good themes, in name order", list(shipped) == SHIPPED, list(shipped))
    errors = [(f, themes.validate_theme_file(os.path.join(h.SHIPPED_THEME_DIR, f))[1]) for f in sorted(os.listdir(h.SHIPPED_THEME_DIR))]
    r.check("themes: none of them reports an error", all(e is None for _, e in errors), errors)
    r.check("themes: forge has the colours it chooses, and the accent is the palette's first",
            all(shipped["forge"]["colors"][k] == v for k, v in FORGE.items()) and shipped["forge"]["palette"] == FORGE_PALETTE, shipped["forge"]["colors"])
    r.check("themes: every stylesheet colour is there for every theme, worked out where the file does not say",
            all(set(t["colors"]) == set(themes.REQUIRED_COLOR_KEYS) for t in shipped.values()))
    r.check("themes: the files list their palette first", all(open(os.path.join(h.SHIPPED_THEME_DIR, f)).read().index("<palette>") < open(os.path.join(h.SHIPPED_THEME_DIR, f)).read().index("<colors>") for f in os.listdir(h.SHIPPED_THEME_DIR)))

    work = tempfile.mkdtemp(prefix="dd-themecheck-")
    try:
        def put(filename, text, binary=False):
            with open(os.path.join(work, filename), "wb" if binary else "w") as f:
                f.write(text)
            return os.path.join(work, filename)

        def verdict(filename, text, **kw):
            return themes.validate_theme_file(put(filename, text, **kw))

        name, error = verdict("good.xml", _xml("good"))
        r.check("themes: a good file is valid", (name, error) == ("good", None), (name, error))
        r.check("themes: the name comes from the file name when there is no name attribute",
                verdict("plain.xml", _xml("x").replace('<theme name="x">', "<theme>")) == ("plain", None))

        bad = {
            "not xml": ("a.xml", "this is not xml at all"),
            "empty file": ("b.xml", ""),
            "wrong root": ("c.xml", _xml("c").replace("theme", "skin")),
            "a group missing": ("d.xml", _xml("d", {"bg": None})),
            "a colour blank": ("e.xml", _xml("e", {"bg": "   "})),
            "a colour that is a word": ("f.xml", _xml("f", {"bg": "red"})),
            "a short hex": ("g.xml", _xml("g", {"bg": "#12"})),
            "not hex digits": ("h.xml", _xml("h", {"bg": "#gg0000"})),
            "a function": ("i.xml", _xml("i", {"bg": "url(http://evil.example/x)"})),
            "css smuggled in a value": ("j.xml", _xml("j", {"bg": "#fff; } body { display: none"})),
            "a palette colour name with markup": ("u.xml", _xml("u").replace('name="ember"', 'name="a;b"', 1)),
            "a name that is not in the palette": ("v.xml", _xml("v", {"bg": "nonesuch"})),
            "a group with no start": ("w.xml", _xml("w").replace("<start>#14110e</start>", "")),
            "the old format, one tag a colour": ("x.xml", '<theme name="x"><colors><bg>#000000</bg></colors>' + _xml("x").split("</colors>")[0].split("<colors>")[0].split("<theme")[1].split(">", 1)[1] + "</theme>"),
            "a name that climbs": ("l.xml", _xml("../etc")),
            "a doctype": ("n.xml", '<!DOCTYPE theme [<!ENTITY a "b">]>\n' + _xml("n")),
            "no palette": ("p.xml", _xml("p", palette=None)),
            "an empty palette": ("q.xml", _xml("q", palette=[])),
            "a palette colour that is a word": ("s.xml", _xml("s", palette=["#ffffff", "red"])),
            "a palette colour with css in it": ("t.xml", _xml("t", palette=["#fff; } body { display: none"])),
            "an entity": ("o.xml", _xml("o").replace("<colors>", '<colors><!ENTITY x "y">')),
        }
        results = {label: verdict(fn, text) for label, (fn, text) in bad.items()}
        r.check("themes: every kind of bad file is reported with a reason",
                all(isinstance(e, str) and e for _, e in results.values()), {k: v for k, v in results.items() if not v[1]})
        # Whitespace and capitals are never the author's fault.
        spaced = _xml("Deep Sea").replace("<colors>", "<colors>\n\n   ").replace("</start>", "  </start>").replace("<start>", "<start>  ")
        r.check("themes: a byte order mark, blank lines before the XML and padding around values are fine",
                verdict("spaced.xml", "\ufeff\n\n  " + spaced)[1] is None)
        r.check("themes: a name with capitals and a space is tidied, not refused", "deep-sea" in themes.load_themes(work), list(themes.load_themes(work)))
        named = _xml("named", {"bg": "ember", "bg-end": "Steel"})
        r.check("themes: a colour may be the name of a palette colour, in any capitals", verdict("named.xml", named)[1] is None)
        loaded_named = {k: v for k, v in themes.load_themes(work).items()}
        r.check("themes: and it means that palette colour", loaded_named["named"]["colors"]["bg"] == "#d98a3d" and loaded_named["named"]["bottoms"]["bg"] == "#7fa3a8", loaded_named.get("named"))
        r.check("themes: a group's end is optional and is the start when left out",
                verdict("noend.xml", _xml("noend").replace("      <end>#1d1915</end>\n", ""))[1] is None
                and themes.load_themes(work)["noend"]["bottoms"]["panel-bg"] == "#1d1915")
        r.check("themes: a palette colour may carry a name for people", 'name="ember"' in open(os.path.join(h.SHIPPED_THEME_DIR, "forge.xml")).read())
        r.check("themes: a palette problem is named", all("palette" in results[k][1] for k in results if "palette" in k), results)
        r.check("themes: a palette may be one colour or any number (forty here)",
                verdict("one.xml", _xml("one", palette=["#ffffff"]))[1] is None and verdict("many.xml", _xml("many", palette=["#ffffff"] * 40))[1] is None)
        r.check("themes: a missing group is named", "background" in results["a group missing"][1], results["a group missing"])
        big = _xml("big", extra="<!-- " + "x" * (themes.MAX_THEME_BYTES + 10) + " -->\n")
        r.check("themes: a file over the size limit is refused", isinstance(verdict("big.xml", big)[1], str))
        r.check("themes: an unreadable path reports itself, it does not raise",
                themes.validate_theme_file(os.path.join(work, "nothing.xml")) == ("nothing", "unreadable or empty file"))

        # Bad files are ignored completely: only the good file is loaded.
        put("notes.txt", "not a theme")
        loaded = themes.load_themes(work)
        r.check("themes: only good files are loaded, bad ones and other file types are ignored entirely",
                list(loaded) == ["deep-sea", "good", "many", "named", "noend", "one", "plain"], list(loaded))
        r.check("themes: a missing directory is no themes, not an error", themes.load_themes(os.path.join(work, "gone")) == {})

        # What goes in the stylesheet: the known names with hex values, nothing else.
        put("extra.xml", _xml("extra", extra="    <evil>expression(alert(1))</evil>\n    <position>fixed</position>\n"))
        css = themes.render_css(themes.load_themes(work), "extra")
        r.check("themes: unknown elements in a file never reach the stylesheet", "evil" not in css and "alert" not in css and "position" not in css, css)
        lines = [l.strip() for l in css.splitlines() if l.strip().startswith("--")]
        r.check("themes: the stylesheet holds exactly the colours, then the palette in order, then the fills",
                [l.split(":")[0] for l in lines] == [f"--{k}" for k in themes.REQUIRED_COLOR_KEYS]
                + [f"--palette-{i}" for i in range(1, len(FORGE_PALETTE) + 1)] + [f"--{k}-fill" for k in themes.GRADIENT_KEYS], lines)
        r.check("themes: the palette colours are written as given", [l.split(": ")[1].rstrip(";") for l in lines if l.startswith("--palette-")] == FORGE_PALETTE, lines)

        # Gradients: every group has a start and an end; the stylesheet always gets a top to bottom fill.
        r.check("themes: a group missing is refused, not guessed", isinstance(verdict("g2.xml", _xml("g2", {"text": None}))[1], str))
        put("g.xml", _xml("g", {"bg": "#112233", "bg-end": "#445566", "panel-bg": "#202020"}))
        gt = themes.load_themes(work)["g"]
        r.check("themes: a start and end is a gradient, the start is still the colour",
                gt["colors"]["bg"] == "#112233" and gt["bottoms"]["bg"] == "#445566" and gt["bottoms"]["panel-bg"] == "#202020", gt)
        gcss = themes.render_css(themes.load_themes(work), "g")
        r.check("themes: every fill is top to bottom, of one colour when the group has one",
                "--bg-fill: linear-gradient(to bottom, #112233, #445566);" in gcss and "--panel-bg-fill: linear-gradient(to bottom, #202020, #202020);" in gcss
                and "--border-fill: linear-gradient(to bottom, #3a322a, #3a322a);" in gcss and "--bg: #112233;" in gcss, gcss)
        # What the file does not say is worked out, and the palette's first colour is the accent.
        d = themes.load_themes(work)["g"]["colors"]
        r.check("themes: the accent is the palette's first colour and the dim text is the texts' end", d["chrome"] == FORGE_PALETTE[0] and d["text-dim"] == "#8c7e6c", d)
        r.check("themes: the inputs sit between the panel and the text, the track is darker than the background's end",
                d["input-bg"] != d["panel-bg"] and d["track-bg"] < gt["bottoms"]["bg"], d)
        def group(tag, start, end):
            return f"    <{tag}>\n      <start>{start}</start>\n      <end>{end}</end>\n    </{tag}>\n"
        put("own.xml", _xml("own", extra=group("controls", "#303030", "ember") + group("up", "#00ff00", "#00aa00") + group("down", "#ff0000", "Brick")))
        k = themes.load_themes(work)["own"]
        r.check("themes: controls, up and down are the file's own when it gives them, an end may be a palette name",
                k["colors"]["input-bg"] == "#303030" and k["bottoms"]["input-bg"] == "#d98a3d" and k["colors"]["ok"] == "#00ff00"
                and k["bottoms"]["ok"] == "#00aa00" and k["colors"]["bad"] == "#ff0000" and k["bottoms"]["bad"] == "#c76a5a", k)
        r.check("themes: the hover of a control is a little further towards the text, at both ends",
                k["colors"]["input-bg-hover"] != k["colors"]["input-bg"] and k["bottoms"]["input-bg-hover"] != k["bottoms"]["input-bg"], k)
        r.check("themes: they all reach the stylesheet as fills", all(f"--{n}-fill: linear-gradient(to bottom," in themes.render_css(themes.load_themes(work), "own")
                                                                   for n in ("input-bg", "input-bg-hover", "ok", "bad")))
        r.check("themes: a control group with a bad colour makes the whole theme invalid", isinstance(verdict("badc.xml", _xml("badc", extra=group("controls", "red", "red")))[1], str))
        r.check("themes: otherwise they are worked out: ok and bad differ, and a light theme's differ from a dark one's",
                d["ok"] != d["bad"] and themes.load_themes(h.SHIPPED_THEME_DIR)["chalk"]["colors"]["ok"] != d["ok"], d)
        r.check("themes: a missing end for the texts is the start faded into the background",
                themes.load_themes(work)["noend"]["colors"]["text-dim"] != themes.load_themes(work)["noend"]["colors"]["text"])
        put("zz-other.xml", _xml("good", {"bg": "#000000"}))
        r.check("themes: two files with one name, the later file wins",
                themes.load_themes(work)["good"]["colors"]["bg"] == "#000000")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    both = themes.render_css(shipped, "system")
    r.check("themes: system is the dark theme, and the light one for a light browser",
            "--bg: #101214;" in both and "@media (prefers-color-scheme: light)" in both and "--bg: #eef1f1;" in both, both[:200])
    only_dark = {k: v for k, v in shipped.items() if k != "chalk"}
    r.check("themes: system with no light theme is just the dark one", "prefers-color-scheme" not in themes.render_css(only_dark, "system"))
    r.check("themes: no themes at all is an empty stylesheet, not an error",
            themes.render_css({}, "mithril") == "" and themes.render_css({}, "system") == "")
    r.check("themes: saved values from before themes had names still mean what they did",
            [themes.normalize_choice(c, shipped) for c in ("dark", "light", "nonsense", None, "forge", "system")]
            == ["moss", "lichen", "mithril", "mithril", "forge", "system"])
    r.check("themes: the list offered is each good theme and then System",
            [t["id"] for t in themes.theme_list(shipped)] == SHIPPED + ["system"])


# ---- the routes ---------------------------------------------------------------------

def _route_checks(r):
    h.reset_user_config()
    h.reset_themes()

    status, _, body = _json("/themes")
    listing = json.loads(body)
    r.check("themes: /themes lists them with the active one", status == 200 and [t["id"] for t in listing["themes"]] == SHIPPED + ["system"]
            and listing["active"] == "mithril", listing)

    status, headers, body = _json("/theme.css")
    css = body.decode()
    r.check("themes: a user with no choice gets the default theme as CSS, never cached",
            status == 200 and headers["Content-Type"].startswith("text/css") and headers["Cache-Control"] == "no-store"
            and "--bg: #101214;" in css, (status, dict(headers)))
    r.check("themes: and it was written to their own directory", os.path.isfile(h.user_theme_css_path())
            and open(h.user_theme_css_path()).read() == css)
    r.check("themes: a cache buster on the address still finds it", _json("/theme.css?v=123")[2].decode() == css)

    status, _, body = _json("/theme", data=b'{"theme": "forge"}', method="POST")
    r.check("themes: choosing a theme answers ok", status == 200 and json.loads(body) == {"ok": True, "theme": "forge"}, body)
    r.check("themes: it is cloned as CSS into the user's directory", "--bg: #14110e;" in open(h.user_theme_css_path()).read())
    r.check("themes: and remembered in their config", h.read_user_config().get("theme") == "forge")
    r.check("themes: /themes now reports it active", json.loads(_json("/themes")[2])["active"] == "forge")

    before = open(h.user_theme_css_path()).read()
    for label, payload in (("an unknown name", b'{"theme": "nonsense"}'), ("a path", b'{"theme": "../x"}'),
                           ("nothing", b'{"theme": null}'), ("a number", b'{"theme": 5}'), ("not json", b"xx"),
                           ("a list", b"[1]")):
        status, _, _ = _json("/theme", data=payload, method="POST")
        r.check(f"themes: choosing {label} is refused", status == 400, status)
    r.check("themes: and a refusal changes nothing", open(h.user_theme_css_path()).read() == before
            and h.read_user_config().get("theme") == "forge")

    # A file dropped in is offered at once; a bad one is not; a removed one cannot be chosen.
    h.write_theme("ember.xml", _xml("ember", {"bg": "#201008"}))
    h.write_theme("broken.xml", _xml("broken", {"bg": "nope"}))
    h.write_theme("junk.xml", "<theme")
    ids = [t["id"] for t in json.loads(_json("/themes")[2])["themes"]]
    r.check("themes: a dropped-in good file is offered, bad files are not", "ember" in ids and "broken" not in ids and "junk" not in ids, ids)
    r.check("themes: it can be chosen and becomes CSS", _json("/theme", data=b'{"theme": "ember"}', method="POST")[0] == 200
            and "--bg: #201008;" in open(h.user_theme_css_path()).read())
    os.remove(os.path.join(h.THEME_DIR, "ember.xml"))
    r.check("themes: the user's copy survives the file going away", "--bg: #201008;" in _json("/theme.css")[2].decode())
    r.check("themes: but it is no longer on offer, or choosable",
            "ember" not in [t["id"] for t in json.loads(_json("/themes")[2])["themes"]]
            and _json("/theme", data=b'{"theme": "ember"}', method="POST")[0] == 400)

    # A person's own themes: ~/.config/dwarvendash/themes/, theirs alone, replacing a shared one of the same name.
    saved_css, saved_cfg = open(h.user_theme_css_path()).read(), h.read_user_config()
    mine = os.path.join(os.path.dirname(h.user_config_path()), "themes")
    shutil.rmtree(mine, ignore_errors=True)
    os.makedirs(mine)
    with open(os.path.join(mine, "mine.xml"), "w") as f:
        f.write(_xml("mine", {"bg": "#0a0b0c"}))
    with open(os.path.join(mine, "forge.xml"), "w") as f:
        f.write(_xml("forge", {"bg": "#222222"}))
    with open(os.path.join(mine, "broken.xml"), "w") as f:
        f.write(_xml("broken", {"bg": "nope"}))
    secret = os.path.join(os.path.dirname(mine), "linked-target.xml")
    with open(secret, "w") as f:
        f.write(_xml("sneaky", {"bg": "#123456"}))
    os.symlink(secret, os.path.join(mine, "sneaky.xml"))
    ids = [t["id"] for t in json.loads(_json("/themes")[2])["themes"]]
    r.check("themes: a theme in the user's own folder is offered to them, a bad one and a symlink are not",
            "mine" in ids and "broken" not in ids and "sneaky" not in ids, ids)
    r.check("themes: it can be chosen and is written as their CSS", _json("/theme", data=b'{"theme": "mine"}', method="POST")[0] == 200
            and "--bg: #0a0b0c;" in open(h.user_theme_css_path()).read())
    _json("/theme", data=b'{"theme": "forge"}', method="POST")
    r.check("themes: their own forge replaces the shared forge, for them", "--bg: #222222;" in open(h.user_theme_css_path()).read())
    shutil.rmtree(mine)
    os.remove(secret)
    r.check("themes: with their folder gone they are back to the shared ones",
            "mine" not in [t["id"] for t in json.loads(_json("/themes")[2])["themes"]])
    with open(h.user_theme_css_path(), "w") as f:
        f.write(saved_css)
    with open(h.user_config_path(), "w") as f:
        json.dump(saved_cfg, f)

    # Someone else's login does not reach this user's stylesheet.
    r.check("themes: no credentials, no stylesheet", _json("/theme.css", user=False)[0] == 401)
    r.check("themes: no credentials, no choosing", _json("/theme", data=b'{"theme": "moss"}', method="POST", user=False)[0] == 401
            and h.read_user_config().get("theme") == "ember")

    # Someone with the old config (before themes were files) and no stylesheet yet.
    os.remove(h.user_theme_css_path())
    cfg = h.read_user_config()
    cfg["theme"] = "dark"
    with open(h.user_config_path(), "w") as f:
        json.dump(cfg, f)
    r.check("themes: a saved 'dark' with no stylesheet yet becomes moss", "--bg: #12140f;" in _json("/theme.css")[2].decode())

    # No themes at all: an empty stylesheet and an empty list but System, nothing breaks.
    os.remove(h.user_theme_css_path())
    for f in os.listdir(h.THEME_DIR):
        os.remove(os.path.join(h.THEME_DIR, f))
    status, _, body = _json("/theme.css")
    r.check("themes: an empty themes directory gives an empty stylesheet", status == 200 and body == b"", (status, body))
    r.check("themes: and only System on offer", [t["id"] for t in json.loads(_json("/themes")[2])["themes"]] == ["system"])
    h.reset_themes()
    h.reset_user_config()


# ---- the page -----------------------------------------------------------------------

def run(browser, r):
    _module_checks(r)
    _route_checks(r)

    h.reset_user_config()
    h.reset_themes()
    shipped = themes.load_themes(h.SHIPPED_THEME_DIR)
    want = {n: _rgb(shipped[n]["colors"]["bg"]) for n in SHIPPED}

    page = h.new_page(browser, color_scheme="dark")
    h.open_dashboard(page, settle=1)

    r.check("theme: defaults to mithril", _bg(page) == want["mithril"], _bg(page))
    r.check("theme: switcher hidden outside modify mode", page.locator(".theme-switcher").count() == 0)
    h.enter_modify(page)
    r.check("theme: switcher lists what the themes directory holds, then System",
            page.eval_on_selector_all(".theme-switcher-select option", "e => e.map(x => x.textContent)") ==
            ["Chalk", "Dusk", "Forge", "Lichen", "Mithril", "Moss", "System"])
    r.check("theme: the switcher is a labelled dropdown showing the active theme",
            page.eval_on_selector(".theme-switcher", "e => e.textContent.startsWith('theme:')") and page.eval_on_selector(".theme-switcher-select", "e => e.selectedOptions[0].textContent") == "Mithril")

    # The switcher is in the title bar, in the options row under the brand row, clear of Done and Log out.
    r.check("theme: switcher is inside the title bar", page.locator("header.brand .theme-switcher").count() == 1)
    geo = page.evaluate("""() => {
      const b = e => document.querySelector(e).getBoundingClientRect();
      return { name: b(".brand-name"), sw: b(".theme-switcher"), done: b("#launcher-modify-toggle"), out: b("#logout-button") };
    }""")
    r.check("theme: switcher sits in its own row under the name", geo["sw"]["top"] >= geo["name"]["bottom"] - 1, str(geo))
    r.check("theme: switcher does not overlap Done or Log out",
            geo["sw"]["top"] >= max(geo["done"]["bottom"], geo["out"]["bottom"]) - 1 or geo["sw"]["right"] <= geo["done"]["left"], str(geo))

    page.set_viewport_size({"width": 375, "height": 900})
    time.sleep(0.4)
    r.check("theme: no sideways scroll at phone width in modify mode",
            not page.evaluate("document.documentElement.scrollWidth > innerWidth"), str(page.evaluate("document.documentElement.scrollWidth")))
    page.set_viewport_size({"width": 1200, "height": 1000})
    time.sleep(0.4)

    # Every theme: applied, visibly different, readable, saved, and its CSS is in the user's directory.
    for theme in SHIPPED:
        _click(page, LABEL[theme], want[theme])
        stats = page.evaluate(CONTRAST_JS)
        r.check(f"theme: {theme} body text is easily readable (contrast >= 7)", stats["text"] >= 7, round(stats["text"], 1))
        r.check(f"theme: {theme} secondary text stays legible (contrast >= 3.5)", stats["dim"] >= 3.5, round(stats["dim"], 1))
        if theme in NEW_LOOKS:
            r.check(f"theme: {theme} chrome accent is neither the ok nor the bad colour",
                    stats["chrome"] != stats["ok"] and stats["chrome"] != stats["bad"], stats)
        number = page.evaluate("""() => { const e = document.querySelector("#load-panel .num-big");
            if (!e) return null; const d = document.createElement("div"); d.style.color = "var(--palette-1)"; document.body.appendChild(d);
            const want = getComputedStyle(d).color; d.remove(); return [getComputedStyle(e).color, want]; }""")
        r.check(f"theme: {theme} the page reads the palette the file gives, in order",
                page.evaluate("readPalette()") == [c.lower() for c in shipped[theme]["palette"]], page.evaluate("readPalette()"))
        r.check("theme: a palette shorter than the panels starts again at the first colour",
                page.evaluate("[colorAt(['a', 'b', 'c'], 4), colorAt(['a'], 7), colorAt(['a', 'b'], 0)]") == ["b", "a", "a"])
        r.check(f"theme: {theme} series colours switch at once, not on the next tick", number is None or number[0] == number[1], number)
        r.check(f"theme: {theme} saved as '{theme}', and its CSS is in the user's directory",
                h.read_user_config().get("theme") == theme and shipped[theme]["colors"]["bg"] in open(h.user_theme_css_path()).read(),
                h.read_user_config().get("theme"))
        r.check(f"theme: {theme} is marked as the active button",
                page.eval_on_selector(".theme-switcher-select", "e => e.selectedOptions[0].textContent") == LABEL[theme])
        fills = page.evaluate("""() => { const v = (n) => (getComputedStyle(document.documentElement).getPropertyValue(n).match(/#[0-9a-f]{6}/gi) || []);
            return { bg: v("--bg-fill"), panel: v("--panel-bg-fill"), image: getComputedStyle(document.querySelector(".panel")).backgroundImage,
                     attach: getComputedStyle(document.body).backgroundAttachment }; }""")
        two = lambda f: len(f) == 2 and f[0] != f[1]
        r.check(f"theme: {theme} paints its panels as the fill (and its border as a second layer), the page fixed to the window",
                fills["image"].count("linear-gradient") == 2 and fills["attach"] == "fixed" and two(fills["bg"]) == (theme == "dusk") and two(fills["panel"]) == (theme == "dusk"), fills)
        h.shot(page, f"theme_{theme}")
    r.check("theme: all six looks have a different background", len(set(want.values())) == 6, want)

    # Persistence.
    _click(page, "Forge", want["forge"])
    page.reload()
    page.wait_for_selector("#meters .panel")
    r.check("theme: forge persists after reload", _bg(page) == want["forge"], _bg(page))

    # System: Mithril for a dark OS, Chalk for a light one, live, by the stylesheet itself.
    h.enter_modify(page)
    _click(page, "System", want["mithril"])
    page.emulate_media(color_scheme="dark")
    _wait_bg(page, want["mithril"])
    r.check("theme: system follows a dark OS to mithril", _bg(page) == want["mithril"], _bg(page))
    page.emulate_media(color_scheme="light")
    _wait_bg(page, want["chalk"])
    r.check("theme: system flips live to chalk with no reload", _bg(page) == want["chalk"], _bg(page))
    r.check("theme: system stored as 'system', not a resolved value", h.read_user_config().get("theme") == "system")
    page.emulate_media(color_scheme="dark")

    # A theme dropped into the directory shows up the next time Modify is opened, and can be used.
    h.write_theme("ember.xml", _xml("ember", {"bg": "#201008"}))
    h.write_theme("broken.xml", _xml("broken", {"bg": "nope"}))
    page.click("#launcher-modify-toggle")  # Done
    time.sleep(0.3)
    page.click("#launcher-modify-toggle")  # Modify again: the directory is read again
    page.wait_for_selector(".theme-switcher-select")
    labels = page.eval_on_selector_all(".theme-switcher-select option", "e => e.map(x => x.textContent)")
    r.check("theme: a dropped-in good theme appears when Modify is opened, a bad one does not",
            "Ember" in labels and "Broken" not in labels, labels)
    _click(page, "Ember", "rgb(32, 16, 8)")
    r.check("theme: and it is applied", _bg(page) == "rgb(32, 16, 8)", _bg(page))
    page.reload()
    page.wait_for_selector("#meters .panel")
    r.check("theme: and kept across a reload", _bg(page) == "rgb(32, 16, 8)", _bg(page))
    os.remove(os.path.join(h.THEME_DIR, "ember.xml"))
    page.reload()
    page.wait_for_selector("#meters .panel")
    r.check("theme: the user's copy outlives the file", _bg(page) == "rgb(32, 16, 8)", _bg(page))

    # Legacy saved values (before themes had names) and no stylesheet yet keep their original look.
    for legacy, now in (("dark", "moss"), ("light", "lichen"), ("nonsense", "mithril")):
        if os.path.exists(h.user_theme_css_path()):
            os.remove(h.user_theme_css_path())
        with open(h.user_config_path()) as f:
            cfg = json.load(f)
        cfg["theme"] = legacy
        with open(h.user_config_path(), "w") as f:
            json.dump(cfg, f)
        page.reload()
        page.wait_for_selector("#meters .panel")
        r.check(f"theme: saved '{legacy}' loads as {now}", _bg(page) == want[now], _bg(page))

    # Branding.
    r.check("theme: wordmark and mark are on the page",
            page.inner_text(".brand-name") == "DWARVENDASH" and page.locator(".brand-mark").count() == 1)
    status = page.evaluate("fetch('/favicon.svg').then(r => [r.status, r.headers.get('content-type')])")
    r.check("theme: favicon is served as svg", status == [200, "image/svg+xml"], status)

    h.finish_page(r, page, "theme")
    page.context.close()
    h.reset_themes()
    h.reset_user_config()

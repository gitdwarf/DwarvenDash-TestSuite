"""
Bookmarks: free-form URLs with no backing process.

Key property: removing a bookmark must never call /deprovision-app
(there is nothing to deprovision). That is checked at the network level,
not just by looking at the screen.
"""

import json
import time
import urllib.request

import dd_harness as h


def _post(path, body):
    req = h.request(path, data=json.dumps(body).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def _bookmark_titles(page):
    return page.eval_on_selector_all(".launcher-link-item a", "e => e.map(x => x.textContent)")


def _add(page, title, url):
    page.fill("#add-bookmark .add-bookmark-title", title)
    page.fill("#add-bookmark .add-bookmark-url", url)
    page.click("#add-bookmark button")
    time.sleep(1)


def run(browser, r):
    h.reset_user_config()
    page = h.new_page(browser)
    h.open_dashboard(page, settle=1)

    r.check("bookmarks: add box hidden outside modify mode", not page.locator("#add-bookmark .add-bookmark-row").count())
    h.enter_modify(page)
    r.check("bookmarks: add box shown in modify mode", page.locator("#add-bookmark .add-bookmark-row").count() == 1)

    # Server-side rejection, directly against the API, so it holds without the UI.
    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://example.com/x", "example.com", "http://"):
        status, _ = _post("/add-bookmark", {"title": "bad", "url": bad})
        r.check(f"bookmarks: server rejects {bad!r}", status == 400, status)
    r.check("bookmarks: rejected URLs left no trace on disk",
            not any(g.get("group") == "Bookmarks" for g in h.read_user_config().get("launcher", [])) if _config_exists() else True)

    page.on("dialog", lambda d: d.dismiss())
    _add(page, "First", "https://example.com/one")
    _add(page, "Second", "http://example.org/two")
    r.check("bookmarks: both appear in the launcher", _bookmark_titles(page) == ["First", "Second"], _bookmark_titles(page))

    cfg = h.read_user_config()
    group = next((g for g in cfg["launcher"] if g.get("group") == "Bookmarks"), None)
    r.check("bookmarks: saved in own Bookmarks group, typed as bookmark",
            bool(group) and [(l["title"], l["type"]) for l in group["links"]] == [("First", "bookmark"), ("Second", "bookmark")], group)
    h.shot(page, "bookmarks_01_added")

    first = page.locator(".launcher-link-item", has_text="First")
    r.check("bookmarks: link opens in a new tab safely",
            first.locator("a").get_attribute("target") == "_blank" and "noopener" in first.locator("a").get_attribute("rel"))

    # A drop inserts before the target, so Second dropped onto First swaps them.
    page.drag_and_drop('.launcher-link-item:has-text("Second") a', '.launcher-link-item:has-text("First") a')
    time.sleep(1)
    r.check("bookmarks: drag reorder", _bookmark_titles(page) == ["Second", "First"], _bookmark_titles(page))

    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(1)
    r.check("bookmarks: order persists after reload", _bookmark_titles(page) == ["Second", "First"], _bookmark_titles(page))

    h.enter_modify(page)
    deprovision_calls = []
    page.on("request", lambda req: deprovision_calls.append(req.url) if "/deprovision-app" in req.url else None)
    page.click('.launcher-link-remove[title="Remove Second"]')
    time.sleep(1.5)
    r.check("bookmarks: removed from screen", _bookmark_titles(page) == ["First"], _bookmark_titles(page))
    r.check("bookmarks: removal never calls /deprovision-app", not deprovision_calls, deprovision_calls)
    saved = [l["title"] for g in h.read_user_config()["launcher"] for l in g["links"]]
    r.check("bookmarks: removal persisted to disk", saved == ["First"], saved)

    # Page order is panels, apps, available apps, bookmarks, add a bookmark.
    # Available apps must never split the bookmarks from their add box.
    cfg = h.read_user_config()
    cfg["launcher"].insert(0, {"group": "Apps", "links": [
        {"title": "alpha", "url": "/apps/alpha/", "type": "app"}]})
    with open(h.user_config_path(), "w") as fh:
        json.dump(cfg, fh)
    page.route("**/available-apps", lambda route: route.fulfill(
        status=200, content_type="application/json", body='[{"app": "beta"}]'))
    page.reload()
    page.wait_for_selector("#meters .panel")
    time.sleep(1)
    h.enter_modify(page)
    page.wait_for_selector("#available-apps .available-apps-list", state="visible")
    tops = page.evaluate("""() => Object.fromEntries(
      ["meters", "launcher", "available-apps", "launcher-bookmarks", "add-bookmark"]
        .map(id => [id, document.getElementById(id).getBoundingClientRect().top]))""")
    order = sorted(tops, key=tops.get)
    r.check("bookmarks: page order is panels, apps, available, bookmarks, add",
            order == ["meters", "launcher", "available-apps", "launcher-bookmarks", "add-bookmark"], str(tops))
    r.check("bookmarks: bookmark group sits only in the bookmarks slot",
            page.locator("#launcher-bookmarks .launcher-group-title").all_inner_texts() == ["Bookmarks"] and
            "Bookmarks" not in page.locator("#launcher .launcher-group-title").all_inner_texts())
    r.check("bookmarks: app group sits in the apps slot",
            page.locator("#launcher .launcher-group-title").all_inner_texts() == ["Apps"])
    pos = page.evaluate("""() => {
      const y = sel => document.querySelector(sel).getBoundingClientRect();
      return { app: y('#launcher .launcher-link-item').bottom, avail: y('#available-apps'),
               mark: y('#launcher-bookmarks .launcher-link-item').top };
    }""")
    r.check("bookmarks: the app link is above the available box, the bookmark link below it",
            pos["app"] <= pos["avail"]["top"] and pos["mark"] >= pos["avail"]["bottom"], str(pos))
    h.shot(page, "bookmarks_02_order")

    h.finish_page(r, page, "bookmarks")
    page.context.close()


def _config_exists():
    import os
    return os.path.exists(h.user_config_path())

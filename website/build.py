#!/usr/bin/env python3
"""
Build the ECE Capstone Laboratory site.

    python3 build.py              # src/ + data/ + static/  ->  dist/
    python3 build.py --serve      # build, then serve dist/ at http://localhost:8000
    python3 build.py --serve --host 0.0.0.0   # same, and let others on the network see it
    python3 build.py --check      # build, then check every internal link in dist/
    python3 build.py --external   # also check external links (slow, needs network)
    python3 build.py --zip        # also pack dist/ into lab-site-preview.zip to send to someone

dist/ is plain HTML, CSS and JS. Copy it onto the Apache document root as-is.
The server needs nothing else: no PHP, no database, no build step of its own.

Where things live, so the next person can find them:
    data/site.json        lab name, contact, hours, closures, announcements, nav
    data/equipment.json   one entry per instrument -> equipment/<id>/ + QR label
    data/faq.json         FAQ entries
    data/resources.json   documents and links
    src/layout.html       the frame around every page (header, footer)
    src/pages/*.html      one file per top-level page
    src/guides/*.html     one file per guide; new files show up on the guides page
    static/               CSS, JS, images, PDFs - copied unchanged

Standard library only, except segno for the QR labels, which is skipped if it is
not installed.
"""

import argparse
import html
import http.server
import json
import re
import shutil
import socketserver
import sys
import urllib.request
from datetime import date, datetime
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC, DATA, STATIC, DIST = HERE / "src", HERE / "data", HERE / "static", HERE / "dist"

# Sites that answer 403 to any script, so --external cannot tell a dead link from a live one.
BLOCKS_BOTS = ("keysight.com",)

# A guide whose "reviewed" date is older than this gets flagged in the build output.
STALE_AFTER_DAYS = 180

DAYS = [("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"),
        ("thu", "Thursday"), ("fri", "Friday"), ("sat", "Saturday"), ("sun", "Sunday")]

esc = html.escape
todos: list[str] = []      # every TODO rendered, reported at the end of the build
warnings: list[str] = []


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


SITE = load("site.json")
EQUIP = load("equipment.json")


# --------------------------------------------------------------------------
# Small rendering helpers
# --------------------------------------------------------------------------

def is_todo(value) -> bool:
    return isinstance(value, str) and "TODO" in value


def t(value, where="") -> str:
    """Escape a data value. A TODO value is wrapped so draft pages show it."""
    value = "" if value is None else str(value)
    if is_todo(value):
        todos.append(f"{where}: {value}" if where else value)
        return f'<mark class="todo">{esc(value)}</mark>'
    return esc(value)


def link(label, url, where="", cls="") -> str:
    """A link, or just the label if the URL is missing or still a TODO."""
    c = f' class="{cls}"' if cls else ""
    if not url or is_todo(url):
        if url:
            todos.append(f"{where}: {url}")
        return f'<span{c}>{t(label, where)} <mark class="todo">link needed</mark></span>'
    ext = url.startswith("http")
    attrs = ' rel="noopener"' if ext else ""
    return f'<a href="{esc(url)}"{c}{attrs}>{t(label, where)}</a>'


def fmt_time(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def front_matter(text: str):
    """Split '---\\nkey: value\\n---\\nbody' into (dict, body)."""
    meta = {}
    if text.startswith("---"):
        _, head, body = text.split("---", 2)
        for line in head.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta, body.strip()
    return meta, text


# --------------------------------------------------------------------------
# Data blocks: {{@name}} inside a page is replaced by one of these
# --------------------------------------------------------------------------

def block_hours():
    hours = SITE["hours"]
    rows = []
    for key, label in DAYS:
        ranges = hours["weekly"].get(key, [])
        when = ", ".join(f"{fmt_time(a)} – {fmt_time(b)}" for a, b in ranges) or "Closed"
        rows.append(f'<tr data-day="{key}"><th scope="row">{label}</th><td>{when}</td></tr>')
    today = date.today().isoformat()
    closures = [c for c in hours["closures"] if c["date"] >= today]
    closure_html = ""
    if closures:
        items = "".join(
            f'<li data-date="{c["date"]}"><time datetime="{c["date"]}">'
            f'{datetime.fromisoformat(c["date"]).strftime("%a %b %-d")}</time> · {esc(c["label"])}</li>'
            for c in closures)
        closure_html = f'<h3 class="h-small">Upcoming closures</h3><ul class="closures">{items}</ul>'
    unverified = "" if hours.get("verified") else (
        '<p class="note"><mark class="todo">TODO: these hours are placeholders until lab staff confirm them.</mark></p>')
    if not hours.get("verified"):
        todos.append("site.json: hours not verified")
    data = json.dumps({"weekly": hours["weekly"], "closures": hours["closures"], "verified": bool(hours.get("verified"))})
    return (f'<table class="hours"><caption class="sr-only">Weekly lab hours</caption>'
            f'<tbody>{"".join(rows)}</tbody></table>{closure_html}{unverified}'
            f'<script type="application/json" id="hours-data">{data}</script>')


def block_announcements():
    items = []
    for a in sorted(SITE["announcements"], key=lambda a: a["date"], reverse=True):
        d = datetime.fromisoformat(a["date"]).strftime("%b %-d, %Y")
        items.append(f'<li class="news-item"><time datetime="{a["date"]}">{d}</time>'
                     f'<h3>{esc(a["title"])}</h3><p>{esc(a["body"])}</p></li>')
    return f'<ul class="news">{"".join(items)}</ul>' if items else "<p>No announcements.</p>"


def block_equipment_grid():
    cats = EQUIP["categories"]
    buttons = ['<button type="button" class="chip" aria-pressed="true" data-filter="all">All</button>']
    buttons += [f'<button type="button" class="chip" aria-pressed="false" data-filter="{esc(c)}">{esc(c)}</button>'
                for c in cats]
    cards = []
    for it in EQUIP["items"]:
        haystack = " ".join([it["name"], it["model"], it["summary"], *it.get("tags", [])]).lower()
        badge = '<span class="badge badge-warn">Unverified</span>' if it.get("verify") else ""
        img = (f'<img class="card-img" src="{{{{root}}}}static/img/{it["image"]}" alt="" loading="lazy" width="400" height="300">'
               if it.get("image") else "")
        cards.append(
            f'<li class="card equip-card" data-category="{esc(it["category"])}" data-search="{esc(haystack)}">'
            f'{img}<div class="card-body"><p class="eyebrow">{esc(it["category"])}</p>'
            f'<h2 class="card-title"><a class="card-link" href="{{{{root}}}}equipment/{it["id"]}/">{esc(it["name"])}</a></h2>'
            f'<p>{esc(it["summary"])}</p>'
            f'<p class="card-meta">{t(it["model"], it["id"])} {badge}</p></div></li>')
    return (
        '<div class="filter-bar" data-equip-filter hidden>'
        '<label class="sr-only" for="equip-q">Filter equipment</label>'
        '<input id="equip-q" type="search" placeholder="Filter: scope, fuse, solder…" autocomplete="off">'
        f'<div class="chips" role="group" aria-label="Category">{"".join(buttons)}</div></div>'
        f'<ul class="card-grid" id="equip-list">{"".join(cards)}</ul>'
        '<p class="empty" id="equip-empty" hidden>Nothing matches. Try another word, or <a href="{{root}}report/">ask for it to be added</a>.</p>')


def block_equipment_options():
    opts = ['<option value="">Not about one instrument</option>']
    opts += [f'<option value="{it["id"]}">{esc(it["name"])}</option>' for it in EQUIP["items"]]
    return "".join(opts)


def block_faq():
    out = []
    for g in load("faq.json")["groups"]:
        items = []
        for it in g["items"]:
            a = it["a"]
            if is_todo(a):
                a = t(a, "faq")
            items.append(f'<details class="faq"><summary>{esc(it["q"])}</summary><div class="faq-a"><p>{a}</p></div></details>')
        out.append(f'<section class="faq-group"><h2>{esc(g["topic"])}</h2>{"".join(items)}</section>')
    return "".join(out)


def block_resources():
    out = []
    for g in load("resources.json")["groups"]:
        items = []
        for it in g["items"]:
            note = f'<span class="res-note">{t(it["note"], "resources")}</span>' if it.get("note") else ""
            pdf = ' <span class="badge">PDF</span>' if it.get("url", "").lower().endswith(".pdf") else ""
            items.append(f'<li>{link(it["label"], it.get("url", ""), "resources")}{pdf}{note}</li>')
        out.append(f'<section class="res-group"><h2>{esc(g["title"])}</h2><ul class="res-list">{"".join(items)}</ul></section>')
    return "".join(out)


GUIDES = []   # filled by build_guides(), read by block_guides_list()


def block_guides_list():
    cards = []
    for g in GUIDES:
        meta = []
        if g.get("time"):
            meta.append(esc(g["time"]))
        if g.get("level"):
            meta.append(esc(g["level"]))
        cards.append(
            f'<li class="card"><h2 class="card-title"><a class="card-link" href="{{{{root}}}}guides/{g["slug"]}/">{esc(g["title"])}</a></h2>'
            f'<p>{esc(g.get("summary", ""))}</p><p class="card-meta">{" · ".join(meta)}</p></li>')
    return f'<ul class="card-grid">{"".join(cards)}</ul>'


def block_staff():
    cards = []
    for p in SITE["staff"]:
        cards.append(
            f'<li class="person"><p class="person-name">{esc(p["name"])}</p>'
            f'<p class="person-role">{esc(p["role"])} · {esc(p["office"])}</p>'
            f'<p><a href="mailto:{esc(p["email"])}">{esc(p["email"])}</a></p>'
            f'<p><a class="text-link" href="https://teams.microsoft.com/l/chat/0/0?users={esc(p["email"])}" rel="noopener">Message on Teams</a></p></li>')
    note = f'<p class="note">{t(SITE["staff_note"], "site.json staff")}</p>' if SITE.get("staff_note") else ""
    return f'<ul class="people">{"".join(cards)}</ul>{note}'


def block_emergency():
    items = "".join(
        f'<li><span class="phone-label">{esc(e["label"])}</span>'
        f'<a class="phone" href="tel:+1{e["number"].replace("-", "")}">{esc(e["number"])}</a></li>'
        for e in SITE["emergency"])
    return f'<ul class="phones">{items}</ul>'


def block_printer_streams():
    rows = "".join(
        f'<li><span class="stream-name">{esc(s["printer"])}</span>'
        f'<code class="copyable">{esc(s["url"])}</code>'
        f'<button type="button" class="btn btn-small btn-secondary" data-copy="{esc(s["url"])}">Copy</button></li>'
        for s in SITE["printer_streams"])
    return f'<ul class="streams">{rows}</ul>'


BLOCKS = {
    "staff": block_staff,
    "emergency": block_emergency,
    "printer_streams": block_printer_streams,
    "hours": block_hours,
    "announcements": block_announcements,
    "equipment_grid": block_equipment_grid,
    "equipment_options": block_equipment_options,
    "faq": block_faq,
    "resources": block_resources,
    "guides_list": block_guides_list,
}


# --------------------------------------------------------------------------
# Page assembly
# --------------------------------------------------------------------------

LAYOUT = (SRC / "layout.html").read_text(encoding="utf-8")
SEARCH_INDEX = []


def render_nav(active, root):
    out = []
    for n in SITE["nav"]:
        cur = ' aria-current="page"' if n["id"] == active else ""
        cls = ' class="nav-cta"' if n["id"] == "report" else ""
        out.append(f'<li{cls}><a href="{root}{n["href"]}"{cur}>{esc(n["label"])}</a></li>')
    return "".join(out)


def global_head():
    if not SITE.get("use_global_elements"):
        return ""
    return ('<link rel="stylesheet" href="https://global-packages.cdn.northeastern.edu/global-elements/dist/css/index.css">\n'
            '<script src="https://global-packages.cdn.northeastern.edu/global-elements/dist/js/index.umd.js" defer></script>\n'
            '<script src="https://global-packages.cdn.northeastern.edu/kernl-ui/dist/js/index.umd.js" defer></script>')


def write_page(out_rel: str, *, title, body, nav="", description="", reviewed="", section="", index=True, scripts=""):
    """Wrap body in the layout and write it to dist/<out_rel>."""
    depth = out_rel.count("/")
    root = "../" * depth if depth else "./"
    if out_rel == "404.html":
        # Apache serves the 404 page at whatever URL was missing, so relative links would break.
        root = SITE.get("base_path", "/")

    for name, fn in BLOCKS.items():
        token = "{{@" + name + "}}"
        if token in body:
            body = body.replace(token, fn())
    body = re.sub(r"\{\{site:(\w+)\}\}", lambda m: t(SITE[m.group(1)], f"site.json {m.group(1)}"), body)
    body = body.replace("{{root}}", root)

    if reviewed:
        try:
            age = (date.today() - date.fromisoformat(reviewed)).days
            if age > STALE_AFTER_DAYS:
                warnings.append(f"{out_rel}: last reviewed {reviewed} ({age} days ago)")
        except ValueError:
            warnings.append(f"{out_rel}: bad reviewed date {reviewed!r}")

    draft = ""
    if SITE.get("draft"):
        draft = ('<div class="draft-banner" role="note"><div class="wrap"><strong>Draft preview.</strong> '
                 'Highlighted <mark class="todo">TODO</mark> items still need to be checked with lab staff.</div></div>')

    reviewed_html = (f'<p class="page-reviewed">Page last reviewed <time datetime="{reviewed}">'
                     f'{datetime.fromisoformat(reviewed).strftime("%B %-d, %Y")}</time></p>') if reviewed else ""

    values = {
        "title": esc(title),
        "page_title": esc(f"{title} | {SITE['lab_name']}" if title != SITE["lab_name"] else SITE["lab_name"]),
        "description": esc(description or f"{SITE['lab_name']}, {SITE['department']}, Northeastern University."),
        "root": root,
        "nav": render_nav(nav, root),
        "content": body,
        "lab_name": esc(SITE["lab_name"]),
        "department": esc(SITE["department"]),
        "college": esc(SITE["college"]),
        "room": t(SITE["room"], "site.json room"),
        "help_room": esc(SITE["help_room"]),
        "draft_banner": draft,
        "global_head": global_head(),
        "use_global": "true" if SITE.get("use_global_elements") else "false",
        "reviewed": reviewed_html,
        "scripts": scripts,
        "year": str(date.today().year),
        "build_date": date.today().isoformat(),
    }
    page = re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), LAYOUT)
    leftover = re.findall(r"\{\{@?\w+\}\}", page)
    if leftover:
        warnings.append(f"{out_rel}: unreplaced {sorted(set(leftover))}")

    dest = DIST / out_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")

    if index:
        url = out_rel.removesuffix("index.html")
        main = re.search(r'<main[^>]*>(.*)</main>', page, re.S)
        SEARCH_INDEX.append({
            "title": title, "url": url, "section": section or nav or "",
            # list pages mention everything; rank the page that is actually about the thing first
            "rank": 0.4 if url in ("", "equipment/", "make/", "guides/", "faq/", "resources/") else 1,
            "text": strip_tags(main.group(1) if main else body)[:4000],
        })


def build_pages():
    for f in sorted((SRC / "pages").glob("*.html")):
        meta, body = front_matter(f.read_text(encoding="utf-8"))
        todos.extend(f"{f.name}: {m.strip()}" for m in re.findall(r"TODO:[^<\n]*", body))
        out = "index.html" if f.stem == "index" else (
            "404.html" if f.stem == "404" else f"{f.stem.replace('--', '/')}/index.html")
        scripts = "".join(f'<script src="{{{{root}}}}static/js/{s.strip()}" defer></script>'
                          for s in meta.get("scripts", "").split(",") if s.strip())
        # scripts carries {{root}}; resolve it the same way as the body
        depth = out.count("/")
        scripts = scripts.replace("{{root}}", "../" * depth if depth else "./")
        write_page(out, title=meta.get("title", f.stem), body=body, nav=meta.get("nav", f.stem.split("--")[0]),
                   description=meta.get("description", ""), reviewed=meta.get("reviewed", ""),
                   section=meta.get("section", ""), index=f.stem != "404", scripts=scripts)


def build_guides():
    for f in sorted((SRC / "guides").glob("*.html")):
        meta, body = front_matter(f.read_text(encoding="utf-8"))
        meta["slug"] = f.stem
        todos.extend(f"guides/{f.name}: {m.strip()}" for m in re.findall(r"TODO:[^<\n]*", body))
        GUIDES.append(meta)
    GUIDES.sort(key=lambda g: int(g.get("order", 99)))
    for g in GUIDES:
        _, body = front_matter((SRC / "guides" / f"{g['slug']}.html").read_text(encoding="utf-8"))
        crumbs = '<nav class="crumbs" aria-label="Breadcrumb"><a href="{{root}}guides/">Guides</a></nav>'
        head = (f'<div class="page-head"><div class="wrap">{crumbs}<h1>{esc(g["title"])}</h1>'
                f'<p class="lede">{esc(g.get("summary", ""))}</p></div></div>')
        write_page(f"guides/{g['slug']}/index.html", title=g["title"],
                   body=f'{head}<div class="wrap prose-wrap"><article class="prose">{body}</article></div>',
                   nav="guides", description=g.get("summary", ""), reviewed=g.get("reviewed", ""),
                   section="Guide")


def build_equipment_pages():
    for it in EQUIP["items"]:
        where = f"equipment/{it['id']}"
        def lst(items, tag="ul"):
            return f"<{tag}>" + "".join(f"<li>{t(x, where)}</li>" for x in items) + f"</{tag}>"
        parts = []
        if it.get("contents"):
            parts.append(f'<h2>What is in it</h2>{lst(it["contents"])}')
        parts.append(f'<h2>{"Quick start" if not it.get("contents") else "Before you start"}</h2>{lst(it["quick_start"], "ol")}')
        if it.get("mistakes"):
            parts.append(f'<h2>Common mistakes</h2>{lst(it["mistakes"])}')
        if it.get("safety"):
            parts.append(f'<aside class="callout callout-safety" aria-label="Safety"><h2>Safety</h2>{lst(it["safety"])}</aside>')
        if it.get("links"):
            links = "".join(f"<li>{link(l['label'], l['url'], where)}</li>" for l in it["links"])
            parts.append(f'<h2>Manuals and links</h2><ul class="res-list">{links}</ul>')
        badge = ('<p><span class="badge badge-warn">Unverified</span> Model and links still need '
                 'checking against the real bench.</p>') if it.get("verify") else ""
        facts = (f'<dl class="facts"><div><dt>Model</dt><dd>{t(it["model"], where)}</dd></div>'
                 f'<div><dt>Where</dt><dd>{t(it["location"], where)}</dd></div>'
                 f'<div><dt>Category</dt><dd>{esc(it["category"])}</dd></div></dl>')
        photo = (f'<figure class="side-photo"><img src="{{{{root}}}}static/img/{it["image"]}" alt="{esc(it.get("image_alt", ""))}" width="800" height="600"></figure>'
                 if it.get("image") else "")
        side = (f'<aside class="side-card">{photo}{facts}{badge}'
                f'<a class="btn btn-secondary btn-block" href="{{{{root}}}}report/?equipment={it["id"]}">Report a problem with this</a>'
                f'<a class="text-link" href="{{{{root}}}}equipment/labels.html">Print bench QR labels</a></aside>')
        head = (f'<div class="page-head"><div class="wrap"><nav class="crumbs" aria-label="Breadcrumb">'
                f'<a href="{{{{root}}}}equipment/">Equipment</a></nav><h1>{esc(it["name"])}</h1>'
                f'<p class="lede">{esc(it["summary"])}</p></div></div>')
        body = f'{head}<div class="wrap split"><article class="prose">{"".join(parts)}</article>{side}</div>'
        write_page(f"equipment/{it['id']}/index.html", title=it["name"], body=body, nav="equipment",
                   description=it["summary"], section="Equipment")


def build_labels():
    """A printable sheet: one QR per instrument, pointing at its page."""
    try:
        import segno
    except ImportError:
        warnings.append("segno not installed; skipped equipment/labels.html (pip install segno)")
        return
    base = SITE.get("base_url", "").rstrip("/") + "/"
    cells = []
    for it in EQUIP["items"]:
        url = f"{base}equipment/{it['id']}/"
        svg = segno.make(url, error="m").svg_inline(scale=3, border=1, dark="#000")
        cells.append(f'<figure class="label">{svg}<figcaption><strong>{esc(it["name"])}</strong>'
                     f'<span>Scan for quick start and manuals</span><span class="label-url">{esc(url)}</span></figcaption></figure>')
    head = ('<div class="page-head no-print"><div class="wrap"><nav class="crumbs" aria-label="Breadcrumb">'
            '<a href="{{root}}equipment/">Equipment</a></nav><h1>Bench QR labels</h1>'
            '<p class="lede">Print this page and stick one label on each instrument. Scanning opens that '
            'instrument’s page on this site.</p><button type="button" class="btn" data-print>Print labels</button></div></div>')
    body = f'{head}<div class="wrap"><div class="label-sheet">{"".join(cells)}</div></div>'
    write_page("equipment/labels.html", title="Bench QR labels", body=body, nav="equipment", index=False)


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def check_internal_links():
    """Broken internal links. Photos and manuals that were never imported are counted
    separately: that is a missing setup step, not a broken page."""
    bad, missing_assets = [], set()
    asset_dirs = [(DIST / "static" / d).resolve() for d in ("img", "docs")]
    for page in DIST.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for href in re.findall(r'(?:href|src)="([^"#?]*)', text):
            if not href or href.startswith(("http:", "https:", "mailto:", "tel:", "data:", "javascript:")):
                continue
            base = SITE.get("base_path", "/")
            target = (DIST / href[len(base):]) if href.startswith("/") else (page.parent / href)
            target = target.resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                if any(d in target.parents for d in asset_dirs):
                    missing_assets.add(target.name)
                else:
                    bad.append(f"{page.relative_to(DIST)} -> {href}")
    if missing_assets:
        print(f"\n{len(missing_assets)} photos/manuals not imported yet (pages still work without them). "
              "To add them: backup_live_site.py, then import_assets.py.")
    return bad


def check_external_links():
    urls = set()
    for page in DIST.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        text = re.sub(r'<link rel="preconnect"[^>]*>', "", text)    # connection hints, not links
        urls.update(re.findall(r'href="(https?://[^"]+)"', text))
    bad = []
    for url in sorted(urls):
        if any(host in url for host in BLOCKS_BOTS):
            print(f"  ??? skip {url}  (site blocks automated checks; open it in a browser)")
            continue
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 (lab site link check)"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
        except Exception as e:  # noqa: BLE001 - any failure is a finding
            status = getattr(e, "code", None) or type(e).__name__
        mark = "ok " if status == 200 else "BAD"
        print(f"  {mark} {status}  {url}")
        if status != 200:
            bad.append(f"{url} ({status})")
    return bad


# --------------------------------------------------------------------------

def build():
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(STATIC, DIST / "static")
    build_guides()          # before pages, so {{@guides_list}} has data
    build_pages()
    build_equipment_pages()
    build_labels()
    (DIST / "static" / "search-index.json").write_text(
        json.dumps(SEARCH_INDEX, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    if not any((STATIC / "img").glob("*.jpg")):
        warnings.append("no photos in static/img/: run backup_live_site.py, then import_assets.py (see README)")
    n_pages = len(list(DIST.rglob("*.html")))
    print(f"Built {n_pages} pages into {DIST.relative_to(HERE)}/")
    seen, unique_todos = set(), []
    for x in sorted(todos):            # the same value can show on several pages; list it once
        value = x.split(": ", 1)[-1]
        if value not in seen:
            seen.add(value)
            unique_todos.append(x)
    if unique_todos:
        print(f"\n{len(unique_todos)} TODO items still to confirm with lab staff:")
        for x in unique_todos:
            print(f"  - {x}")
    for w in warnings:
        print(f"WARNING: {w}")


def lan_ip():
    """This machine's address on the local network (no packet is actually sent)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def serve(port, host):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((host, port), handler) as httpd:
        print(f"\nServing http://localhost:{port}/  (Ctrl-C to stop)")
        if host == "0.0.0.0" and lan_ip():
            print(f"Others on the same network can open http://{lan_ip()}:{port}/")
        httpd.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true", help="serve dist/ after building")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="use 0.0.0.0 to let other computers on the same network see the preview")
    ap.add_argument("--check", action="store_true", help="check internal links after building")
    ap.add_argument("--external", action="store_true", help="also check external links")
    ap.add_argument("--zip", action="store_true", help="also pack dist/ into lab-site-preview.zip to send to someone")
    args = ap.parse_args()

    build()
    if args.check or args.external:
        bad = check_internal_links()
        print(f"\nInternal links: {'all OK' if not bad else f'{len(bad)} broken'}")
        for b in bad:
            print(f"  BROKEN {b}")
        if args.external:
            print("\nExternal links:")
            bad += check_external_links()
        if bad:
            sys.exit(1)
    if args.zip:
        out = shutil.make_archive(str(HERE / "lab-site-preview"), "zip", root_dir=DIST.parent, base_dir=DIST.name)
        print(f"\nPacked {Path(out).name} ({Path(out).stat().st_size / 1e6:.0f} MB). To view it: unzip, then\n"
              f"  cd dist && python3 -m http.server 8000\nand open http://localhost:8000/")
    if args.serve:
        serve(args.port, args.host)


if __name__ == "__main__":
    main()

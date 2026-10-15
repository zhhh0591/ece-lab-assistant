# ECE Makerspace & Capstone Lab website

> **Public copy.** This is the code and content of the site I built for the ECE
> Makerspace & Capstone Lab. The technicians' names and emails, network
> addresses and room numbers are replaced with placeholders, and the lab's
> photos and manuals are not included, so pages show empty spaces where photos
> go. Everything else runs as described below.

The new lab site, meant to replace the lab's current single-page site.
Plain HTML, CSS and a little JavaScript. The server only serves files; nothing
runs on it.

It is a **draft preview**: it runs on a laptop, not on the lab server yet. The
proposal for the department is kept privately.

## How to view this site

Pick whichever fits. All three need Python 3, which macOS and most Linux machines
already have (check with `python3 --version`).

### 1. Look at it on my laptop, from yours (same network)

On the machine that has this folder:

```bash
python3 build.py --serve --host 0.0.0.0
```

It prints an address like `http://10.110.42.17:8000/`. Anyone on the same network
opens that address in a browser. Press Ctrl-C to stop.

If the page does not load on their machine, the Wi-Fi is keeping devices apart
(campus Wi-Fi often does). Use option 2 instead.

### 2. From a zip I send you

I make the zip with:

```bash
python3 build.py --zip
```

That creates `lab-site-preview.zip` (about 47 MB, mostly instrument manuals).
To open it:

1. Unzip it. You get a folder called `dist`.
2. In a terminal, go into that folder and start a small web server:

   ```bash
   cd dist
   python3 -m http.server 8000
   ```

3. Open http://localhost:8000/ in a browser. Press Ctrl-C in the terminal to stop.

Double-clicking `index.html` does **not** work properly: the links point at folders
like `equipment/`, which only a web server turns into pages.

### 3. Build it yourself from this folder

You need the lab's photos and manuals, which are not in git. They come from the
live site, so this needs the **campus network or the GlobalProtect VPN** once:

```bash
pip install pillow segno
python3 backup_live_site.py     # copies the live site into ../current-site-backup
python3 import_assets.py        # resizes the photos, copies the manuals into static/
python3 build.py --serve        # builds dist/ and serves it
```

Then open http://localhost:8000/. After the first time, only the last command is
needed.

Without the backup, the site still builds and works, just without photos and the
local PDF manuals. The build prints a warning saying so.

## Everyday changes

Almost everything a technician would want to change is in one of four files:

| To change… | Edit | Then |
|---|---|---|
| Hours, closures, announcements, staff, emails | `data/site.json` | build |
| An instrument or machine (add, remove, fix a model) | `data/equipment.json` | build |
| A question and answer | `data/faq.json` | build |
| A manual or outside link | `data/resources.json` | build |

```bash
python3 build.py --check
```

That rebuilds `dist/` and checks every internal link. It also prints every
`TODO` still waiting for an answer, and any guide whose `reviewed:` date is more
than 180 days old.

To see the result before publishing:

```bash
python3 build.py --serve
```

Then open http://localhost:8000/.

## Bigger changes

- **A new guide**: add `src/guides/<name>.html` with a front-matter block (copy
  one of the existing guides). It appears on the Guides page automatically.
- **A new page**: add `src/pages/<name>.html`. Use `<section>--<page>.html` for a
  page inside a section, e.g. `make--pcb.html` becomes `make/pcb/`.
- **Site-wide header and footer**: `src/layout.html`.
- **Look and feel**: `static/css/site.css`. The colors at the top follow the
  Northeastern brand; keep red as an accent.

Inside pages and data files, `{{root}}` means "the top of the site", and
`{{site:poster_email}}` (or any key in `site.json`) inserts that value.

## Photos and manuals

The photos and PDFs belong to the lab and are not kept in git. `backup_live_site.py`
copies the live site (campus network or VPN), and `import_assets.py` turns that
backup into `static/img/` and `static/docs/`: it resizes the photos (the old homepage
loaded 30 MB of them) and copies the manuals. Run both again whenever the live site
gets new files.

## Publishing

1. Set `"draft": false` in `data/site.json` once every TODO is answered. The
   yellow banner and highlights disappear.
2. `python3 build.py --check`
3. Copy the **contents** of `dist/` onto the Apache document root. Keep the old
   `files/` and `images/` folders in place so old links to PDFs keep working.
4. Two lines of Apache config are worth adding (in the site config, or in an
   `.htaccess` file if `AllowOverride` permits):

   ```apache
   ErrorDocument 404 /404.html
   Options -Indexes
   ```

   The first shows the site's own "page not found" page. The second stops the
   server listing the contents of folders.

If the site ever lives under a sub-path instead of the server root, set
`"base_path"` in `site.json` (for example `"/lab/"`) so the 404 page's links
still work.

## What the scripts need

- `build.py`: Python 3.9+, standard library only. `segno` is optional, for the
  bench QR label sheet (`pip install segno`).
- `backup_live_site.py`: standard library only; campus network or VPN.
- `import_assets.py`: Pillow.
- Visitors' browsers: the Northeastern global header and footer load from the
  university CDN. If that cannot be reached, the page shows a plain bar and the
  required university links instead.

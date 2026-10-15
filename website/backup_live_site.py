#!/usr/bin/env python3
"""
Back up the live lab site: the homepage plus every image and document on it.

    python3 backup_live_site.py [output-folder]

Needs the campus network or the GlobalProtect VPN; the server is not reachable
from anywhere else. Files already in the backup are skipped, so running it again
only fetches what is new.

It also reads the server's folder listings for /images/ and /files/, which catch
files that exist on the server but are not linked from the homepage (there were
15 of them on 2026-10-15).

Default output: ../current-site-backup, which import_assets.py reads from.
"""

import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

LIVE = os.environ.get("LIVE_SITE", "http://lab-server.example/")   # the real address is not published
HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "current-site-backup"
SKIP = {"Thumbs.db"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main():
    try:
        index = get(LIVE)
    except OSError as e:
        sys.exit(f"Could not reach {LIVE} ({e}).\nConnect to the campus network or the GlobalProtect VPN and try again.")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_bytes(index)

    paths = set(re.findall(r'(?:src|href)="\.?/?((?:images|files)/[^"]+)"', index.decode("utf-8", "replace")))
    for folder in ("images/", "files/"):
        try:
            listing = get(LIVE + folder).decode("utf-8", "replace")
        except OSError:
            continue                                   # listing turned off: the linked files are enough
        paths |= {folder + name for name in re.findall(r'href="([^"?/][^"]*)"', listing)}

    fetched = skipped = 0
    for rel in sorted(paths):
        name = urllib.parse.unquote(rel)
        if Path(name).name in SKIP:
            continue
        dest = OUT / name
        if dest.exists():
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(get(LIVE + urllib.parse.quote(name)))
        fetched += 1
        print(f"  {dest.stat().st_size // 1024:>7} KB  {name}")
    print(f"Backup in {OUT}: {fetched} new files, {skipped} already there.")


if __name__ == "__main__":
    main()

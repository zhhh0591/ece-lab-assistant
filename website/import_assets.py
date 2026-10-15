#!/usr/bin/env python3
"""
Copy the photos and documents the new site uses out of the backup of the old site,
resizing photos on the way.

    python3 import_assets.py [path/to/current-site-backup]

The old homepage loads about 33 MB of full-size phone photos. Resized to 1600 px
and saved as JPEG, the same photos are a few hundred KB each.

Images that are only pictures of text (3D printer rules, PCB milling rules,
soldering safety, phone numbers, video instructions, the charging-station sign)
are deliberately NOT imported: their text is now real HTML on the site, which
screen readers, search and phones can all use.

static/img and static/docs are gitignored. They are the lab's files, not ours,
and this script recreates them from the backup at any time.
"""

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
BACKUP = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "current-site-backup"
IMG_OUT, DOC_OUT = HERE / "static" / "img", HERE / "static" / "docs"

# old file name -> new file name. The new names say what the photo shows.
PHOTOS = {
    "lab_room.png": "lab-room.jpg",
    "bench_equipment.png": "bench-instruments.jpg",
    "toolbox.png": "bench-toolbox.jpg",
    "IMG_1744.jpg": "shared-toolbox.jpg",
    "IMG_1757.jpg": "prusa-printers.jpg",
    "IMG_1766.jpg": "placement-machine.jpg",
    "IMG_1758.jpg": "reflow-oven.jpg",
    "IMG_1767.jpg": "pcb-mill.jpg",
    "IMG_1772.jpg": "soldering-station.jpg",
    "IMG_1770.jpg": "charging-stations.jpg",
    "IMG_1779.jpg": "poster-plotter.jpg",
    "IMG_1753.jpg": "lab-computer.jpg",
    "IMG_1785.jpg": "lab-printer.jpg",
    "First_Aid_Station.png": "first-aid-station.jpg",
}

DOCS = {
    "scope-manual.pdf": "dso6000-scope-manual.pdf",
    "Agilent 6000 Oscillocope User's Guide.pdf": "dso6000-users-guide.pdf",
    "E3647A_Power_Supply_Manual.pdf": "e3647a-power-supply-manual.pdf",
    "Agilent_33220A_Manual.pdf": "33220a-function-generator-manual.pdf",
    "Man_DMM_fluke45.pdf": "fluke45-manual.pdf",
    "fluke45-intro.pdf": "fluke45-intro.pdf",
    "basics-of-3d-printing.pdf": "basics-of-3d-printing.pdf",
}

MAX_SIDE = 1600

# Close-ups cut from the bench photo, so each instrument page shows its own front panel.
# Boxes are fractions of the photo (left, top, right, bottom), so they survive resizing.
CROPS = {
    "bench_equipment.png": {
        "oscilloscope.jpg":       (0.000, 0.370, 0.506, 0.906),
        "multimeter.jpg":         (0.553, 0.131, 1.000, 0.426),
        "function-generator.jpg": (0.553, 0.420, 0.963, 0.672),
        "power-supply.jpg":       (0.616, 0.655, 0.956, 0.988),
    }
}


def main():
    if not BACKUP.exists():
        sys.exit(f"No backup at {BACKUP}. Back up the old site first (see lab-web/site/README.md).")
    IMG_OUT.mkdir(parents=True, exist_ok=True)
    DOC_OUT.mkdir(parents=True, exist_ok=True)
    before = after = 0
    for old, new in PHOTOS.items():
        src = BACKUP / "images" / old
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        dest = IMG_OUT / new
        im.save(dest, "JPEG", quality=80, optimize=True, progressive=True)
        before += src.stat().st_size
        after += dest.stat().st_size
        print(f"  {old:28} -> img/{new:24} {src.stat().st_size // 1024:>6} KB -> {dest.stat().st_size // 1024:>4} KB  {im.size[0]}x{im.size[1]}")
    for old, crops in CROPS.items():
        im = ImageOps.exif_transpose(Image.open(BACKUP / "images" / old)).convert("RGB")
        W, H = im.size
        for new, (l, t, r, b) in crops.items():
            # grow the box to 4:3 around its center, so cards and pages never cut the instrument off
            cx, cy, w, h = (l + r) / 2 * W, (t + b) / 2 * H, (r - l) * W, (b - t) * H
            if w / h > 4 / 3: h = w * 3 / 4
            else: w = h * 4 / 3
            x0 = min(max(cx - w / 2, 0), W - w); y0 = min(max(cy - h / 2, 0), H - h)
            part = im.crop((round(x0), round(y0), round(x0 + w), round(y0 + h)))
            part.thumbnail((1200, 1200))
            part.save(IMG_OUT / new, "JPEG", quality=82, optimize=True, progressive=True)
            print(f"  {old:28} -> img/{new:24} crop {part.size[0]}x{part.size[1]}")
    for old, new in DOCS.items():
        shutil.copy2(BACKUP / "files" / old, DOC_OUT / new)
        print(f"  {old:28} -> docs/{new}")
    print(f"\nPhotos: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

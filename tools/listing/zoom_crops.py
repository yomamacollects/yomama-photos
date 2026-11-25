"""Make enlarged crops of the small print on each card scan, so nothing on the
collector line is read from a shrunken full-card view.

  python tools/listing/zoom_crops.py OUT_DIR IMAGE_OR_URL [...]
  python tools/listing/zoom_crops.py OUT_DIR --manifest inbox/<batch>.json   (fronts only)

For each image it writes:
  <name>_top.jpg      top 15%  (name, HP, stage, evolves-from, 1st Ed stamp on some sets)
  <name>_mid.jpg      42-62% height, right 60% (EX-era-to-today "Illus." line under the art,
                      WOTC 1st Edition stamp / shadow line at the art frame's lower left)
  <name>_bottom.jpg   bottom 16%  (WOTC Illus. line, copyright, set code, number, rarity, reg. mark)
  <name>_corner.jpg   bottom-right corner at 3x (rarity symbol, set symbol, promo code)
Crops are 2x (corner 3x) of the scan's own pixels. Landscape scans are cropped
the same way after turning them upright, so check the full card too.
"""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

REGIONS = {
    "top": ((0.0, 0.0, 1.0, 0.15), 2),
    "mid": ((0.40, 0.42, 1.0, 0.62), 2),
    "bottom": ((0.0, 0.84, 1.0, 1.0), 2),
    "corner": ((0.62, 0.86, 1.0, 1.0), 3),
}


def load(src: str) -> Image.Image:
    if src.startswith("http"):
        import requests

        r = requests.get(src, timeout=60)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGB")
    return Image.open(src).convert("RGB")


def crops(src: str, out: Path) -> list[Path]:
    im = load(src)
    if im.width > im.height:
        im = im.rotate(90, expand=True)
    stem = Path(src.split("?")[0]).stem
    paths = []
    for name, ((x0, y0, x1, y1), scale) in REGIONS.items():
        box = (int(x0 * im.width), int(y0 * im.height), int(x1 * im.width), int(y1 * im.height))
        c = im.crop(box)
        c = c.resize((c.width * scale, c.height * scale), Image.LANCZOS)
        if max(c.size) > 3000:
            c.thumbnail((3000, 3000), Image.LANCZOS)
        p = out / f"{stem}_{name}.jpg"
        c.save(p, quality=92)
        paths.append(p)
    return paths


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    srcs = argv[1:]
    if srcs[0] == "--manifest":
        m = json.loads(Path(srcs[1]).read_text(encoding="utf-8"))
        srcs = [it["photos"][0] for it in m["items"]]
    for s in srcs:
        for p in crops(s, out):
            print(p)


if __name__ == "__main__":
    main(sys.argv[1:])

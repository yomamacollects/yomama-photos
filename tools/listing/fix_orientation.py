"""Turn photos the right way up before they're listed.

The scanner crops and straightens, but it can't tell when a card went
through upside down or sideways. While inspecting a batch, Claude checks every
front; for any card that's the wrong way up, run this on BOTH sides (a card
fed upside down is upside down on the back too, unless the back says otherwise),
then commit the files back to main under the same names.

  python tools/listing/fix_orientation.py 180 2026-11-21/YMC-20261121-05_1.jpg 2026-11-21/YMC-20261121-05_2.jpg
  (angle: 90 = turn left, 180 = upside down, 270 = turn right)
"""

import sys

from PIL import Image


def main(argv):
    if len(argv) < 2 or argv[0] not in {"90", "180", "270"}:
        raise SystemExit(__doc__)
    ang = int(argv[0])
    for p in argv[1:]:
        im = Image.open(p)
        dpi = im.info.get("dpi", (600, 600))
        im.convert("RGB").rotate(ang, expand=True).save(p, "JPEG", quality=92, optimize=True, dpi=dpi, subsampling=0)
        print(f"rotated {ang}: {p}")


if __name__ == "__main__":
    main(sys.argv[1:])

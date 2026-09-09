"""Isolate-check one font for ThorVG load + raster safety.

Runs inside a subprocess spawned by ``nanoframes fonts verify``: some fonts
segfault this ThorVG build at engine teardown (e.g. AppleGothic), and a crash
here surfaces as exit code 139 in the parent instead of taking the CLI down.
Prints one line ``solid N`` (N = pixels brighter than 180 on the red channel)
when the font loaded and the test text rasterized.

Usage: python -m nanoframes.scripts.verify_font <font.ttf|.otf> <family-name>
"""

from __future__ import annotations

import sys

from nanoframes.fonts import DEFAULT_FONT_CANDIDATES
from nanoframes.render import render_svg

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="70">'
    '<rect width="160" height="70" fill="#fff"/>'
    '<text x="4" y="50" font-family="{family}" font-size="30" fill="#000">A中</text></svg>'
)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    path, family = argv[1], argv[2]
    img = render_svg(_SVG.format(family=family), 160, 70, threads=1,
                     font_paths=DEFAULT_FONT_CANDIDATES + (path,))
    solid = sum(1 for px in img.getdata(band=0) if px > 180)
    print("solid", solid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

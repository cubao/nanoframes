"""Measure text glyph geometry exactly as the renderer will rasterize it.

nanoframes draws text by letting ThorVG's SVG loader resolve ``<text>`` —
complete with font-family matching, shaping, letter-spacing and fallback. To
make auto-sizing (background chips, wrapped/broken lines, text-along-curve)
*consistent with the final render*, we measure the same way: rasterize a tiny
SVG holding one isolated ``<text>`` and read back its ink bounding box from the
pixels. Because it is literally the same code path, the reported box is exact —
there is no separate metric/font engine to drift from the renderer.

Cost
----
Each measurement is a ~sub-millisecond ThorVG raster of a tiny isolated SVG.
Results are cached by ``(family, weight, size_px, text)`` so the steady-state
cost of an auto-sized composition is one measurement per distinct string.
"""

from __future__ import annotations

from dataclasses import dataclass

from nanoframes.fonts import DEFAULT_FONT_CANDIDATES
from nanoframes.render import render_svg

_MARK_BASELINE = 256  # baseline y we place glyphs on inside the measurement SVG
_MARK_W = 1024
_MARK_H = 512


@dataclass(frozen=True)
class InkMetrics:
    """Glyph ink box, resolved against the ``<text>`` baseline anchor (x, y).

    ``left_dx`` / ``right_dx`` are horizontal offsets from the text anchor ``x``
    to the ink left/right edges. ``top`` is the ink top offset from the baseline
    (negative, since glyphs sit above it); ``bottom`` is the ink bottom offset
    (positive for descenders). ``w``/``h`` are ink width/height.
    """

    left_dx: float
    right_dx: float
    top: float
    bottom: float
    w: float
    h: float

    @property
    def center_dx(self) -> float:
        return (self.left_dx + self.right_dx) / 2.0


class Measurer:
    """Cached, renderer-exact text measurement.

    ``Measurer`` registers the same candidate fonts the render pass uses, so
    font-family resolution inside each measurement SVG matches the real frame.
    """

    def __init__(self, extra_font_paths: list[str] | None = None, cache: bool = True):
        self._fonts: list[str] = list(DEFAULT_FONT_CANDIDATES) + list(extra_font_paths or [])
        self._cache: dict[tuple, InkMetrics] = {} if cache else None

    # -- public ---------------------------------------------------------------
    def ink(self, text: str, family: str, weight: str, size_px: float,
            letter_spacing: float = 0.0) -> InkMetrics:
        key = (text, family, weight, round(size_px, 4), round(letter_spacing, 4))
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        box = self._measure(text, family, weight, size_px, letter_spacing)
        if self._cache is not None:
            self._cache[key] = box
        return box

    # -- machinery ------------------------------------------------------------
    def _measure(self, text: str, family: str, weight: str, size_px: float,
                 letter_spacing: float) -> InkMetrics:
        import numpy as np  # heavy, lazy

        if letter_spacing:
            ls = f' letter-spacing="{letter_spacing:g}px"'
        else:
            ls = ""
        svg = (
            "<svg xmlns=\"http://www.w3.org/2000/svg\" "
            f'width="{_MARK_W}" height="{_MARK_H}">'
            f'<rect width="{_MARK_W}" height="{_MARK_H}" fill="#ffffff"/>'
            f'<text x="0" y="{_MARK_BASELINE}" font-family="{family}" '
            f'font-weight="{weight}" font-size="{size_px:g}" fill="#000000"{ls}>'
            f"{text}</text></svg>"
        )

        img = render_svg(svg, _MARK_W, _MARK_H, threads=1, font_paths=self._fonts)
        arr = np.array(img)

        gray = arr[:, :, 0] if arr.ndim == 3 and arr.shape[2] >= 3 else arr
        ys, xs = np.where(gray < 128)
        if len(xs) == 0:
            return InkMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        return InkMetrics(
            left_dx=float(x0),
            right_dx=float(x1),
            top=float(y0 - _MARK_BASELINE),
            bottom=float(y1 - _MARK_BASELINE),
            w=float(x1 - x0 + 1),
            h=float(y1 - y0 + 1),
        )
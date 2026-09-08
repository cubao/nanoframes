"""Rasterize a per-frame SVG through ThorVG into a Pillow image.

The ThorVG `Picture` loader needs the SVG as a file (it resolves relative
resource URLs against the file path), so bake output is written to a temp
`.svg` file before rendering.
"""

from __future__ import annotations

import os
import tempfile

from nanoframes import bake
from nanoframes.cache import FrameCache
from nanoframes.parse import Document


class RenderError(RuntimeError):
    """Raised when ThorVG fails to load or rasterize a frame."""


# Candidate default fonts so text renders even when a composition declares no
# font file. ThorVG only rasterizes <text> after a font has been loaded (cached
# globally by path), so we register a few common faces on engine setup.
DEFAULT_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    r"/System/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

def _ensure_font(engine) -> None:
    """Register default fonts so SVG <text> resolves to a real face.

    Called every engine: ThorVG tears down its global font cache when an engine
    is terminated, so a fresh engine needs the fonts registered again. Loading is
    cheap because ThorVG caches font data by path. (See ``nanoframes.fonts`` for
    CJK font discovery; we deliberately do NOT auto-register arbitrary discovered
    faces here because some fonts crash this ThorVG build at teardown.)
    """
    import os

    import thorvg_python as tvg  # noqa: PLC0415

    dummy = tvg.Text(engine)  # font_load lives on Text; global cache keyed by path
    for path in DEFAULT_FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            dummy.font_load(path)
        except Exception:
            continue


def _write_temp(svg_str: str) -> str:
    fd, path = tempfile.mkstemp(prefix="nanoframes_", suffix=".svg")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(svg_str)
    except Exception:
        os.unlink(path)
        raise
    return path


def render_svg(svg_str: str, width: int, height: int, threads: int = 4) -> "object":
    """Return a Pillow Image for a standalone SVG string."""
    import thorvg_python as tvg  # heavy import, keep it lazy

    path = _write_temp(svg_str)
    engine = tvg.Engine(threads=threads)
    _ensure_font(engine)
    canvas = tvg.SwCanvas(engine)
    try:
        canvas.set_target(width, height)
        pic = tvg.Picture(engine)
        result = pic.load(path)
        if result != 0:
            raise RenderError(f"ThorVG failed to load SVG (result={result})")
        pic.set_size(width, height)
        canvas.add(pic)
        canvas.update()
        canvas.draw(True)
        canvas.sync()
        return canvas.get_pillow()
    finally:
        canvas.destroy()
        engine.term()
        try:
            os.unlink(path)
        except OSError:
            pass


_MEASURER = None


def _measurer():
    """A process-wide renderer-exact Measurer (lazily created, reused across frames)."""
    global _MEASURER
    if _MEASURER is None:
        from nanoframes.measure import Measurer
        _MEASURER = Measurer()
    return _MEASURER


def render_frame(doc: Document, t: float, out_path: str | None = None, threads: int = 4,
                 cache: "FrameCache | None" = None) -> "object":
    """Render one frame of a composition at time ``t``.

    Returns a Pillow Image; if ``out_path`` is given the PNG is also saved. When
    ``cache`` is provided, an armed frame is served from the cache (skipping
    ThorVG) and misses are written back.
    """
    if cache is not None:
        hit = cache.get(doc.identity, t, doc.composition.width, doc.composition.height)
        if hit is not None:
            if out_path:
                os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
                hit.save(out_path)
            return hit
    svg = bake.bake_svg(doc, t, measurer=_measurer())
    img = render_svg(svg, doc.composition.width, doc.composition.height, threads=threads)
    if cache is not None:
        cache.put(doc.identity, t, img)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        img.save(out_path)
    return img
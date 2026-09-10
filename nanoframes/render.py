"""Rasterize a per-frame SVG through ThorVG into a Pillow image.

The ThorVG `Picture` loader needs the SVG as a file (it resolves relative
resource URLs against the file path), so bake output is written to a temp
``.svg`` file before rendering.

``render_svg`` is the one place that owns the ThorVG engine lifecycle —
engine creation, default font registration, temp-file write, canvas draw and
clean teardown (canvas destroy before engine term; some fonts crash this build
at teardown, which is why ``nanoframes fonts verify`` runs load checks in an
isolated subprocess). Text measurement (``nanoframes.measure``) rasterizes the
same way with the same fonts, so metrics and final frames cannot drift.
"""

from __future__ import annotations

import os
import sys
import tempfile

from nanoframes import bake
from nanoframes.cache import FrameCache
from nanoframes.fonts import DEFAULT_FONT_CANDIDATES
from nanoframes.parse import Document
from nanoframes.scale import draft_size, prescale_images


class RenderError(RuntimeError):
    """Raised when ThorVG fails to load or rasterize a frame."""


def _write_temp(svg_str: str) -> str:
    fd, path = tempfile.mkstemp(prefix="nanoframes_", suffix=".svg")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(svg_str)
    except Exception:
        os.unlink(path)
        raise
    return path


def render_svg(svg_str: str, width: int, height: int, threads: int = 4,
               font_paths: tuple[str, ...] | list[str] | None = None) -> "object":
    """Return a Pillow Image for a standalone SVG string.

    ``font_paths`` defaults to ``nanoframes.fonts.DEFAULT_FONT_CANDIDATES``;
    measurement and font verification pass their own (superset) lists. Fonts
    are registered on every engine: ThorVG tears down its global font cache
    when an engine is terminated, so a fresh engine needs them again (loading
    is cheap because ThorVG caches font data by path).
    """
    import thorvg_python as tvg  # heavy import, keep it lazy

    if font_paths is None:
        font_paths = DEFAULT_FONT_CANDIDATES
    path = _write_temp(svg_str)
    engine = tvg.Engine(threads=threads)
    canvas = tvg.SwCanvas(engine)
    try:
        holder = tvg.Text(engine)  # font_load lives on Text; cache keyed by path
        for fpath in font_paths:
            if not os.path.exists(fpath):
                continue
            try:
                holder.font_load(fpath)
            except Exception:
                continue
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


def measurer():
    """A process-wide renderer-exact Measurer (lazily created, reused everywhere).

    Shared with lint and `nanoframes debug` so a composition's text is measured
    once per distinct string across checking, diagnosing and rendering.
    """
    global _MEASURER
    if _MEASURER is None:
        from nanoframes.measure import Measurer
        _MEASURER = Measurer()
    return _MEASURER


def frame_is_blank(img) -> bool:
    """True when a rendered frame has no opaque pixel at all."""
    if img.mode not in ("RGBA", "LA"):
        return False
    return img.getchannel("A").getextrema()[1] == 0


def blank_frame_warning(img, t: float) -> str | None:
    """Print (and return) a one-line diagnosis for a frame that drew nothing.

    A fully transparent frame is the failure mode with no other symptom: no
    error, no exception, a valid PNG. The usual causes are every element being
    outside its clip window at this time, or geometry that lands off-canvas —
    both of which ``nanoframes debug`` answers element by element.
    """
    if not frame_is_blank(img):
        return None
    message = (f"nanoframes: frame t={t:g} rendered fully transparent (no pixel drawn)."
               f" Likely: every element is outside its data-start/data-duration window here,"
               f" or its geometry leaves the canvas — run `nanoframes debug <comp> --t {t:g}`.")
    print(message, file=sys.stderr)
    return message


def render_frame(doc: Document, t: float, out_path: str | None = None, threads: int = 4,
                 cache: "FrameCache | None" = None,
                 text_handler=None, scale: float = 1.0,
                 warn_blank: bool = True) -> "object":
    """Render one frame of a composition at time ``t``.

    Returns a Pillow Image; if ``out_path`` is given the PNG is also saved. When
    ``cache`` is provided, an armed frame is served from the cache (skipping
    ThorVG) and misses are written back.

    ``text_handler`` (see ``nanoframes.rastertext``) rasterizes ``<text
    data-raster>`` nodes; the cache is bypassed whenever one is supplied,
    because its (source, t) key knows nothing about the handler.

    ``scale`` below 1.0 renders a draft frame at that fraction of the canvas
    size (see ``nanoframes.scale``): the canvas and each embedded ``<image>``
    shrink together. The composition is not modified on disk — the in-memory
    tree's image sources are swapped, and restored on the next ``scale >= 1``
    render of the same ``doc``.

    ``warn_blank`` prints a stderr diagnosis for a fully transparent frame;
    batch and video renders turn it off and report the count once instead.
    """
    if text_handler is not None:
        cache = None
    width, height = draft_size(doc.composition.width, doc.composition.height, scale)
    if cache is not None:
        hit = cache.get(doc.identity, t, width, height)
        if hit is not None:
            if out_path:
                os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
                hit.save(out_path)
            return hit
    prescale_images(doc, scale)
    svg = bake.bake_svg(doc, t, measurer=measurer(), text_handler=text_handler)
    img = render_svg(svg, width, height, threads=threads)
    if warn_blank:
        blank_frame_warning(img, t)
    if cache is not None:
        cache.put(doc.identity, t, img)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        img.save(out_path)
    return img

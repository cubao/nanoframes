"""Review images: a contact sheet of the motion, and a blend of it.

Both answer the one question a per-frame report cannot — *what does the motion
look like* — in a picture an agent can read without watching the clip. They are
built from the same frames a render would write (same bake, same fonts, same
rasterizer), so nothing here can show a picture the clip does not contain.

`strip` lays evenly spaced frames out in a labelled sheet: the shape of the
movement at a glance, and where the beats fall. `onion` blends a range into one
image with later frames weighted stronger, which is how a path and an easing
curve are read off a moving element: a linear move leaves evenly spaced ghosts,
an eased one bunches them at the ends.

Both are pure functions of the frames they sample and of nothing else — no
randomness, no clock, no font substitution beyond the bundled face — so the same
composition yields the same PNG on any machine that can render it at all.
"""

from __future__ import annotations

import os

from nanoframes.timeline import frame_times

#: Tile width in the contact sheet; fframes' `strip` uses the same default and
#: it is a good one: four tiles fit a 1920-wide sheet, and a 1080p frame is
#: still readable at a quarter size.
DEFAULT_TILE_WIDTH = 480
DEFAULT_COLUMNS = 4
_GAP = 2
_LABEL_HEIGHT = 26


def sample_frames(comp, count: int, first: float | None = None,
                  last: float | None = None) -> list:
    """``count`` frame times spread evenly across a range of the clip.

    Evenly spaced *frames*, not seconds: the sheet is meant to be read as the
    clip plays, and sampling by time would crowd the frames near a short range
    and thin out a long one. ``first``/``last`` are seconds and default to the
    whole clip; the last frame is included, so a 2-sample sheet is its two ends.
    """
    times = frame_times(comp)
    if not times:
        return []
    lo = 0.0 if first is None else first
    hi = comp.duration if last is None else last
    window = [t for t in times if lo - 1e-9 <= t <= hi + 1e-9] or times
    count = max(1, min(count, len(window)))
    if count == 1:
        return [window[0]]
    step = (len(window) - 1) / (count - 1)
    return [window[round(i * step)] for i in range(count)]


def _label_font(size: int = 16):
    """The bundled face for labels, or Pillow's built-in font as a fallback.

    Label text is not part of the composition, so it is deliberately not run
    through ThorVG: this must work on a host where rendering is what is being
    debugged.
    """
    from PIL import ImageFont

    from nanoframes.fonts import font_candidates

    for path in font_candidates():
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def strip_image(frames: list, tile_width: int = DEFAULT_TILE_WIDTH,
                columns: int = DEFAULT_COLUMNS):
    """A labelled contact sheet: one tile per ``(label, image)`` in ``frames``."""
    from PIL import Image, ImageDraw

    if not frames:
        raise ValueError("strip_image needs at least one frame")
    columns = max(1, columns)
    first = frames[0][1]
    scale = tile_width / first.width
    tile_h = max(1, round(first.height * scale))
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_h + _LABEL_HEIGHT)),
                      (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    font = _label_font()
    for index, (label, img) in enumerate(frames):
        column, row = index % columns, index // columns
        x = column * tile_width
        y = row * (tile_h + _LABEL_HEIGHT)
        draw.text((x + 6, y + 5), label, fill=(205, 205, 205), font=font)
        sheet.paste(img.convert("RGB").resize((tile_width, tile_h), Image.LANCZOS),
                    (x, y + _LABEL_HEIGHT))
    return sheet


def onion_image(frames: list, strength: float = 1.0):
    """Blend frames into one image, later frames weighted stronger.

    A frame's weight comes from its **position in the range**, not its index in
    the sample: the first is 1 and the last is ``1 + strength``, whatever
    ``--count`` was. Sampling the same range more finely therefore adds ghosts
    between the old ones instead of restyling the blend — ``-n`` is a resolution
    knob, and a blend of a range always reads the same way. ``strength`` 0 makes
    every frame equal. Weights are normalized, so the result is a convex
    combination and never clips.
    """
    import numpy as np

    if not frames:
        raise ValueError("onion_image needs at least one frame")
    count = len(frames)
    positions = [0.0] if count == 1 else [i / (count - 1) for i in range(count)]
    weights = np.array([1.0 + strength * p for p in positions])
    weights /= weights.sum()
    accumulator = None
    for weight, (_label, img) in zip(weights, frames):
        layer = np.asarray(img.convert("RGBA"), dtype=float) * weight
        accumulator = layer if accumulator is None else accumulator + layer
    from PIL import Image

    return Image.fromarray(np.clip(accumulator, 0, 255).astype("uint8"), "RGBA")

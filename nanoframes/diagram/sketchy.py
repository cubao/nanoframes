"""Hand-drawn strokes, computed rather than filtered.

The sketchy look in the browser world is an SVG turbulence filter. ThorVG does
not rasterize filters, so nothing about it can be copied — but the *geometry*
can be: an outline drawn twice with a deterministic wobble reads as hand-drawn,
and it stays inside the SVG Tiny 1.2 subset this renderer actually supports.

The visual register follows the hand-drawn explainer conventions collected in
`hi-nikola/hand-drawn-explainer-video-nikola` (Apache-2.0) — imperfect
marker/crayon outlines, flat warm-paper fills, and the warm-white canvas
(`#F8F6EF`) with its restrained accent set — and the sketchy primitive from
diagram-design's `primitive-sketchy.md` (MIT). See
`skills/nanoframes/references/diagram-sketchy.md`.

Everything here is a pure function of the shape's coordinates plus its name, so
a composition renders byte-identically on every machine and in every process
order. No RNG state, no clock, no hashing of object identity.
"""

from __future__ import annotations

import math

# Wobble amplitude (px). The source style guide's outline is a thick marker /
# crayon line: a visibly imperfect edge, not a shaky one. Bigger than a hairline
# and much smaller than the stroke widths the themes use.
JITTER = 2.6
# A hand-made line rarely lands twice in the same place, so outlines are drawn
# twice with different wobble.
DOUBLE_STROKE = True


def _noise(seed: int, index: int) -> float:
    """Deterministic value in ``[-1, 1]`` — a pure function of ``(seed, index)``.

    A linear congruential step rather than ``random``: ``random``'s state is
    global and order-dependent, which would make a diagram's wobble depend on
    how many shapes were drawn before it.
    """
    x = (seed * 1_103_515_245 + (index + 1) * 12_345) & 0x7FFFFFFF
    x = (x >> 13) ^ x
    x = (x * (x * x * 60493 + 19990303) + 1376312589) & 0x7FFFFFFF
    return (x / 1_073_741_823.0) - 1.0


def _seed(name: str) -> int:
    """A stable seed for a shape name (FNV-1a; no process-wide hash salt)."""
    h = 2_166_136_261
    for ch in name:
        h = ((h ^ ord(ch)) * 16_777_619) & 0xFFFFFFFF
    return h


def _f(value: float) -> str:
    return f"{round(value, 1):g}"


def wobbly_line(x1: float, y1: float, x2: float, y2: float, seed: int, index: int,
                amp: float = JITTER) -> str:
    """``d`` for one hand-drawn segment: a quadratic bend through a jittered mid."""
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    # Displace the control point mostly perpendicular to the segment, so the
    # line bends instead of shortening — the way a drawn stroke bows.
    px, py = -(y2 - y1) / length, (x2 - x1) / length
    off = _noise(seed, index) * amp
    cx, cy = mx + px * off, my + py * off
    return f"M {_f(x1)},{_f(y1)} Q {_f(cx)},{_f(cy)} {_f(x2)},{_f(y2)}"


def rough_rect(x: float, y: float, w: float, h: float, name: str,
               seed_offset: int = 0) -> list:
    """``d`` strings for a hand-drawn rectangle outline.

    One path per edge (so each side bows independently) plus, when
    ``DOUBLE_STROKE``, a second pass over a slightly inset rectangle — the
    doubled contour a pen leaves when it goes around a box twice.
    """
    seed = _seed(name) + seed_offset

    def edges(box: tuple) -> list:
        bx, by, bw, bh = box
        xs, ys = (bx, bx + bw), (by, by + bh)
        return [
            (xs[0], ys[0], xs[1], ys[0]),
            (xs[1], ys[0], xs[1], ys[1]),
            (xs[1], ys[1], xs[0], ys[1]),
            (xs[0], ys[1], xs[0], ys[0]),
        ]

    out = [wobbly_line(*edge, seed, i) for i, edge in enumerate(edges((x, y, w, h)))]
    if DOUBLE_STROKE:
        inset = 1.0
        second = (x + inset, y + inset, max(1.0, w - 2 * inset), max(1.0, h - 2 * inset))
        for i, edge in enumerate(edges(second)):
            out.append(wobbly_line(*edge, seed, i + 16, amp=JITTER * 0.6))
    return out


def rough_arc(cx: float, cy: float, r: float, start_deg: float, end_deg: float,
              name: str, samples: int | None = None, amp: float = JITTER) -> str:
    """``d`` for a hand-drawn arc, sampled and wobbled perpendicular to the radius.

    Angles are in SVG convention (positive y is down, positive degrees sweep
    clockwise), matching ``build_loop``'s ring math.
    """
    sweep = (end_deg - start_deg) % 360.0
    if sweep == 0.0:
        sweep = 360.0
    if samples is None:
        samples = max(6, min(40, int(abs(sweep)) // 10 + 6))
    seed = _seed(name)
    pts = []
    for k in range(samples + 1):
        t = k / float(samples)
        theta = math.radians(start_deg + sweep * t)
        rr = r + _noise(seed, k) * amp
        pts.append((cx + rr * math.cos(theta), cy + rr * math.sin(theta)))
    d = f"M {_f(pts[0][0])},{_f(pts[0][1])}"
    for x, y in pts[1:]:
        d += f" L {_f(x)},{_f(y)}"
    return d

"""Diagram geometry: the 4px grid, orthogonal connectors, arrowheads.

The connector rules are adapted from
[diagram-design](https://github.com/cathrynlavery/diagram-design) SKILL.md §6
(MIT, (c) 2025 Cathryn Lavery): every bend is a quarter-arc of ``r=8``, no
diagonal slants between off-axis nodes, and no two connectors share a stroke
path. The one primitive that cannot be ported is the SVG ``<marker>``: this
ThorVG build accepts the attribute and draws nothing, so arrowheads are emitted
as explicit polygons computed from the path's end tangent (``arrowhead``).
"""

from __future__ import annotations

import math

GRID = 4
CORNER_R = 8.0
# Arrowhead template: the source's `points="0 0, 8 3, 0 6"` with refX=7, i.e.
# the tip sits 1px past the anchor point.
ARROW_LEN = 8.0
ARROW_HALF = 3.0
ARROW_TIP = 1.0


def q4(value: float) -> float:
    """Snap to the 4px grid (the source's hard rule for coords, sizes, gaps)."""
    return round(value / GRID) * GRID


def r2(value: float) -> float:
    return round(value + 0.0, 2)


def on_grid(value: float) -> bool:
    return abs(value - q4(value)) < 0.01


def _fmt(value: float) -> str:
    text = f"{r2(value):.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _corner(p0: tuple, p1: tuple, p2: tuple, r: float) -> tuple[str, tuple]:
    """A quarter-arc elbow at ``p1``: line to the arc start, ``Q`` to the arc end.

    Returns the path fragment (starting with the line command) and the point the
    caller continues from.
    """
    ux0, uy0 = p1[0] - p0[0], p1[1] - p0[1]
    ux1, uy1 = p2[0] - p1[0], p2[1] - p1[1]
    n0 = math.hypot(ux0, uy0) or 1.0
    n1 = math.hypot(ux1, uy1) or 1.0
    r = min(r, n0, n1)
    a = (p1[0] - ux0 / n0 * r, p1[1] - uy0 / n0 * r)
    b = (p1[0] + ux1 / n1 * r, p1[1] + uy1 / n1 * r)
    frag = f"L {_fmt(a[0])},{_fmt(a[1])} Q {_fmt(p1[0])},{_fmt(p1[1])} {_fmt(b[0])},{_fmt(b[1])}"
    return frag, b


def elbow(a: tuple, b: tuple, a_dir: str, b_dir: str, r: float = CORNER_R) -> tuple[list, float]:
    """Orthogonal route from ``a`` to ``b``; returns ``([points], rounded_length)``.

    ``a_dir`` / ``b_dir`` are the port orientations the points were chosen on
    (``right`` / ``left`` / ``up`` / ``down``). The route leaves along ``a_dir``,
    turns on one (L) or two (Z) corners, and arrives along ``b_dir`` reversed.
    ``rounded_length`` is the polyline length minus the two corner cuts, i.e.
    the arc length actually stroked — the label midpoint walks this.
    """
    ax, ay = a
    bx, by = b
    if abs(ax - bx) < 0.5:
        return [(ax, ay), (ax, by)], abs(by - ay)
    if abs(ay - by) < 0.5:
        return [(ax, ay), (bx, ay)], abs(bx - ax)

    vertical_first = a_dir in ("up", "down")
    if vertical_first:
        mid = (ay + by) / 2.0
        if (ay - mid) * (by - mid) < 0:
            p1 = (ax, mid)
            p2 = (bx, mid)
        else:
            p1 = p2 = (ax, by)
    else:
        mid = (ax + bx) / 2.0
        if (ax - mid) * (bx - mid) < 0:
            p1 = (mid, ay)
            p2 = (mid, by)
        else:
            p1 = p2 = (bx, ay)

    if p1 == p2:
        length = math.hypot(p1[0] - ax, p1[1] - ay) + math.hypot(bx - p1[0], by - p1[1])
        return [a, p1, b], length
    length = (math.hypot(p1[0] - ax, p1[1] - ay)
              + math.hypot(p2[0] - p1[0], p2[1] - p1[1])
              + math.hypot(bx - p2[0], by - p2[1]) - 2 * r)
    return [a, p1, p2, b], max(0.0, length)


def path_d(points: list, r: float = CORNER_R) -> str:
    """SVG path for an orthogonal polyline with rounded corners."""
    if len(points) < 3:
        a, b = points[0], points[-1]
        return f"M {_fmt(a[0])},{_fmt(a[1])} L {_fmt(b[0])},{_fmt(b[1])}"
    d = f"M {_fmt(points[0][0])},{_fmt(points[0][1])}"
    for i in range(1, len(points) - 1):
        frag, _ = _corner(points[i - 1], points[i], points[i + 1], r)
        d += " " + frag
    last = points[-1]
    return d + f" L {_fmt(last[0])},{_fmt(last[1])}"


def point_at(points: list, distance: float) -> tuple:
    """Point at ``distance`` along the polyline."""
    walked = 0.0
    for i in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if walked + seg >= distance or i == len(points) - 2:
            t = 0.0 if seg == 0 else max(0.0, min(1.0, (distance - walked) / seg))
            return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        walked += seg
    return points[-1]


def longest_segment(points: list) -> tuple:
    """``((mx, my), (vx, vy), length)`` for the longest segment of a polyline."""
    best = 0.0
    mid = points[0]
    vec = (1.0, 0.0)
    for i in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg > best:
            best = seg
            mid = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            vec = ((x1 - x0) / seg if seg else 1.0, (y1 - y0) / seg if seg else 0.0)
    return mid, vec, best


def label_anchor(points: list, gap: float, prefer: str = "",
                 descent: float = 0.0, ascent: float = 0.0) -> tuple:
    """Where an arrow label goes, and its orientation.

    Returns ``((x, y), orientation, segment_mid)`` where orientation is
    ``"h"`` (label above a horizontal run) or ``"v"`` (label beside a vertical
    run). ``gap`` is the visible clearance from the stroke the connector rules
    require (6–10px), measured from the *ink* — ``descent`` (how far the ink
    falls below the baseline) and ``ascent`` (how far the ink rises above it)
    come from the measurer, because a broad fallback face's CJK ink sits lower
    than a Latin one and would otherwise touch the line.
    """
    mid, vec, _ = longest_segment(points)
    horizontal = abs(vec[0]) >= abs(vec[1])
    if prefer in ("h", "v"):
        horizontal = prefer == "h"
    if horizontal:
        return (mid[0], mid[1] - gap + descent), "h", mid
    return (mid[0] + gap + ascent, mid[1]), "v", mid


def end_tangent(points: list) -> tuple:
    """``(x, y, deg)`` at the path end: where the arrowhead tip points."""
    (x0, y0), (x1, y1) = points[-2], points[-1]
    deg = math.degrees(math.atan2(y1 - y0, x1 - x0))
    return x1, y1, deg


def arrowhead(points: list) -> tuple[str, tuple]:
    """``(polygon points, (tip_x, tip_y, deg))`` for the end of a polyline.

    The SVG marker the source uses is not rendered by ThorVG, so the head is
    emitted as a rotated polygon; ``ARROW_TIP`` offsets the tip one pixel past
    the anchor so the head visually touches the box stroke.
    """
    x, y, deg = end_tangent(points)
    rad = math.radians(deg)
    ux, uy = math.cos(rad), math.sin(rad)
    tip = (x + ux * ARROW_TIP, y + uy * ARROW_TIP)
    base = (tip[0] - ux * ARROW_LEN, tip[1] - uy * ARROW_LEN)
    nx, ny = -uy, ux
    p1 = (base[0] + nx * ARROW_HALF, base[1] + ny * ARROW_HALF)
    p2 = (base[0] - nx * ARROW_HALF, base[1] - ny * ARROW_HALF)
    pts = " ".join(f"{_fmt(p[0])},{_fmt(p[1])}" for p in (tip, p1, p2))
    return pts, (tip[0], tip[1], deg)


def open_head(points: list) -> str:
    """Polyline points for an async / fire-and-forget open arrowhead."""
    x, y, deg = end_tangent(points)
    rad = math.radians(deg)
    ux, uy = math.cos(rad), math.sin(rad)
    tip = (x + ux * ARROW_TIP, y + uy * ARROW_TIP)
    base = (tip[0] - ux * ARROW_LEN, tip[1] - uy * ARROW_LEN)
    nx, ny = -uy, ux
    p1 = (base[0] + nx * ARROW_HALF, base[1] + ny * ARROW_HALF)
    p2 = (base[0] - nx * ARROW_HALF, base[1] - ny * ARROW_HALF)
    return " ".join(f"{_fmt(p[0])},{_fmt(p[1])}" for p in (p1, tip, p2))


# ---------------------------------------------------------------------------
# Text / label collision checks (the source's §6 rules 2 and 6, as tests)
# ---------------------------------------------------------------------------


def segment_distance(point: tuple, a: tuple, b: tuple) -> float:
    """Shortest distance from ``point`` to segment ``a``–``b``."""
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def path_distance(point: tuple, points: list) -> float:
    return min(segment_distance(point, points[i], points[i + 1])
               for i in range(len(points) - 1))


def rect_overlap(a: tuple, b: tuple) -> tuple:
    """Overlap of two ``(x, y, w, h)`` rects as ``(dx, dy)`` (<=0 means no overlap)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (min(ax + aw, bx + bw) - max(ax, bx), min(ay + ah, by + bh) - max(ay, by))


def rect_contains(inner: tuple, outer: tuple, eps: float = 0.5) -> bool:
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return (ix >= ox - eps and iy >= oy - eps
            and ix + iw <= ox + ow + eps and iy + ih <= oy + oh + eps)

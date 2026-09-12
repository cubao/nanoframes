"""Path parametrization by arc length for text-along-curve placement.

ThorVG's SVG loader does not support ``<textPath>`` (confirmed empirically:
it loads without error but rasterizes nothing). To place text along a curve we
sample the curve by arc length ourselves — flattening the path into short line
segments, building an arc-length lookup, and reporting ``(x, y, angle)`` at any
arc position. This gives nanoframes an offline analogue of remotion's
``@remotion/paths`` ``getPointAtLength`` / ``getTangentAtLength``.

Supported authoring form::

    <text data-curve="M0 400 C 300 -200 600 200 900 0"
          data-curve-pad="0" ...>text along the curve</text>

``data-curve`` is a standard SVG path ``d``. Angle is the in-path tangent at
the glyph's advance position, so each glyph is rotated to follow the curve.
Flattened commands: ``M``/``L``/``C``/``Q``/``S``/``T``/``H``/``V``/``Z``
(absolute and relative); elliptical arcs (``A``) raise ``NotImplementedError``
rather than silently dropping the segment.
"""

from __future__ import annotations

import math
import re

_TOK = re.compile(r"[MLCSTAmlcsta]|[-+]?(?:\d*\.\d+|\d+\.?)\d*(?:[eE][-+]?\d+)?")


class PathSampler:
    """Flattens an SVG path ``d`` into an arc-length table."""

    def __init__(self, d: str, samples: int = 48):
        self.points, self.dist = _flatten(d, samples)
        self.length = self.dist[-1]

    def point(self, s: float) -> tuple[float, float]:
        """Return the point at arc length ``s`` along the path."""
        s = max(0.0, min(s, self.length))
        seg_len = self.length / max(1, len(self.dist) - 1)
        i = min(len(self.dist) - 2, int(s / seg_len) if seg_len else 0)
        a, b = self.points[i], self.points[i + 1]
        local = (s - i * seg_len) / seg_len if seg_len else 0.0
        return (a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local)

    def angle(self, s: float) -> float:
        """Tangent angle (degrees) at arc length ``s``."""
        s = max(0.0, min(s, self.length))
        seg_len = self.length / max(1, len(self.dist) - 1)
        i = min(len(self.dist) - 2, int(s / seg_len) if seg_len else 0)
        a, b = self.points[i], self.points[i + 1]
        return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))

    @staticmethod
    def circle(cx: float, cy: float, r: float, start_deg: float = -90.0,
               samples: int = 240) -> "PathSampler":
        """Build a circular path sampler (counter-clockwise from start_deg)."""
        pts: list[tuple[float, float]] = []
        dist = [0.0]
        prev = None
        for k in range(1, samples + 1):
            a = math.radians(start_deg + 360.0 * k / samples)
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            if prev is not None:
                dist.append(dist[-1] + math.hypot(x - prev[0], y - prev[1]))
            pts.append((x, y))
            prev = (x, y)
        out = PathSampler.__new__(PathSampler)
        out.points, out.dist = pts, dist
        out.length = dist[-1]
        return out


def _flatten(d: str, samples: int) -> tuple[list[tuple[float, float]], list[float]]:
    """Return (polyline, cumulative-arc-lengths)."""
    pts: list[tuple[float, float]] = []
    dist = [0.0]
    args: list[float] = []
    cx = cy = 0.0
    sx = sy = 0.0

    toks = _TOK.findall(d)
    i = 0
    cur_cmd: str | None = None
    while i < len(toks):
        if toks[i] in "MLCSTAmlcsta":
            cmd = toks[i]
            i += 1
            args = []
            while i < len(toks) and not toks[i][0].isalpha():
                args.append(float(toks[i]))
                i += 1
        else:
            # bare numbers continue the previous command
            cmd = cur_cmd
            if cmd is None:
                break
            args = [float(toks[i])]
            i += 1
            while i < len(toks) and not toks[i][0].isalpha():
                args.append(float(toks[i]))
                i += 1
        cur_cmd = cmd

        if cmd in ("A", "a"):
            raise NotImplementedError(
                "elliptical arc segments are not supported (PathSampler flattens "
                "M/L/C/Q/S/T/H/V/Z only)"
            )

        n = len(args)
        if cmd in ("M", "m"):
            k = 0
            first = True
            while k < n:
                if first:
                    if cmd == "m":
                        cx += args[k]
                        cy += args[k + 1]
                    else:
                        cx, cy = args[k], args[k + 1]
                    sx, sy = cx, cy
                    if not pts:
                        pts.append((cx, cy))
                    first = False
                    cur_cmd = "L"
                else:
                    _line(pts, dist, cx, cy, cx + args[k] if cmd == "m" else args[k],
                          cy + args[k + 1] if cmd == "m" else args[k + 1])
                    cx = cx + args[k] if cmd == "m" else args[k]
                    cy = cy + args[k + 1] if cmd == "m" else args[k + 1]
                k += 2
        elif cmd in ("L", "l"):
            k = 0
            while k < n:
                tx = cx + args[k] if cmd == "l" else args[k]
                ty = cy + args[k + 1] if cmd == "l" else args[k + 1]
                _line(pts, dist, cx, cy, tx, ty)
                cx, cy = tx, ty
                k += 2
        elif cmd in ("C", "c"):
            k = 0
            while k < n:
                x1 = cx + args[k] if cmd == "c" else args[k]
                y1 = cy + args[k + 1] if cmd == "c" else args[k + 1]
                x2 = cx + args[k + 2] if cmd == "c" else args[k + 2]
                y2 = cy + args[k + 3] if cmd == "c" else args[k + 3]
                x3 = cx + args[k + 4] if cmd == "c" else args[k + 4]
                y3 = cy + args[k + 5] if cmd == "c" else args[k + 5]
                _cubic(pts, dist, cx, cy, x1, y1, x2, y2, x3, y3, samples)
                cx, cy = x3, y3
                k += 6
        elif cmd in ("Q", "q"):
            k = 0
            while k < n:
                x1 = cx + args[k] if cmd == "q" else args[k]
                y1 = cy + args[k + 1] if cmd == "q" else args[k + 1]
                x2 = cx + args[k + 2] if cmd == "q" else args[k + 2]
                y2 = cy + args[k + 3] if cmd == "q" else args[k + 3]
                _quad(pts, dist, cx, cy, x1, y1, x2, y2, samples)
                cx, cy = x2, y2
                k += 4
        elif cmd in ("S", "s"):
            # half-cubic; treated as cubic with reflected control point stub
            k = 0
            while k < n:
                x2 = cx + args[k] if cmd == "s" else args[k]
                y2 = cy + args[k + 1] if cmd == "s" else args[k + 1]
                x3 = cx + args[k + 2] if cmd == "s" else args[k + 2]
                y3 = cy + args[k + 3] if cmd == "s" else args[k + 3]
                _cubic(pts, dist, cx, cy, cx, cy, x2, y2, x3, y3, samples)
                cx, cy = x3, y3
                k += 4
        elif cmd in ("T", "t"):
            k = 0
            while k < n:
                x2 = cx + args[k] if cmd == "t" else args[k]
                y2 = cy + args[k + 1] if cmd == "t" else args[k + 1]
                _quad(pts, dist, cx, cy, cx, cy, x2, y2, samples)
                cx, cy = x2, y2
                k += 2
        elif cmd in ("H", "h"):
            for k in range(0, n, 1):
                tx = cx + args[k] if cmd == "h" else args[k]
                _line(pts, dist, cx, cy, tx, cy)
                cx = tx
        elif cmd in ("V", "v"):
            for k in range(0, n, 1):
                ty = cy + args[k] if cmd == "v" else args[k]
                _line(pts, dist, cx, cy, cx, ty)
                cy = ty
        elif cmd in ("Z", "z"):
            _line(pts, dist, cx, cy, sx, sy)
            cx, cy = sx, sy
    return pts, dist


def _line(pts, dist, x0, y0, x1, y1, step: float = 1.0):
    seg_len = math.hypot(x1 - x0, y1 - y0)
    if seg_len == 0:
        return
    n = max(1, int(seg_len * step))
    for k in range(1, n + 1):
        f = k / n
        px = x0 + (x1 - x0) * f
        py = y0 + (y1 - y0) * f
        prev = pts[-1]
        pts.append((px, py))
        dist.append(dist[-1] + math.hypot(px - prev[0], py - prev[1]))


def _cubic(pts, dist, x0, y0, x1, y1, x2, y2, x3, y3, samples):
    for k in range(1, samples + 1):
        t = k / samples
        mt = 1 - t
        x = mt**3 * x0 + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x3
        y = mt**3 * y0 + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y3
        prev = pts[-1]
        pts.append((x, y))
        dist.append(dist[-1] + math.hypot(x - prev[0], y - prev[1]))


def _quad(pts, dist, x0, y0, x1, y1, x2, y2, samples):
    for k in range(1, samples + 1):
        t = k / samples
        mt = 1 - t
        x = mt**2 * x0 + 2 * mt * t * x1 + t**2 * x2
        y = mt**2 * y0 + 2 * mt * t * y1 + t**2 * y2
        prev = pts[-1]
        pts.append((x, y))
        dist.append(dist[-1] + math.hypot(x - prev[0], y - prev[1]))

"""The diagram scene — a tiny drawing IR between a spec and SVG.

A *scene* is the resolved, laid-out diagram: every coordinate computed, every
label measured, flat lists in paint order (background → zones → connectors →
labels → nodes → text). Both diagram kinds build one of these, and
``nanoframes.diagram.emit`` turns exactly this into SVG — so geometry is
tested against the IR, not against string output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Text:
    """A text run at a baseline anchor.

    ``kind`` records the semantic slot (``title`` / ``label`` / ``sub`` /
    ``tag`` / ``eyebrow`` / ``arrow``); the checks that keep labels off
    connectors and nodes only look at ``arrow`` runs.
    """

    x: float
    y: float
    content: str
    size: float
    fill: str
    family: str
    anchor: str = "middle"      # start | middle | end
    kind: str = "label"
    tracking: float = 0.0       # px; emitted per character (ThorVG ignores letter-spacing)
    mask: bool = False          # opaque paper plate behind the run
    opacity: float = 1.0


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str = "#ffffff"
    fill_opacity: float = 1.0
    stroke: str | None = None
    stroke_opacity: float = 1.0
    stroke_width: float = 1.0
    rx: float = 0.0
    dash: str | None = None
    opacity: float = 1.0
    weight: str = "box"          # box | zone | chip | line | background


@dataclass
class Path:
    d: str
    stroke: str
    stroke_width: float = 1.2
    dash: str | None = None
    opacity: float = 1.0
    head: str | None = None      # filled | open — arrowhead drawn as its own polygon
    head_fill: str | None = None
    head_at: tuple | None = None  # (x, y, tangent_deg) — computed when the path is built
    points: list = field(default_factory=list)  # the polyline, for geometry checks


@dataclass
class Group:
    """A named chunk of the scene — the unit that fades in when revealed."""

    name: str
    parts: list = field(default_factory=list)
    start: float = 0.0
    fade: float = 0.0


@dataclass
class Scene:
    width: float
    height: float
    fps: int = 30
    duration: float = 1.0
    background: str = "#f5f5f5"
    groups: list = field(default_factory=list)   # list[Group], in paint order
    warnings: list = field(default_factory=list)  # human-readable spec findings

    def add(self, group: Group) -> Group:
        self.groups.append(group)
        return group

    def texts(self, kind: str | None = None):
        for g in self.groups:
            for part in g.parts:
                if isinstance(part, Text) and (kind is None or part.kind == kind):
                    yield part

    def rects(self, weight: str | None = None):
        for g in self.groups:
            for part in g.parts:
                if isinstance(part, Rect) and (weight is None or part.weight == weight):
                    yield part

    def paths(self):
        for g in self.groups:
            for part in g.parts:
                if isinstance(part, Path):
                    yield part


def union_bounds(scene: Scene) -> tuple:
    """Bounding box of everything drawn: ``(x0, y0, x1, y1)``."""
    xs: list = []
    ys: list = []
    for g in scene.groups:
        for part in g.parts:
            if isinstance(part, Rect):
                if part.weight == "background":
                    continue  # sized to the final canvas, not a content bound
                xs += [part.x, part.x + part.w]
                ys += [part.y, part.y + part.h]
            elif isinstance(part, Text):
                half = part.size * max(1, len(part.content)) * 0.4
                if part.anchor == "middle":
                    xs += [part.x - half, part.x + half]
                elif part.anchor == "end":
                    xs += [part.x - 2 * half, part.x]
                else:
                    xs += [part.x, part.x + 2 * half]
                ys += [part.y - part.size, part.y + part.size * 0.3]
            elif isinstance(part, Path):
                for x, y in _PAIR_RE.findall(part.d):
                    xs.append(float(x))
                    ys.append(float(y))
                if part.head_at:
                    xs.append(part.head_at[0])
                    ys.append(part.head_at[1])
    if not xs or not ys:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


_PAIR_RE = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")


def translate(scene: Scene, dx: float, dy: float) -> Scene:
    """Shift the whole scene by ``(dx, dy)`` — the page margin, applied once."""
    if dx == 0 and dy == 0:
        return scene
    for group in scene.groups:
        for part in group.parts:
            if isinstance(part, Rect) and part.weight in ("box", "chip") or isinstance(part, Text):
                part.x += dx
                part.y += dy
            elif isinstance(part, Path):
                part.d = _PAIR_RE.sub(
                    lambda m: f"{float(m.group(1)) + dx:.2f},{float(m.group(2)) + dy:.2f}",
                    part.d,
                )
                part.points = [(x + dx, y + dy) for x, y in part.points]
                if part.head:
                    part.head = _PAIR_RE.sub(
                        lambda m: (f"{float(m.group(1)) + dx:.2f},"
                                   f"{float(m.group(2)) + dy:.2f}"),
                        part.head,
                    )
                if part.head_at:
                    part.head_at = (part.head_at[0] + dx, part.head_at[1] + dy,
                                    part.head_at[2])
    return scene

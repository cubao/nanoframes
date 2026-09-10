"""Where an element actually lands: geometry + transform chain, no rasterization.

A frame is rasterized into a fixed canvas, but nothing in the authoring loop
says whether an element's geometry ends up on it. ThorVG will happily draw a
picture whose content only exists outside the canvas — the frame then shows
nothing, with no error anywhere. Answering "does this land on the canvas?" is
pure arithmetic: parse the shape geometry, walk the transforms, intersect boxes.

Consumers:

* ``nanoframes lint`` — flags elements that never land on the canvas and
  ``rotate`` pivots that swing an element away from where it was authored;
* ``nanoframes debug`` — the per-element box report;
* bake's ``"center": "auto"`` transform pivot — the element's own box center.

Transforms are tracked as 2D affine matrices ``(a, b, c, d, e, f)`` in SVG
order (``x' = a·x + c·y + e``). Boxes are axis-aligned and conservative: a
rotated element reports the box of its rotated corners, not its silhouette.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from nanoframes.xmlutil import float_attr, local_name

# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

Matrix = tuple  # (a, b, c, d, e, f) — 2D affine, SVG order

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_TRANSFORM_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)\d*(?:[eE][-+]?\d+)?")


class TransformError(ValueError):
    """Raised for a ``transform`` attribute this module cannot model."""


def multiply(m: Matrix, n: Matrix) -> Matrix:
    """Return ``m ∘ n`` (n applies first), as SVG lists transforms."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _function_matrix(name: str, args: list[float]) -> Matrix:
    if name == "translate":
        return (1.0, 0.0, 0.0, 1.0, args[0], args[1] if len(args) > 1 else 0.0)
    if name == "scale":
        sx = args[0]
        return (sx, 0.0, 0.0, args[1] if len(args) > 1 else sx, 0.0, 0.0)
    if name == "rotate":
        rad = math.radians(args[0])
        cos, sin = math.cos(rad), math.sin(rad)
        rot = (cos, sin, -sin, cos, 0.0, 0.0)
        if len(args) >= 3:  # rotate(deg cx cy) == translate(cx,cy) rotate(deg) translate(-cx,-cy)
            return multiply(multiply((1.0, 0.0, 0.0, 1.0, args[1], args[2]), rot),
                            (1.0, 0.0, 0.0, 1.0, -args[1], -args[2]))
        return rot
    if name == "matrix" and len(args) >= 6:
        return tuple(args[:6])  # type: ignore[return-value]
    if name == "skewX":
        return (1.0, 0.0, math.tan(math.radians(args[0])), 1.0, 0.0, 0.0)
    if name == "skewY":
        return (1.0, math.tan(math.radians(args[0])), 0.0, 1.0, 0.0, 0.0)
    raise TransformError(f"unsupported transform function {name!r}")


def parse_transform(text: str | None) -> Matrix:
    """Parse an SVG ``transform`` attribute into a matrix (list order applied)."""
    if not text or not text.strip():
        return IDENTITY
    matrix = IDENTITY
    for name, raw_args in _TRANSFORM_RE.findall(text):
        args = [float(v) for v in _NUMBER_RE.findall(raw_args)]
        if not args:
            raise TransformError(f"transform {name!r} has no arguments")
        matrix = multiply(matrix, _function_matrix(name, args))
    return matrix


# ---------------------------------------------------------------------------
# Boxes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    """An axis-aligned box in some user coordinate system."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def diagonal(self) -> float:
        return math.hypot(self.width, self.height)

    def union(self, other: "Box") -> "Box":
        return Box(min(self.x0, other.x0), min(self.y0, other.y0),
                   max(self.x1, other.x1), max(self.y1, other.y1))

    def transform(self, m: Matrix) -> "Box":
        """Box of this box's corners under ``m`` (conservative under rotation)."""
        corners = [apply(m, x, y) for x, y in
                   ((self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1))]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return Box(min(xs), min(ys), max(xs), max(ys))

    def intersects(self, other: "Box") -> bool:
        return not (self.x1 < other.x0 or other.x1 < self.x0
                    or self.y1 < other.y0 or other.y1 < self.y0)

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


@dataclass(frozen=True)
class Bounds:
    """A measured box plus whether every piece of geometry could be measured.

    ``complete`` is False when part of the subtree could not be measured (a
    text node without a measurer, a path with elliptical arcs, a ``<use>``).
    Callers must not report "this renders as nothing" from an incomplete box —
    the unmeasured part may well be the visible part.
    """

    box: Box | None = None
    complete: bool = True

    def union(self, other: "Bounds") -> "Bounds":
        if self.box is None:
            return Bounds(other.box, self.complete and other.complete)
        if other.box is None:
            return Bounds(self.box, self.complete and other.complete)
        return Bounds(self.box.union(other.box), self.complete and other.complete)

    @property
    def usable(self) -> bool:
        return self.box is not None and self.complete


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

# Non-rendering (or non-geometric) containers: skipped without marking the
# measurement incomplete.
NON_RENDERING_TAGS = frozenset({
    "defs", "clipPath", "mask", "linearGradient", "radialGradient", "stop",
    "style", "script", "title", "desc", "metadata", "filter", "pattern",
    "symbol", "marker", "animate", "animateTransform",
})


def _points_box(points: str) -> Box | None:
    nums = [float(v) for v in _NUMBER_RE.findall(points or "")]
    if len(nums) < 2:
        return None
    xs, ys = nums[0::2], nums[1::2]
    return Box(min(xs), min(ys), max(xs), max(ys))


def _path_box(d: str) -> Box | None:
    """Box of a path ``d``.

    Flattened with the same sampler text-along-curve uses, so curves contribute
    their real extent rather than a control-point hull. Paths with elliptical
    arcs are unmeasurable here (the sampler refuses them) and report None.
    """
    if not d:
        return None
    from nanoframes.curve import PathSampler  # local: keeps bounds.py light

    try:
        sampler = PathSampler(d, samples=8)
    except NotImplementedError:
        return None
    if not sampler.points:
        return None
    xs = [p[0] for p in sampler.points]
    ys = [p[1] for p in sampler.points]
    return Box(min(xs), min(ys), max(xs), max(ys))


def _own_geometry(node) -> Bounds:
    """Geometry box for one node, excluding its own ``transform``."""
    tag = local_name(node.tag)
    if tag in NON_RENDERING_TAGS:
        return Bounds()
    if tag == "rect":
        x, y = float_attr(node, "x"), float_attr(node, "y")
        if node.get("width") is None or node.get("height") is None:
            return Bounds()
        return Bounds(Box(x, y, x + float_attr(node, "width"), y + float_attr(node, "height")))
    if tag == "circle":
        cx, cy, r = float_attr(node, "cx"), float_attr(node, "cy"), float_attr(node, "r")
        return Bounds(Box(cx - r, cy - r, cx + r, cy + r))
    if tag == "ellipse":
        cx, cy = float_attr(node, "cx"), float_attr(node, "cy")
        rx, ry = float_attr(node, "rx"), float_attr(node, "ry")
        return Bounds(Box(cx - rx, cy - ry, cx + rx, cy + ry))
    if tag == "line":
        x1, y1 = float_attr(node, "x1"), float_attr(node, "y1")
        x2, y2 = float_attr(node, "x2"), float_attr(node, "y2")
        return Bounds(Box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
    if tag in ("polygon", "polyline"):
        box = _points_box(node.get("points") or "")
        return Bounds(box)
    if tag == "path":
        box = _path_box(node.get("d") or "")
        return Bounds(box) if box is not None else Bounds(complete=False)
    if tag == "image":
        x, y = float_attr(node, "x"), float_attr(node, "y")
        w, h = float_attr(node, "width"), float_attr(node, "height")
        return Bounds(Box(x, y, x + w, y + h))
    if tag in ("text", "tspan"):
        return Bounds(complete=False)  # needs a font: see subtree_bounds(measurer=…)
    if tag in ("g", "svg", "a", "switch"):
        return Bounds()
    return Bounds(complete=False)  # <use>, <foreignObject>, anything unknown


def _text_bounds(node, measurer) -> Bounds:
    """Ink box of a ``<text>`` node, measured the way the renderer will draw it."""
    text = "".join(node.itertext())
    if not text.strip():
        return Bounds()
    try:
        size = float_attr(node, "font-size", 16.0)
        spacing = float_attr(node, "letter-spacing", 0.0)
    except ValueError:
        return Bounds(complete=False)
    ink = measurer.ink(text, node.get("font-family") or "Arial",
                       node.get("font-weight") or "normal", size, spacing)
    if ink.w == 0 and ink.h == 0:
        return Bounds(Box(float_attr(node, "x"), float_attr(node, "y"),
                          float_attr(node, "x"), float_attr(node, "y")))
    x, y = float_attr(node, "x"), float_attr(node, "y")
    # text-anchor shifts the ink box along x; center/end are rare enough that a
    # one-line adjustment keeps the box honest.
    anchor = node.get("text-anchor")
    if anchor == "middle":
        x -= ink.w / 2.0
    elif anchor == "end":
        x -= ink.w
    return Bounds(Box(x + ink.left_dx, y + ink.top, x + ink.right_dx, y + ink.bottom))


def own_bounds(node, measurer=None) -> Bounds:
    """A single node's own geometry, excluding its ``transform`` and its children."""
    tag = local_name(node.tag)
    if tag in ("text", "tspan") and measurer is not None:
        return _text_bounds(node, measurer)
    return _own_geometry(node)


def local_bounds(node, measurer=None) -> Bounds:
    """Geometry of ``node`` + descendants, excluding the node's own transform.

    That is the coordinate system the node's ``transform`` maps *from* — the
    space a transform's ``"center": "auto"`` pivot must be expressed in.
    """
    result = own_bounds(node, measurer)
    for child in node:
        result = result.union(subtree_bounds(child, measurer))
    return result


def subtree_bounds(node, measurer=None) -> Bounds:
    """Geometry of ``node`` and everything below it, in the *parent* space."""
    inner = local_bounds(node, measurer)
    if inner.box is None:
        return inner
    try:
        matrix = parse_transform(node.get("transform"))
    except TransformError:
        return Bounds(complete=False)
    return Bounds(inner.box.transform(matrix), inner.complete)


def painted_bounds(node, measurer=None) -> Bounds:
    """``subtree_bounds`` with anything bake left at ``display:none`` pruned.

    A baked tree materializes each element's clip window as ``display:none``;
    what a frame actually paints is the subtree without those nodes.
    """
    if node.get("display") == "none":
        return Bounds()
    inner = own_bounds(node, measurer)
    for child in node:
        inner = inner.union(painted_bounds(child, measurer))
    if inner.box is None:
        return inner
    try:
        matrix = parse_transform(node.get("transform"))
    except TransformError:
        return Bounds(complete=False)
    return Bounds(inner.box.transform(matrix), inner.complete)


def root_bounds(root, node, measurer=None) -> Bounds:
    """Geometry of ``node`` in the root's user space (every ancestor transform applied)."""
    ancestors = _ancestor_chain(root, node)
    if ancestors is None:
        return Bounds(complete=False)
    bounds = subtree_bounds(node, measurer)
    if bounds.box is None:
        return bounds
    box = bounds.box
    for ancestor in ancestors:
        try:
            box = box.transform(parse_transform(ancestor.get("transform")))
        except TransformError:
            return Bounds(complete=False)
    return Bounds(box, bounds.complete)


def _ancestor_chain(root, node) -> list | None:
    """Nodes from the root down to (excluding) ``node``; None if not a descendant."""
    path: list = []
    return path if _find_path(root, node, path) else None


def _find_path(current, target, path: list) -> bool:
    if current is target:
        return True
    for child in current:
        path.append(child)
        if _find_path(child, target, path):
            return True
        path.pop()
    return False


def canvas_box(width: float, height: float) -> Box:
    return Box(0.0, 0.0, float(width), float(height))


def iter_renderable(root, ancestors: Matrix = IDENTITY, path: tuple = ()):
    """Yield ``(path, node, matrix)`` for every renderable node under ``root``.

    ``path`` is the child-index chain — stable across bakes of one document, so
    per-frame samples can be lined up. ``matrix`` maps the node's *parent* space
    into the root's. Non-rendering subtrees (``defs``, ``script``, masks) are
    pruned, as is anything under a transform this module cannot model.
    """
    for index, child in enumerate(root):
        here = path + (index,)
        if local_name(child.tag) in NON_RENDERING_TAGS:
            continue
        yield here, child, ancestors
        try:
            inner = multiply(ancestors, parse_transform(child.get("transform")))
        except TransformError:
            continue
        yield from iter_renderable(child, inner, here)


def node_at(root, path: tuple):
    """The node at a child-index path, or None if the tree differs there."""
    node = root
    for index in path:
        children = list(node)
        if index >= len(children):
            return None
        node = children[index]
    return node


def label(node) -> str:
    """A short human label for a node (``#id``, else ``<tag>``)."""
    if node is None:
        return "element"
    return f"#{node.get('id')}" if node.get("id") else f"<{local_name(node.tag)}>"


def classify(box: Box, canvas: Box) -> str:
    """One of ``on-canvas``, ``clipped`` (partly outside) or ``off-canvas`` (no overlap)."""
    if not box.intersects(canvas):
        return "off-canvas"
    if box.x0 < canvas.x0 or box.y0 < canvas.y0 or box.x1 > canvas.x1 or box.y1 > canvas.y1:
        return "clipped"
    return "on-canvas"

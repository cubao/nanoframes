"""The tree grammar: a nested hierarchy → a tidy org chart.

This is the second *computed* grammar (``loop`` was the first): the spec carries
no coordinates at all, only the words and the reporting lines, and the compiler
turns the shape into geometry. It is one compiler of the package's grammar table
(:data:`nanoframes.diagram.GRAMMARS`) and produces the same
:class:`~nanoframes.diagram.scene.Scene` as ``flow``, through the same page
machinery (``nanoframes.diagram.canvas``) — so tokens, the 4px grid, measured
text, the legend, the reveal clock and the emitter are inherited, not re-derived.

The algorithm is Reingold–Tilford in Buchheim et al.'s linear-time form
(*Improving Walker's Algorithm to Run in Linear Time*, 2002): leaves are packed
left to right, every parent is centred over the extremes of its children, and
subtrees are threaded against each other's contours so that unequal branches
interleave instead of each reserving its full width. That is the whole algorithm
here — no general layout engine, no box model, no node-specific measurement:
the recursive ``_first_walk``/``_apportion`` pair moves each box's *centre* and
leaves every decision about what a box looks like to ``canvas``.

Placement is a separate, deliberate step. The layout returns centres in local
units; the compiler then snaps each box's top-left corner onto the 4px grid (as
``flow`` does for authored coordinates) and puts the canvas centre on the
**root**, clamped so the figure never leaves the page margins. Rows are uniform:
same depth, same y, one row pitch for the whole chart.

Siblings share the connector trunk — every child's elbow runs down from the
parent's bottom centre and turns at the same bus, which is what makes a
hierarchy readable. That is a deliberate relaxation of ``flow``'s "no two
connectors share a stroke path" rule, which exists to keep *relations* apart;
here the shared trunk *is* the relation (docs/tree.md).
"""

from __future__ import annotations

from nanoframes.diagram import geometry as geo
from nanoframes.diagram import text as txt
from nanoframes.diagram.canvas import (
    REVEAL_FADE,
    Canvas,
    box_parts,
    connector_path,
    legend_space,
    node_size,
    rough,
    type_items,
    wants_legend,
)
from nanoframes.diagram.scene import Group, Scene
from nanoframes.diagram.spec import Spec
from nanoframes.diagram.tokens import PRESETS, Tokens

# Sibling gap and row pitch, both on the 4px grid. The gap is the air between
# two neighbouring subtrees (the tidy layout keeps it exactly); the pitch is the
# gap below a row of boxes.
H_GAP = 48.0
V_GAP = 64.0
# Taste budget (the source's, restated for a hierarchy): the chart is a table
# once a row stops being a hierarchy. Warned, never refused — a wide tree is a
# legible chart, just a poor one; `canvas` grows rather than clipping.
BUDGET_NODES = 15


class _Node:
    """One box in the tidy-layout walk — Reingold–Tilford's per-node state."""

    __slots__ = ("spec", "w", "h", "children", "parent", "number", "prelim",
                 "mod", "shift", "change", "thread", "ancestor")

    def __init__(self, spec, w: float, h: float, parent=None, number: int = 0):
        self.spec = spec
        self.w = w
        self.h = h
        self.children: list = []
        self.parent = parent
        self.number = number
        # (x of the box centre) relative to the node's own subtree; `mod` is the
        # same shift carried down to the children, and `shift`/`change`/`thread`
        # are the bookkeeping `_apportion` uses to move a subtree as a unit.
        self.prelim = 0.0
        self.mod = 0.0
        self.shift = 0.0
        self.change = 0.0
        self.thread = None
        self.ancestor = self

    @property
    def left_sibling(self):
        if self.parent is None or self.number == 0:
            return None
        return self.parent.children[self.number - 1]


def build_tree(spec: Spec, tokens: Tokens, measurer) -> Scene:
    """Compile a tree spec into a scene (the grammar's one entry point)."""
    b = Canvas(spec, tokens, measurer)
    t = tokens
    root = spec.tree
    if root is None:
        raise ValueError('a "tree" diagram needs a "tree" object')
    nodes = list(_walk(root))                       # pre-order, root first
    if len(nodes) > BUDGET_NODES:
        b.warnings.append(
            f"{len(nodes)} boxes over the {BUDGET_NODES}-box budget — a chart this"
            " size reads as a table: split it by level, or show one branch"
        )

    sizes = {n.id: node_size(b.measurer, n, t.ramp, b.node_font, b.sub_font)
             for n in nodes}
    h_gap = H_GAP if spec.h_gap is None else spec.h_gap
    v_gap = V_GAP if spec.v_gap is None else spec.v_gap
    placed = _tidy(_node(root, sizes), h_gap)       # id -> (centre_x, depth, w, h)

    row_h = max(h for _, h in sizes.values())
    pitch = geo.ceil4(row_h + v_gap)
    depth_max = max(depth for _, depth, _, _ in placed.values())
    left = min(cx - w / 2.0 for cx, _, w, _ in placed.values())
    right = max(cx + w / 2.0 for cx, _, w, _ in placed.values())
    header = b.header_height()
    floor = (geo.ceil4(right - left + 2 * spec.margin),
             geo.ceil4(depth_max * pitch + row_h + 2 * spec.margin + header
                       + legend_space(spec, nodes)))
    minimum = spec.canvas or (
        (max(PRESETS[spec.preset][0], floor[0]), max(PRESETS[spec.preset][1], floor[1]))
        if spec.preset and spec.preset in PRESETS else floor
    )

    # Horizontal placement: the root is a tree's visual anchor (the loop centres
    # on its hub for the same reason), so the canvas centre goes on the root —
    # unless that would push the figure past a margin, in which case jam it
    # against the edge it would have crossed. The canvas is at least the content
    # plus both margins, so `minimum` is always enough for the figure to fit.
    origin = min(max(minimum[0] / 2.0 - (placed[root.id][0] - left), spec.margin),
                 minimum[0] - spec.margin - (right - left))
    top = spec.margin + header
    boxes = {}
    for node in nodes:                              # grid-snapped box corners
        cx, depth, w, h = placed[node.id]
        boxes[node.id] = (geo.q4(origin + cx - left - w / 2.0),
                          geo.q4(top + depth * pitch), w, h)

    groups = [b.background(minimum[0], minimum[1])]
    for parent, child in _edges(root):              # connectors, then their nodes
        g = Group(name=f"edge:{parent.id}->{child.id}")
        g.start, g.fade = b.slice(REVEAL_FADE)
        g.parts.append(_connector(boxes, parent, child, t))
        groups.append(g)

    for node in nodes:                              # nodes mask the connectors
        x, y, w, h = boxes[node.id]
        style = t.node_style(node.type)
        g = Group(name=f"node:{node.id}")
        g.start, g.fade = b.slice(REVEAL_FADE)
        g.parts += box_parts(x, y, w, h, f"node:{node.id}", style, t)
        g.parts += txt.node_texts(
            b.measurer, x, y, w, h, node.label, node.sub, node.tag, t.ramp,
            b.node_font, b.sub_font, t.ink, t.muted, t.soft, t.accent, focal=node.focal)
        if node.tag:
            g.parts += txt.tag_chip(x, y, f"tag:{node.id}", style["stroke"],
                                    rough=rough(t))
        groups.append(g)

    head = Group(name="header", start=0.0, fade=0.0)
    head.parts += b.title_block()
    if head.parts:
        groups.append(head)
    items = type_items(nodes, t) if wants_legend(spec, nodes) else []
    return b.to_scene(groups, minimum=minimum, place=b.legend(minimum[0], items))


def _connector(boxes: dict, parent, child, tokens: Tokens):
    """Parent bottom-centre → child top-centre: down, across the bus, down."""
    px, py, pw, ph = boxes[parent.id]
    cx, cy, cw, _ = boxes[child.id]
    points, _ = geo.elbow((px + pw / 2.0, py + ph), (cx + cw / 2.0, cy), "down")
    return connector_path(points, tokens.edge_style("default"), tokens,
                          f"edge:{parent.id}->{child.id}")


def _walk(root):
    """Every node of the tree, root first (the order dicts and groups use)."""
    yield root
    for child in root.children:
        yield from _walk(child)


def _edges(root):
    """Every ``(parent, child)`` pair, in pre-order — the chart's reporting lines."""
    for child in root.children:
        yield root, child
        yield from _edges(child)


def _node(spec_node, sizes: dict, parent=None, number: int = 0) -> _Node:
    w, h = sizes[spec_node.id]
    node = _Node(spec_node, w, h, parent, number)
    node.children = [_node(child, sizes, node, i)
                     for i, child in enumerate(spec_node.children)]
    return node


# ---------------------------------------------------------------------------
# Reingold–Tilford (Buchheim et al. 2002)
#
# `prelim` is a box *centre*, in local units; `mod` is the shift a node hands to
# its whole subtree during `_second_walk`. Widths enter through `_distance`, so
# boxes of any size keep the same minimum gap.
# ---------------------------------------------------------------------------


def _tidy(root: _Node, gap: float) -> dict:
    """``id -> (centre_x, depth, w, h)`` for every box."""
    _first_walk(root, gap)
    out: dict = {}
    _second_walk(root, 0.0, 0, out)
    return out


def _distance(a: _Node, b: _Node, gap: float) -> float:
    """Minimum centre-to-centre separation of two adjacent boxes."""
    return (a.w + b.w) / 2.0 + gap


def _next_left(v: _Node):
    """The next node on ``v``'s left contour: its thread, else its first child."""
    return v.thread if v.thread is not None else (v.children[0] if v.children else None)


def _next_right(v: _Node):
    """The next node on ``v``'s right contour: its thread, else its last child."""
    return v.thread if v.thread is not None else (v.children[-1] if v.children else None)


def _first_walk(v: _Node, gap: float) -> None:
    """Post-order pass: pack leaves, centre parents, apportion each subtree."""
    if not v.children:
        left = v.left_sibling
        v.prelim = left.prelim + _distance(left, v, gap) if left else 0.0
        return
    default = v.children[0]
    for child in v.children:
        _first_walk(child, gap)
        default = _apportion(child, default, gap)
    _execute_shifts(v)
    midpoint = (v.children[0].prelim + v.children[-1].prelim) / 2.0
    left = v.left_sibling
    if left:
        # A sibling to the left forces this subtree right; the difference from
        # the ideal midpoint is what the children will be shifted by.
        v.prelim = left.prelim + _distance(left, v, gap)
        v.mod = v.prelim - midpoint
    else:
        v.prelim = midpoint


def _apportion(v: _Node, default: _Node, gap: float) -> _Node:
    """Push ``v`` right until its contour clears its left sibling's.

    Walks the right contour of the left sibling and the left contour of ``v`` in
    step (following threads where a subtree is shallower), and moves the whole
    conflicting subtree as a unit at each overlap. This is what lets two
    branches of different shape interleave instead of each reserving its full
    width — the difference between a tidy tree and evenly-spaced columns.
    """
    left = v.left_sibling
    if left is None:
        return default
    inside_right = outside_right = v
    inside_left = left
    outside_left = v.parent.children[0]
    s_ir = s_or = v.mod
    s_il = left.mod
    s_ol = outside_left.mod
    while _next_right(inside_left) is not None and _next_left(inside_right) is not None:
        inside_left = _next_right(inside_left)
        inside_right = _next_left(inside_right)
        outside_left = _next_left(outside_left)
        outside_right = _next_right(outside_right)
        outside_right.ancestor = v
        shift = ((inside_left.prelim + s_il) - (inside_right.prelim + s_ir)
                 + _distance(inside_left, inside_right, gap))
        if shift > 0:
            _move_subtree(_ancestor(inside_left, v, default), v, shift)
            s_ir += shift
            s_or += shift
        s_il += inside_left.mod
        s_ir += inside_right.mod
        s_ol += outside_left.mod
        s_or += outside_right.mod
    if _next_right(inside_left) is not None and _next_right(outside_right) is None:
        # The left subtree reaches deeper: hand its contour on through a thread.
        outside_right.thread = _next_right(inside_left)
        outside_right.mod += s_il - s_or
    if _next_left(inside_right) is not None and _next_left(outside_left) is None:
        outside_left.thread = _next_left(inside_right)
        outside_left.mod += s_ir - s_ol
    return v


def _move_subtree(left: _Node, right: _Node, shift: float) -> None:
    """Move ``right``'s subtree ``shift`` to the right, spreading the cost."""
    subtrees = right.number - left.number
    right.change -= shift / subtrees
    right.shift += shift
    left.change += shift / subtrees
    right.prelim += shift
    right.mod += shift


def _execute_shifts(v: _Node) -> None:
    """Apply the deferred per-subtree shifts to ``v``'s children."""
    shift = 0.0
    change = 0.0
    for child in reversed(v.children):
        child.prelim += shift
        child.mod += shift
        change += child.change
        shift += child.shift + change


def _ancestor(inside_left: _Node, v: _Node, default: _Node) -> _Node:
    """The left sibling whose subtree must move — ``default`` when there is none."""
    return inside_left.ancestor if inside_left.ancestor.parent is v.parent else default


def _second_walk(v: _Node, m: float, depth: int, out: dict) -> None:
    """Sum the modifiers down the tree: relative ``prelim`` → absolute centres."""
    out[v.spec.id] = (v.prelim + m, depth, v.w, v.h)
    for child in v.children:
        _second_walk(child, m + v.mod, depth + 1, out)

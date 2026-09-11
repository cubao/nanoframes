"""Build a :class:`Scene` from a parsed diagram spec.

Two kinds, both fully deterministic:

* ``flow`` — explicit node positions; the builder owns box sizing, orthogonal
  connector routing with per-edge port fanning, masked arrow labels, zones and
  the arrowheads ThorVG cannot draw.
* ``loop`` — the source's parametric ring (``type-loop.md`` §2): stations are
  placed on a circle, ring connectors are circular arcs cut against the station
  boxes, write-back spokes are radial and dashed, and the canvas is derived.

Paint order is the source's (§5): background → zones → connectors → labels →
nodes → hub → legend. The reveal clock is a single pass in that same order, so
a `reveal` composition builds its diagram in reading order.
"""

from __future__ import annotations

import math

from nanoframes.diagram import geometry as geo
from nanoframes.diagram import scene as scene_mod
from nanoframes.diagram import text as txt
from nanoframes.diagram.scene import Group, Path, Rect, Scene, Text
from nanoframes.diagram.spec import BUDGET_EDGES, BUDGET_NODES, HARD_NODES, Spec
from nanoframes.diagram.tokens import FONT_MONO, FONT_SANS, FONT_SERIF, PRESETS, Tokens

REVEAL_FADE = 0.35
REVEAL_STEP = 0.16
# Visible clearance between an arrow label's ink and its connector stroke
# (source SKILL.md §6 rule 2: 6–10px). Measured from the ink's descent, so a
# CJK label — whose glyphs sit lower than Latin ones — keeps the same gap.
ARROW_GAP = 8.0
LEGEND_H = 60.0
ZONE_PAD = 16.0
ZONE_HEAD = 32.0


class _Builder:
    """Shared scaffolding: reveal clock, warnings, and canvas bookkeeping."""

    def __init__(self, spec: Spec, tokens: Tokens, measurer):
        self.spec = spec
        self.tokens = tokens
        self.measurer = measurer
        self.node_font = FONT_SANS
        self.sub_font = FONT_MONO
        self.warnings: list = []
        self._clock = 0.0

    # -- reveal clock ---------------------------------------------------------
    def slice(self, fade: float = 0.0) -> tuple:
        """Next ``(start, fade)`` in the reveal sequence; ``(0, 0)`` when static."""
        if not self.spec.reveal:
            return 0.0, 0.0
        start = round(self._clock, 2)
        self._clock += REVEAL_STEP
        return start, fade

    # -- shared pieces --------------------------------------------------------
    def background(self, width: float, height: float) -> Group:
        """The paper plate. It is never emitted — ``render`` writes ``#bg`` — but it
        carries the fill, and it must not contribute to the content bounds."""
        g = Group(name="background", start=0.0, fade=0.0)
        g.parts.append(Rect(x=0, y=0, w=width, h=height, fill=self.tokens.paper,
                            fill_opacity=1.0, weight="background"))
        return g

    def title_block(self) -> list:
        """Left-aligned serif title and sans subtitle — the source's page header."""
        t = self.tokens
        out = []
        x = self.spec.margin
        body_top = self.spec.margin
        if self.spec.title:
            out.append(Text(x=x, y=body_top + t.ramp["title"] * 0.78,
                            content=self.spec.title, size=t.ramp["title"],
                            fill=t.ink, family=FONT_SERIF, anchor="start", kind="title"))
        if self.spec.subtitle:
            out.append(Text(x=x, y=body_top + t.ramp["title"] + 22,
                            content=self.spec.subtitle, size=t.ramp["sub"] + 1,
                            fill=t.muted, family=FONT_SANS, anchor="start", kind="sub"))
        return out

    def header_height(self) -> float:
        if not self.spec.title and not self.spec.subtitle:
            return 0.0
        t = self.tokens
        h = t.ramp["title"] + 12
        if self.spec.subtitle:
            h += 26
        return h + 16  # breathing room between the header block and the figure

    def legend(self, width: float, items: list):
        """Horizontal legend strip at the bottom (never floating inside the art).

        The strip hangs off the canvas bottom, which is only known once content
        is measured — so this returns a placer the Builder calls at the end.
        """
        if not items:
            return None

        def place(scene: Scene) -> None:
            t = self.tokens
            g = Group(name="legend", start=0.0, fade=0.0)
            top = scene.height - LEGEND_H + 20
            g.parts.append(Rect(x=self.spec.margin, y=top - 8,
                                w=max(0.0, scene.width - 2 * self.spec.margin),
                                h=0.8, fill=t.rule, fill_opacity=0.12, weight="line"))
            x = self.spec.margin
            for label, fill, stroke, dash in items:
                g.parts.append(Rect(x=x, y=top + 2, w=16, h=10, fill=fill,
                                    fill_opacity=0.9, stroke=stroke, stroke_width=0.8,
                                    rx=2, dash=dash, weight="chip"))
                g.parts.append(Text(x=x + 24, y=top + 11, content=label,
                                    size=t.ramp["tag"] + 1, fill=t.muted,
                                    family=FONT_MONO, anchor="start", kind="tag"))
                width_est = txt.measure(self.measurer, label, FONT_MONO, "400",
                                        t.ramp["tag"] + 1).width
                x += 24 + width_est + 32
            scene.groups.append(g)

        return place

    def to_scene(self, groups: list, minimum: tuple | None = None,
                 place=None, centre_on: tuple | None = None) -> Scene:
        scene = Scene(width=0.0, height=0.0, fps=self.spec.fps,
                      duration=self.duration(), background=self.tokens.paper)
        scene.groups = groups
        scene.warnings = list(self.warnings)
        _finish(scene, self.spec, minimum, centre_on=centre_on)
        if place is not None:
            place(scene)
        return scene

    def duration(self) -> float:
        if self.spec.duration is not None:
            return self.spec.duration
        if not self.spec.reveal:
            return 1.0
        return round(max(1.0, self._clock + REVEAL_FADE + 0.2), 2)


def _finish(scene: Scene, spec: Spec, minimum: tuple | None = None,
            centre_on: tuple | None = None) -> Scene:
    # `centre_on` is the ideal hub centre the ring was authored around; the
    # figure is re-centred on the drawn hub once the canvas width is known.
    """Place the content on its margin and normalize the canvas size.

    The shift applied here is *only* what is needed to keep content inside the
    margin (rounded onto the 4px grid), so a spec authored on the grid keeps its
    alignment — an author's coordinates are honoured, not re-based. An explicit
    canvas is a *minimum*: content that would spill past its edge resizes it, and
    says so. A loop passes ``centre_on`` to have its hub — the figure's visual
    centre — sit on the canvas centre instead.
    """
    x0, y0, x1, y1 = scene_mod.union_bounds(scene)
    # Minimal shift: pin the content edge onto the margin only when it would
    # otherwise fall outside it, so authored grid coordinates stay grid coords.
    dx = 0.0 if x0 >= spec.margin else round(spec.margin - x0, 1)
    dy = 0.0 if y0 >= spec.margin else round(spec.margin - y0, 1)
    scene_mod.translate(scene, dx, dy)
    x0, x1 = x0 + dx, x1 + dx
    min_w = (minimum or (0.0, 0.0))[0]
    min_h = (minimum or (0.0, 0.0))[1]
    scene.width = max(min_w, geo.q4(x1 + spec.margin))
    scene.height = max(min_h, geo.q4(y1 + spec.margin))
    if centre_on is not None:
        # A loop centres its *drawn* hub (the box snap can move it a pixel or
        # two off the ideal centre the geometry was built around) on the canvas.
        drawn_x = _drawn_hub_x(scene)
        if drawn_x is not None:
            shift = round(scene.width / 2.0 - drawn_x, 1)
        else:
            shift = round((scene.width - (x0 + x1)) / 2.0, 1)
        scene_mod.translate(scene, shift, 0.0)
    if scene.width > min_w + 0.01 or scene.height > min_h + 0.01:
        if spec.canvas:
            scene.warnings.append(
                f"content needs {scene.width:g}x{scene.height:g} but the canvas is"
                f" {min_w:g}x{min_h:g} — grew the canvas instead of clipping"
            )
    scene.groups = [g for g in scene.groups if g.name != "background"]
    return scene


def _wants_legend(spec: Spec) -> bool:
    if spec.legend is not None:
        return spec.legend
    return len({n.type for n in spec.nodes}) >= 2


def _legend_space(spec: Spec) -> float:
    return LEGEND_H if _wants_legend(spec) else 0.0


# ---------------------------------------------------------------------------
# flow
# ---------------------------------------------------------------------------


def build_flow(spec: Spec, tokens: Tokens, measurer) -> Scene:
    b = _Builder(spec, tokens, measurer)
    t = tokens
    if len(spec.nodes) > HARD_NODES:
        raise ValueError(
            f"{len(spec.nodes)} nodes: above {HARD_NODES} the source rule is to split into an"
            " overview plus one detail diagram (never one canvas)"
        )
    if len(spec.nodes) > BUDGET_NODES:
        b.warnings.append(
            f"{len(spec.nodes)} nodes over the {BUDGET_NODES}-node budget — zone them"
            " (nodes[].zone) or split into overview + detail"
        )
    if len(spec.edges) > BUDGET_EDGES:
        b.warnings.append(f"{len(spec.edges)} edges over the {BUDGET_EDGES}-edge budget")
    focals = [n for n in spec.nodes if n.focal]
    if len(focals) > 2:
        b.warnings.append(
            f"{len(focals)} focal nodes; the accent is editorial — 1–2 per diagram"
        )

    # -- resolve geometry -----------------------------------------------------
    boxes: dict = {}
    for node in spec.nodes:
        size = _node_size(b, node)
        x, y = geo.q4(node.x or 0.0), geo.q4(node.y or 0.0)
        if not (geo.on_grid(node.x or 0.0) and geo.on_grid(node.y or 0.0)):
            b.warnings.append(
                f"node {node.id!r}: position ({node.x:g},{node.y:g}) snapped to the 4px grid"
                f" -> ({x:g},{y:g})"
            )
        boxes[node.id] = (x, y) + size

    left = min(bx for bx, _, _, _ in boxes.values())
    top = min(by for _, by, _, _ in boxes.values())
    right = max(bx + bw for bx, _, bw, _ in boxes.values())
    bottom = max(by + bh for _, by, _, bh in boxes.values())
    content_w = right - left + 2 * spec.margin
    content_h = (bottom - top + 2 * spec.margin
                 + b.header_height() + _legend_space(spec))
    minimum = (spec.canvas or
               ((max(PRESETS[spec.preset][0], geo.q4(content_w)),
                 max(PRESETS[spec.preset][1], geo.q4(content_h)))
                if spec.preset and spec.preset in PRESETS
                else (geo.q4(content_w), geo.q4(content_h))))

    groups = [b.background(minimum[0], minimum[1])]

    for node in spec.nodes:                      # zones, in spec order
        g = _zone_group(b, spec, node, boxes)
        if g is not None and g not in groups:
            g.start, g.fade = b.slice(0.0)
            groups.append(g)

    labels = []
    for edge in spec.edges:                      # connectors, then their labels
        path = _route_edge(b, spec, boxes, edge)
        g = Group(name=f"edge:{edge.source}->{edge.target}")
        g.start, g.fade = b.slice(REVEAL_FADE)
        g.parts.append(path)
        groups.append(g)
        if edge.label:
            labels.append(_edge_label_group(b, path, edge, *b.slice(REVEAL_FADE)))

    for node in spec.nodes:                      # nodes last (they mask connectors)
        x, y, w, h = boxes[node.id]
        g = Group(name=f"node:{node.id}")
        g.start, g.fade = b.slice(REVEAL_FADE)
        g.parts.append(Rect(x=x, y=y, w=w, h=h, rx=6.0, weight="box",
                            **t.node_style(node.type)))
        g.parts += txt.node_texts(
            b.measurer, x, y, w, h, node.label, node.sub, node.tag, t.ramp,
            b.node_font, b.sub_font, t.ink, t.muted, t.soft, t.accent, focal=node.focal)
        groups.append(g)

    groups += labels
    head = Group(name="header", start=0.0, fade=0.0)
    head.parts += b.title_block()
    if head.parts:
        groups.append(head)
    return b.to_scene(groups, minimum=minimum,
                      place=b.legend(minimum[0], _legend_items(spec)))


def _legend_items(spec: Spec) -> list:
    if not _wants_legend(spec):
        return []
    from nanoframes.diagram.tokens import resolve

    t = resolve(spec.skin, spec.preset)
    items = []
    seen = []
    for node in spec.nodes:
        if node.type in seen:
            continue
        seen.append(node.type)
        style = t.node_style(node.type)
        items.append((node.type.upper(), style["fill"], style["stroke"], style.get("dash")))
    styles: list = []
    for edge in spec.edges:
        if edge.style == "default" or edge.style in styles:
            continue
        styles.append(edge.style)
        style = t.edge_style(edge.style)
        items.append((edge.style.upper(), style["stroke"], style["stroke"], style["dash"]))
    return items


def _node_size(b: _Builder, node) -> tuple:
    t = b.tokens
    w, h = txt.box_size(b.measurer, node.label, node.sub, node.tag, t.ramp,
                        b.node_font, b.sub_font)
    if node.w:
        w = max(40.0, float(node.w))
    if node.h:
        h = max(32.0, float(node.h))
    return w, h


# -- connectors --------------------------------------------------------------


def _port_point(box: tuple, side: str, offset_ratio: float) -> tuple:
    """A point on ``side`` of a box at ``offset_ratio`` (0..1) along that edge."""
    x, y, w, h = box
    if side == "right":
        return (x + w, y + h * offset_ratio)
    if side == "left":
        return (x, y + h * offset_ratio)
    if side == "down":
        return (x + w * offset_ratio, y + h)
    return (x + w * offset_ratio, y)


def _choose_ports(box_a: tuple, box_b: tuple, edge) -> tuple:
    if edge.from_port and edge.to_port:
        return edge.from_port, edge.to_port
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    dx = (bx + bw / 2.0) - (ax + aw / 2.0)
    dy = (by + bh / 2.0) - (ay + ah / 2.0)
    if edge.from_port:
        return edge.from_port, _opposite(edge.from_port, dx, dy)
    if edge.to_port:
        return _opposite(edge.to_port, dx, dy), edge.to_port
    if abs(dx) >= abs(dy):
        return ("right" if dx >= 0 else "left"), ("left" if dx >= 0 else "right")
    return ("down" if dy >= 0 else "up"), ("up" if dy >= 0 else "down")


def _opposite(side: str, dx: float, dy: float) -> str:
    """The natural partner side for a given port and node delta."""
    if side in ("left", "right"):
        return ("left" if dx >= 0 else "right")
    return ("up" if dy >= 0 else "down")


def _route_edge(b: _Builder, spec: Spec, boxes: dict, edge) -> Path:
    """Route one connector: port fanning, rounded elbow path, explicit arrowhead."""
    t = b.tokens
    a_side, b_side = _choose_ports(boxes[edge.source], boxes[edge.target], edge)
    fan_out = [e for e in spec.edges if e.source == edge.source
               and _choose_ports(boxes[e.source], boxes[e.target], e)[0] == a_side]
    fan_in = [e for e in spec.edges if e.target == edge.target
              and _choose_ports(boxes[e.source], boxes[e.target], e)[1] == b_side]
    a_ratio = (fan_out.index(edge) + 1) / (len(fan_out) + 1)
    b_ratio = (fan_in.index(edge) + 1) / (len(fan_in) + 1)
    a = _port_point(boxes[edge.source], a_side, a_ratio)
    z = _port_point(boxes[edge.target], b_side, b_ratio)
    points, _ = geo.elbow(a, z, a_side, b_side)
    style = t.edge_style(edge.style)
    path = Path(d=geo.path_d(points), stroke=style["stroke"],
                stroke_width=style["width"], dash=style["dash"], points=points)
    if style["head"] == "filled":
        path.head, path.head_at = geo.arrowhead(points)
        path.head_fill = style["stroke"]
    else:
        path.head = geo.open_head(points)
        path.head_fill = None
        path.head_at = geo.end_tangent(points)
    return path


def _edge_label_group(b: _Builder, path: Path, edge, start: float, fade: float) -> Group:
    """Masked arrow label with the source's mandatory 6–10px stroke clearance."""
    t = b.tokens
    g = Group(name=f"label:{edge.source}->{edge.target}", start=start, fade=fade)
    metrics = txt.measure(b.measurer, edge.label.upper(), FONT_MONO, "400",
                          t.ramp["arrow"])
    (anc_x, anc_y), orientation, _ = geo.label_anchor(
        path.points, ARROW_GAP, edge.label_side or "",
        descent=metrics.bottom, ascent=-metrics.top)
    run = Text(x=round(anc_x, 1), y=round(anc_y, 1), content=edge.label.upper(),
               size=t.ramp["arrow"], fill=t.muted, family=FONT_MONO,
               anchor="middle" if orientation == "h" else "start",
               kind="arrow", mask=True)
    box = txt.text_box(run, b.measurer)
    g.parts.append(Rect(x=box[0], y=box[1], w=box[2], h=box[3], rx=2.0,
                        fill=t.paper, fill_opacity=1.0, weight="chip"))
    g.parts.append(run)
    return g

# -- zones -------------------------------------------------------------------


def _zone_group(b: _Builder, spec: Spec, node, boxes: dict):
    """The zone group for ``node``'s zone (built once, when its first member is seen)."""
    if not node.zone:
        return None
    t = b.tokens
    zone = next((z for z in spec.zones if z.id == node.zone), None)
    if zone is None:
        return None
    members = [boxes[n.id] for n in spec.nodes if n.zone == zone.id and n.id in boxes]
    if not members:
        b.warnings.append(f"zone {zone.id!r} contains no nodes")
        return None
    x0 = min(m[0] for m in members) - ZONE_PAD
    y0 = min(m[1] for m in members) - ZONE_HEAD
    x1 = max(m[0] + m[2] for m in members) + ZONE_PAD
    y1 = max(m[1] + m[3] for m in members) + ZONE_PAD
    x, y = geo.q4(x0), geo.q4(y0)
    w, h = geo.q4(x1 - x), geo.q4(y1 - y)
    g = Group(name=f"zone:{zone.id}")
    g.parts.append(Rect(x=x, y=y, w=w, h=h, rx=8.0, weight="zone",
                        fill=t.zone_fill[0], fill_opacity=t.zone_fill[1],
                        stroke=t.zone_stroke[0], stroke_opacity=t.zone_stroke[1],
                        stroke_width=0.8))
    label = zone.label.upper()
    tracking = round(0.14 * t.ramp["tag"], 2)
    run_w = txt.visual_width(b.measurer, label, FONT_MONO, "400", t.ramp["tag"],
                             0.14, tracking)
    mask_w = run_w + 8
    g.parts.append(Rect(x=x + 12, y=y + 4, w=round(mask_w, 1), h=12, rx=2,
                        fill=t.paper, fill_opacity=1.0, weight="chip"))
    g.parts += txt.tracked_parts(x + 12 + mask_w / 2.0, y + 13, label,
                                 t.ramp["tag"], t.muted, FONT_MONO, tracking,
                                 anchor="middle", kind="eyebrow")
    return g


# ---------------------------------------------------------------------------
# loop
# ---------------------------------------------------------------------------


def build_loop(spec: Spec, tokens: Tokens, measurer) -> Scene:
    b = _Builder(spec, tokens, measurer)
    t = tokens
    loop = spec.loop
    stations = loop.stations
    n = len(stations)

    sizes: dict = {}
    for st in stations:
        w, h = txt.box_size(measurer, st.label, st.sub, st.tag, t.ramp,
                            b.node_font, b.sub_font)
        sizes[st.id] = (loop.station_w or w, loop.station_h or h)
    hub_w, hub_h = loop.hub_w or 200.0, loop.hub_h or 104.0
    hub_label_w, hub_label_h = txt.box_size(measurer, loop.hub_label, loop.hub_sub, "",
                                            t.ramp, b.node_font, b.sub_font)
    hub_w, hub_h = _snap_hub(max(hub_w, hub_label_w)), _snap_hub(max(hub_h, hub_label_h))

    max_st_w = max(s[0] for s in sizes.values())
    max_st_h = max(s[1] for s in sizes.values())
    radius = max(loop.radius, hub_w / 2.0 + 40.0, max_st_w / 2.0 + 40.0)
    # The ring is authored at a fixed distance below the title band; `_finish`
    # then centres it horizontally on the canvas, so only vertical placement is
    # the builder's business.
    top = spec.margin + b.header_height()
    centre = (max_st_w / 2.0 + spec.margin, top + max_st_h / 2.0 + radius)
    content = (geo.q4(2 * (max_st_w / 2.0 + spec.margin) + 2 * radius),
               geo.q4(top + 2 * radius + max_st_h / 2.0 + spec.margin))
    minimum = spec.canvas or (
        (max(PRESETS[spec.preset][0], content[0]),
         max(PRESETS[spec.preset][1], content[1] + _legend_space(spec)))
        if spec.preset and spec.preset in PRESETS
        else (content[0], content[1] + _legend_space(spec))
    )
    cx, cy = centre

    boxes: dict = {}
    for k, st in enumerate(stations):
        theta = math.radians(-90.0 + k * 360.0 / n)
        w, h = sizes[st.id]
        size_x, size_y = geo.q4(cx + radius * math.cos(theta) - w / 2.0), \
            geo.q4(cy + radius * math.sin(theta) - h / 2.0)
        boxes[st.id] = (size_x, size_y, w, h)

    # -- ring arcs + write-back spokes ---------------------------------------
    arcs = []
    for k in range(n):
        here, nxt = stations[k], stations[(k + 1) % n]
        theta_here = -90.0 + k * 360.0 / n
        theta_next = -90.0 + ((k + 1) % n) * 360.0 / n
        p_exit = _circle_box_point(boxes[here.id], cx, cy, radius, theta_here, exit_side=True)
        p_entry = _circle_box_point(boxes[nxt.id], cx, cy, radius, theta_next, exit_side=False)
        if p_exit is None or p_entry is None:
            b.warnings.append(
                f"ring arc {here.id}->{nxt.id}: station box does not meet the ring —"
                " increase radius or shrink the station"
            )
            continue
        phi_end = math.atan2(p_entry[1] - cy, p_entry[0] - cx) - 1.2 / radius
        end = (cx + radius * math.cos(phi_end), cy + radius * math.sin(phi_end))
        arc = Path(d=(f"M {geo.r2(p_exit[0])},{geo.r2(p_exit[1])}"
                      f" A {radius:g} {radius:g} 0 0 1 {geo.r2(end[0])},{geo.r2(end[1])}"),
                   stroke=t.muted, stroke_width=1.2, points=[p_exit, p_entry])
        arc.head, arc.head_at = _head_at(end, math.degrees(phi_end) + 90.0)
        arc.head_fill = t.muted
        arcs.append(arc)

    spokes = []
    for k, st in enumerate(stations):
        theta = math.radians(-90.0 + k * 360.0 / n)
        u = (math.cos(theta), math.sin(theta))
        w, h = sizes[st.id]
        d_st = _box_distance(u, w / 2.0, h / 2.0)
        d_hub = _box_distance(u, hub_w / 2.0, hub_h / 2.0)
        # True radii: both endpoints are cast from the ideal ring centre, not the
        # grid-snapped box centre, so the spoke has no angular wobble. The start
        # lands on the station's inner edge; the end stops `marker_gap` short of
        # the hub stroke so the lighter head does not collide with it.
        start = (cx + (radius - d_st) * u[0], cy + (radius - d_st) * u[1])
        end = (cx + (d_hub + 6.0) * u[0], cy + (d_hub + 6.0) * u[1])
        spoke = Path(d=(f"M {geo.r2(start[0])},{geo.r2(start[1])}"
                        f" L {geo.r2(end[0])},{geo.r2(end[1])}"),
                     stroke=t.soft, stroke_width=1.0, dash="5,4", points=[start, end])
        spoke.head, spoke.head_at = _head_at(end, math.degrees(theta) + 180.0)
        spoke.head_fill = t.soft
        spokes.append(spoke)

    # -- canvas --------------------------------------------------------------
    groups = [b.background(minimum[0], minimum[1])]
    for k, arc in enumerate(arcs):
        g = Group(name=f"ring:{stations[k].id}->{stations[(k + 1) % n].id}")
        g.start, g.fade = b.slice(0.0)
        g.parts.append(arc)
        groups.append(g)
    for k, spoke in enumerate(spokes):
        g = Group(name=f"spoke:{stations[k].id}")
        g.start, g.fade = b.slice(0.0)
        g.parts.append(spoke)
        groups.append(g)

    hub = Group(name="hub")
    hub.start, hub.fade = b.slice(REVEAL_FADE)
    hub_x, hub_y = geo.q4(cx - hub_w / 2.0), geo.q4(cy - hub_h / 2.0)
    hub.parts.append(Rect(x=hub_x, y=hub_y, w=hub_w, h=hub_h, rx=8.0, weight="box",
                          fill=t.ink, fill_opacity=1.0, stroke=t.ink, stroke_opacity=1.0))
    hub.parts += txt.node_texts(b.measurer, hub_x, hub_y, hub_w, hub_h,
                                loop.hub_label, loop.hub_sub, "", t.ramp,
                                b.node_font, b.sub_font, t.paper, t.paper, t.paper, t.accent)
    groups.append(hub)

    for st in stations:
        x, y, w, h = boxes[st.id]
        g = Group(name=f"node:{st.id}")
        g.start, g.fade = b.slice(REVEAL_FADE)
        g.parts.append(Rect(x=x, y=y, w=w, h=h, rx=6.0, weight="box",
                            **t.node_style("focal" if st.focal else "backend")))
        g.parts += txt.node_texts(
            b.measurer, x, y, w, h, st.label, st.sub, st.tag, t.ramp,
            b.node_font, b.sub_font, t.ink, t.muted, t.soft, t.accent, focal=st.focal)
        groups.append(g)

    items = [("STATION", "#ffffff" if t.skin == "light" else t.paper_2, t.ink, None),
             ("WRITE-BACK", t.soft, t.soft, "5,4")]
    if any(st.focal for st in stations):
        items.insert(0, ("FOCAL", t.accent, t.accent, None))
    head = Group(name="header", start=0.0, fade=0.0)
    head.parts += b.title_block()
    if head.parts:
        groups.append(head)
    return b.to_scene(groups, minimum=minimum, place=b.legend(minimum[0], items),
                      centre_on=(cx, cy))


def _drawn_hub_x(scene: Scene):
    """Centre x of the hub box as drawn, or None when the scene has no hub."""
    for group in scene.groups:
        if group.name != "hub":
            continue
        for part in group.parts:
            if isinstance(part, Rect) and part.weight == "box":
                return part.x + part.w / 2.0
    return None


def _snap_hub(value: float) -> float:
    """Hub dimension rounded to the 4px grid *and* to an even count of grid cells.

    Nodes only need positions modulo 4 (the grid rule). The hub needs its
    half-width to be a grid multiple too: it is centred on a grid point through
    ``q4(cx - w/2)``, and an even width keeps that snap at the true centre — so
    the ring and hub stay concentric.
    """
    return float(-(-int(value) // 8) * 8)


# -- loop geometry -----------------------------------------------------------


def _box_distance(u: tuple, half_w: float, half_h: float) -> float:
    """Distance from a box center to its edge along unit direction ``u``."""
    terms = []
    if abs(u[0]) > 1e-9:
        terms.append(half_w / abs(u[0]))
    if abs(u[1]) > 1e-9:
        terms.append(half_h / abs(u[1]))
    return min(terms) if terms else 0.0


def _circle_box_point(box: tuple, cx: float, cy: float, radius: float,
                      theta_deg: float, exit_side: bool):
    """Where the station circle leaves / enters a station box.

    Intersects the circle with the box's four edges, keeps the candidates on the
    box, and returns the one just clockwise of the station's own angle
    (``exit_side``) or just counter-clockwise of it (entry).
    """
    x, y, w, h = box
    candidates = []
    for x_e in (x, x + w):
        if abs(x_e - cx) <= radius:
            dy = math.sqrt(max(0.0, radius * radius - (x_e - cx) ** 2))
            for yy in (cy + dy, cy - dy):
                if y - 0.01 <= yy <= y + h + 0.01:
                    candidates.append((x_e, yy))
    for y_e in (y, y + h):
        if abs(y_e - cy) <= radius:
            dx = math.sqrt(max(0.0, radius * radius - (y_e - cy) ** 2))
            for xx in (cx + dx, cx - dx):
                if x - 0.01 <= xx <= x + w + 0.01:
                    candidates.append((xx, y_e))
    if not candidates:
        return None
    angles = [(math.degrees(math.atan2(p[1] - cy, p[0] - cx)) % 360.0, p) for p in candidates]
    theta = theta_deg % 360.0
    if exit_side:
        after = [a for a in angles if (a[0] - theta) % 360.0 > 1e-6]
        return min(after, key=lambda a: (a[0] - theta) % 360.0)[1] if after else None
    before = [a for a in angles if (theta - a[0]) % 360.0 > 1e-6]
    return min(before, key=lambda a: (theta - a[0]) % 360.0)[1] if before else None


def _head_at(tip: tuple, deg: float) -> tuple:
    """Arrowhead polygon at an explicit tip and tangent (arcs and spokes)."""
    rad = math.radians(deg)
    ux, uy = math.cos(rad), math.sin(rad)
    tip_pt = (tip[0] + ux * geo.ARROW_TIP, tip[1] + uy * geo.ARROW_TIP)
    base = (tip_pt[0] - ux * geo.ARROW_LEN, tip_pt[1] - uy * geo.ARROW_LEN)
    nx, ny = -uy, ux
    p1 = (base[0] + nx * geo.ARROW_HALF, base[1] + ny * geo.ARROW_HALF)
    p2 = (base[0] - nx * geo.ARROW_HALF, base[1] - ny * geo.ARROW_HALF)
    pts = " ".join(f"{geo.r2(p[0])},{geo.r2(p[1])}" for p in (tip_pt, p1, p2))
    return pts, (tip_pt[0], tip_pt[1], deg)


def build_scene(spec: Spec, measurer=None) -> Scene:
    """Build the scene for any spec kind."""
    from nanoframes.diagram.tokens import resolve

    tokens = resolve(spec.skin, spec.preset)
    if spec.kind == "flow":
        return build_flow(spec, tokens, measurer)
    if spec.kind == "loop":
        return build_loop(spec, tokens, measurer)
    raise ValueError(f"unknown diagram kind {spec.kind!r}")

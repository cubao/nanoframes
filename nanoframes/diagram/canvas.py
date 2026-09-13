"""The page a diagram grammar draws on — shared machinery, not a grammar.

A *grammar* is one compiler: its own spec plus its own data→geometry algorithm,
producing the same :class:`~nanoframes.diagram.scene.Scene`. Everything a
grammar shares lives here: the reveal clock, the warning channel, the page
furniture (paper, title band, legend, canvas sizing), measured box sizing,
node-type legend items, connector rendering and the hand-drawn registers.
Geometry *rules* (the grid, elbow routing, arrowheads) are in ``geometry``;
tokens (colors, ramp, presets) are in ``tokens``.

The point of the split is that a new grammar is a new algorithm, not a new
renderer: it computes boxes and connectors, calls :class:`Canvas` for the page
and ``nanoframes.diagram.emit.render`` for the SVG, and inherits the grid,
measured text, reveal animation and every ThorVG workaround unchanged.

Paint order is the source's (SKILL.md §5) and every grammar holds it:
background → zones → connectors → labels → nodes → header, with the reveal
clock running in that same order so a revealed composition builds in reading
order.
"""

from __future__ import annotations

from nanoframes.diagram import geometry as geo
from nanoframes.diagram import scene as scene_mod
from nanoframes.diagram import sketchy
from nanoframes.diagram import text as txt
from nanoframes.diagram.scene import Group, Path, Rect, Scene, Text
from nanoframes.diagram.spec import Spec
from nanoframes.diagram.tokens import FONT_MONO, FONT_SANS, FONT_SERIF, Tokens

REVEAL_FADE = 0.35
REVEAL_STEP = 0.16
LEGEND_H = 60.0
# Only a preset-sized canvas (or an explicit one) is worth centring
# a small figure in; below this much slack the figure just sits at the top.
CENTRE_MIN_SLACK = 320.0


class Canvas:
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
        """Height of the title band laid out above the figure (see `header_height`)."""
        return header_height(self.spec)

    def legend(self, width: float, items: list):
        """Horizontal legend strip at the bottom (never floating inside the art).

        The strip hangs off the canvas bottom, which is only known once content
        is measured — so this returns a placer the Canvas calls at the end.
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
        finish(scene, self.spec, minimum, centre_on=centre_on)
        if place is not None:
            place(scene)
        return scene

    def duration(self) -> float:
        if self.spec.duration is not None:
            return self.spec.duration
        if not self.spec.reveal:
            return 1.0
        return round(max(1.0, self._clock + REVEAL_FADE + 0.2), 2)


def finish(scene: Scene, spec: Spec, minimum: tuple | None = None,
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
    header = header_height(spec)
    figure_top = y0 + dy
    slack = min_h - (header + (y1 + dy - figure_top) + 2 * spec.margin)
    if slack > CENTRE_MIN_SLACK and figure_top >= header + spec.margin - 1:
        # A preset (or taller explicit canvas) leaves vertical slack: centre the
        # *figure* in the space below the title band rather than parking it at
        # the top with one large void underneath. The header stays put.
        scene_mod.translate(scene, 0.0, round(slack / 2.0, 1))
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


def _drawn_hub_x(scene: Scene):
    """Centre x of the hub box as drawn, or None when the scene has no hub."""
    for group in scene.groups:
        if group.name != "hub":
            continue
        for part in group.parts:
            if isinstance(part, Rect) and part.weight == "box":
                return part.x + part.w / 2.0
    return None


def header_height(spec: Spec) -> float:
    """Height of the title band laid out above the figure.

    A spec-level question, so both the builder and `finish`'s centring step ask
    this one function instead of keeping two copies of the arithmetic in sync.
    """
    if not spec.title and not spec.subtitle:
        return 0.0
    ramp = resolve_ramp(spec)
    h = ramp["title"] + 12
    if spec.subtitle:
        h += 26
    return h + 16


def resolve_ramp(spec: Spec) -> dict:
    from nanoframes.diagram.tokens import resolve

    return resolve(spec.skin, spec.preset).ramp


# ---------------------------------------------------------------------------
# sketchy (hand-drawn) shapes
# ---------------------------------------------------------------------------


def rough(tokens: Tokens) -> bool:
    """Whether this skin draws with hand-drawn strokes."""
    return tokens.skin == "sketchy"


def box_parts(x: float, y: float, w: float, h: float, name: str, style: dict,
              tokens: Tokens, rx: float = 6.0, weight: str = "box") -> list:
    """A node box: a crisp ``Rect``, or a plate plus hand-drawn outline.

    One place decides what "this skin draws a box" means, so a new skin changes
    it once instead of in every caller.
    """
    if not rough(tokens):
        return [Rect(x=x, y=y, w=w, h=h, rx=rx, weight=weight, **style)]
    parts = [Rect(x=x, y=y, w=w, h=h, rx=rx, weight=weight,
                  fill=style["fill"], fill_opacity=style["fill_opacity"])]
    parts += _sketchy_paths(x, y, w, h, name, _sketchy_style(style), tokens)
    return parts


def _sketchy_paths(x: float, y: float, w: float, h: float, name: str, style: dict,
                   tokens: Tokens) -> list:
    """A hand-drawn rectangle outline, styled like the ``Rect`` it replaces."""
    out = []
    for i, d in enumerate(sketchy.rough_rect(x, y, w, h, name)):
        # The second pass is lighter, like a re-traced edge.
        width = style["stroke_width"] * (0.7 if i >= 4 else 1.0)
        out.append(Path(d=d, stroke=style["stroke"], stroke_width=width,
                        dash=style.get("dash"), opacity=style.get("stroke_opacity", 1.0)))
    return out


def _sketchy_style(style: dict) -> dict:
    """``node_style``'s dict as a stroke style for a rough outline."""
    return {"stroke": style["stroke"],
            "stroke_opacity": style["stroke_opacity"],
            "stroke_width": style.get("stroke_width", 1.0) + 0.9,
            "dash": style.get("dash")}


# ---------------------------------------------------------------------------
# connectors
# ---------------------------------------------------------------------------


def connector_path(points: list, style: dict, tokens: Tokens, name: str) -> Path:
    """One orthogonal connector as a ``Path``, arrowhead included.

    The route (which points) belongs to the grammar; turning a polyline into a
    drawn path does not — the elbow corners, the hand-drawn wobble and the
    polygon arrowhead ThorVG needs instead of ``<marker>`` are shared.
    """
    if rough(tokens):
        # Hand-drawn connectors: each leg bows, corners stay on the elbow points.
        d = ""
        for i in range(len(points) - 1):
            (x1, y1), (x2, y2) = points[i], points[i + 1]
            d += sketchy.wobbly_line(x1, y1, x2, y2, sketchy._seed(name), i)
        path = Path(d=d, stroke=style["stroke"], stroke_width=style["width"] + 0.4,
                    dash=style["dash"], points=points)
    else:
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


# ---------------------------------------------------------------------------
# nodes and the legend
# ---------------------------------------------------------------------------


def node_size(measurer, node, ramp: dict, font_label: str, font_sub: str) -> tuple:
    """Auto-sized node box ``(w, h)``: measured text, or the spec's explicit size."""
    w, h = txt.box_size(measurer, node.label, node.sub, node.tag, ramp,
                        font_label, font_sub)
    if node.w:
        w = max(40.0, float(node.w))
    if node.h:
        h = max(32.0, float(node.h))
    return w, h


def wants_legend(spec: Spec, nodes: list) -> bool:
    """The legend is on when asked for, or when 2+ visual kinds are in use."""
    if spec.legend is not None:
        return spec.legend
    return len({n.type for n in nodes}) >= 2


def legend_space(spec: Spec, nodes: list) -> float:
    return LEGEND_H if wants_legend(spec, nodes) else 0.0


def type_items(nodes: list, tokens: Tokens) -> list:
    """Legend swatches for the node types actually used, in first-seen order."""
    items = []
    seen: list = []
    for node in nodes:
        if node.type in seen:
            continue
        seen.append(node.type)
        style = tokens.node_style(node.type)
        items.append((node.type.upper(), style["fill"], style["stroke"], style.get("dash")))
    return items

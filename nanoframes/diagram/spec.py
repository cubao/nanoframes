"""The diagram spec — the one input surface for `nanoframes diagram`.

A spec is a small JSON document (the source type references are written against
YAML snippets; JSON keeps nanoframes dependency-free and matches the timeline
JSON the rest of the package already speaks):

```json
{
  "diagram": "flow",
  "preset": "doc-wide",
  "title": "Ingest path",
  "nodes": [
    {"id": "edge", "label": "Edge", "sub": "cdn", "x": 80, "y": 200, "type": "external"},
    {"id": "api",  "label": "API Gateway", "sub": ":8443", "x": 320, "y": 200, "type": "focal"}
  ],
  "edges": [{"from": "edge", "to": "api", "label": "TLS"}]
}
```

Layout is explicit for ``flow`` (the agent places nodes; the builder owns every
box, connector, mask and arrowhead) and computed for ``loop`` (the ring, the
spokes and the canvas), ``tree`` (a nested hierarchy, laid out by the
Reingold–Tilford algorithm in ``nanoframes.diagram.tree``) and ``chart`` (a data
table, scaled and ticked by ``nanoframes.diagram.chart``). Everything invalid
is reported as a named warning or error in :class:`SpecError` — never as a
silent misdraw.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

KINDS = ("flow", "loop", "tree", "chart")
NODE_TYPES = ("focal", "backend", "store", "external", "input", "optional", "security")
EDGE_STYLES = ("default", "accent", "link", "dashed", "async", "return")
CHART_TYPES = ("bar", "line")

# Complexity budget (source SKILL.md §7): above the soft ceiling the diagram is
# probably two diagrams; the hard ceiling always splits.
BUDGET_NODES = 9
BUDGET_EDGES = 12
HARD_NODES = 24
LOOP_STATIONS = (5, 8)


class SpecError(ValueError):
    """Spec is unusable — raised with every problem found, not just the first."""

    def __init__(self, problems: list):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass
class NodeSpec:
    id: str
    label: str
    sub: str = ""
    tag: str = ""
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    type: str = "backend"
    zone: str | None = None
    focal: bool = False


@dataclass
class TreeNodeSpec:
    """One box of a hierarchy, plus its reports — no coordinates, ever.

    Same three text slots and node ``type`` vocabulary as :class:`NodeSpec`; the
    difference is the recursive shape, which is the input its layout algorithm
    actually needs.
    """

    id: str
    label: str
    sub: str = ""
    tag: str = ""
    w: float | None = None
    h: float | None = None
    type: str = "backend"
    focal: bool = False
    children: list = field(default_factory=list)   # list[TreeNodeSpec], left → right


@dataclass
class EdgeSpec:
    source: str
    target: str
    label: str = ""
    style: str = "default"
    from_port: str | None = None   # left|right|up|down
    to_port: str | None = None
    label_side: str | None = None  # h|v


@dataclass
class ZoneSpec:
    id: str
    label: str
    nodes: list = field(default_factory=list)


@dataclass
class LoopSpec:
    hub_label: str = ""
    hub_sub: str = ""
    stations: list = field(default_factory=list)   # list[NodeSpec], clockwise from top
    radius: float = 240.0
    station_w: float | None = None
    station_h: float | None = None
    hub_w: float | None = None
    hub_h: float | None = None


@dataclass
class SeriesSpec:
    """One measured claim: a label, and one number per category.

    There is nowhere in here to put a colour, a coordinate or a scale — the
    chart's whole input is the table, and every rendering decision is derived.
    """

    label: str = ""
    values: list = field(default_factory=list)     # list[float], one per category


@dataclass
class ChartSpec:
    """A data table plus its axis titles — the chart grammar's input."""

    type: str = "bar"                              # bar | line
    categories: list = field(default_factory=list)  # list[str], left to right
    series: list = field(default_factory=list)      # list[SeriesSpec]
    x_label: str = ""
    y_label: str = ""
    unit: str = ""                                  # folded into the y axis title
    grid: bool = True


@dataclass
class Spec:
    kind: str
    skin: str = "light"
    preset: str | None = None
    canvas: tuple | None = None
    title: str = ""
    subtitle: str = ""
    fps: int = 30
    dpi: float | None = None
    duration: float | None = None
    reveal: bool = False
    legend: bool | None = None      # None = auto (show when 2+ visual kinds exist)
    margin: float = 40.0
    nodes: list = field(default_factory=list)
    zones: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    loop: LoopSpec | None = None
    tree: TreeNodeSpec | None = None
    chart: ChartSpec | None = None
    h_gap: float | None = None      # tree: air between two neighbouring subtrees
    v_gap: float | None = None      # tree: air below a row of boxes


def parse_spec(data: dict) -> Spec:
    """Validate a spec dict into a :class:`Spec` (raises :class:`SpecError`)."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise SpecError(["the spec must be a JSON object"])
    kind = data.get("diagram")
    if kind not in KINDS:
        raise SpecError([f'"diagram" must be one of {", ".join(KINDS)} (got {kind!r})'])

    spec = Spec(kind=kind)
    spec.skin = str(data.get("skin", "light"))
    spec.preset = data.get("preset")
    canvas = data.get("canvas")
    if isinstance(canvas, dict):
        w, h = canvas.get("width"), canvas.get("height")
        if not (isinstance(w, (int, float)) and isinstance(h, (int, float)) and w > 0 and h > 0):
            problems.append('canvas needs positive "width" and "height"')
        else:
            spec.canvas = (float(w), float(h))
    elif canvas is not None:
        problems.append('"canvas" must be an object like {"width": 960, "height": 600}')
    spec.title = str(data.get("title", ""))
    spec.subtitle = str(data.get("subtitle", ""))
    fps = data.get("fps", 30)
    if not (isinstance(fps, (int, float)) and fps > 0):
        problems.append(f'"fps" must be positive (got {fps!r})')
    else:
        spec.fps = int(fps)
    dpi = data.get("dpi")
    if dpi is None:
        pass
    elif isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or dpi <= 0:
        problems.append(f'"dpi" must be a positive number (got {dpi!r})')
    else:
        spec.dpi = float(dpi)
    duration = data.get("duration")
    if duration is not None and not (isinstance(duration, (int, float)) and duration > 0):
        problems.append(f'"duration" must be positive seconds (got {duration!r})')
    else:
        spec.duration = float(duration) if duration is not None else None
    spec.reveal = bool(data.get("reveal", False))
    legend = data.get("legend")
    if legend is not None and not isinstance(legend, bool):
        problems.append(f'"legend" must be true/false (got {legend!r})')
    else:
        spec.legend = legend
    margin = data.get("margin", 40.0)
    if not (isinstance(margin, (int, float)) and margin >= 0):
        problems.append(f'"margin" must be >= 0 (got {margin!r})')
    else:
        spec.margin = float(margin)

    if spec.preset is not None:
        from nanoframes.diagram.tokens import PRESETS

        if spec.preset not in PRESETS and spec.preset != "fit":
            problems.append(
                f'unknown preset {spec.preset!r}; known: fit, {", ".join(sorted(PRESETS))}'
            )

    zones: dict[str, ZoneSpec] = {}
    for i, raw in enumerate(data.get("zones", []) or []):
        if not isinstance(raw, dict):
            problems.append(f"zones[{i}] must be an object")
            continue
        zid = str(raw.get("id") or f"zone{i}")
        if zid in zones:
            problems.append(f"duplicate zone id {zid!r}")
            continue
        zones[zid] = ZoneSpec(id=zid, label=str(raw.get("label", zid)),
                              nodes=list(raw.get("nodes", []) or []))
    spec.zones = list(zones.values())

    seen: set[str] = set()
    for i, raw in enumerate(data.get("nodes", []) or []):
        node = _parse_node(raw, f"nodes[{i}]", problems)
        if node is None:
            continue
        if node.id in seen:
            problems.append(f"duplicate node id {node.id!r}")
            continue
        seen.add(node.id)
        if node.zone and node.zone not in zones:
            problems.append(f"node {node.id!r} references unknown zone {node.zone!r}")
        spec.nodes.append(node)

    if kind == "flow":
        if not spec.nodes:
            problems.append('a "flow" diagram needs at least one node')
        for node in spec.nodes:
            if node.x is None or node.y is None:
                problems.append(f'node {node.id!r} needs "x" and "y" (flow layout is explicit)')
        for i, raw in enumerate(data.get("edges", []) or []):
            edge = _parse_edge(raw, i, problems)
            if edge is None:
                continue
            for endpoint, ref in (("from", edge.source), ("to", edge.target)):
                if ref not in seen:
                    problems.append(f'edge {i} ("{endpoint}": {ref!r}) references no node')
            spec.edges.append(edge)
    elif kind == "loop":
        spec.loop = _parse_loop(data.get("loop"), problems)
    elif kind == "tree":
        # The tree grammar's two layout knobs, next to the header like `margin`.
        for field_name in ("h_gap", "v_gap"):
            value = data.get(field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                problems.append(f'"{field_name}" must be positive (got {value!r})')
                continue
            setattr(spec, field_name, float(value))
        spec.tree = _parse_tree(data.get("tree"), problems)
    else:
        spec.chart = _parse_chart(data.get("chart"), problems)

    if problems:
        raise SpecError(problems)
    return spec


def _parse_node(raw, where: str, problems: list) -> NodeSpec | None:
    """One node object, validated. ``where`` names it in every message.

    The caller supplies the path (``nodes[2]``, ``tree.children[0]``) so a bad
    node is reported where the author can see it, in the grammar's own words.
    """
    if not isinstance(raw, dict):
        problems.append(f"{where} must be an object")
        return None
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        problems.append(f'{where} needs a non-empty "label"')
        return None
    nid = raw.get("id")
    if nid is not None and not isinstance(nid, str):
        problems.append(f"{where}.id must be a string")
        return None
    node = NodeSpec(id=nid or _slug(label), label=label.strip())
    node.sub = str(raw.get("sub", ""))
    node.tag = str(raw.get("tag", ""))
    for field_name in ("x", "y", "w", "h"):
        value = raw.get(field_name)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            problems.append(f"node {node.id!r}.{field_name} must be a number (got {value!r})")
            continue
        setattr(node, field_name, float(value))
    node.type = str(raw.get("type", "backend"))
    if node.type not in NODE_TYPES:
        problems.append(
            f"node {node.id!r}: unknown type {node.type!r}; known: {', '.join(NODE_TYPES)}"
        )
    node.zone = raw.get("zone")
    node.focal = bool(raw.get("focal", False)) or node.type == "focal"
    if node.focal:
        node.type = "focal"
    return node


def _parse_edge(raw, index: int, problems: list) -> EdgeSpec | None:
    if not isinstance(raw, dict):
        problems.append(f"edges[{index}] must be an object")
        return None
    source, target = raw.get("from"), raw.get("to")
    if not isinstance(source, str) or not isinstance(target, str):
        problems.append(f'edges[{index}] needs "from" and "to" node ids')
        return None
    edge = EdgeSpec(source=source, target=target, label=str(raw.get("label", "")))
    edge.style = str(raw.get("style", "default"))
    if edge.style not in EDGE_STYLES:
        problems.append(
            f"edges[{index}]: unknown style {edge.style!r}; known: {', '.join(EDGE_STYLES)}"
        )
    for field_name, attr in (("from_port", "from_port"), ("to_port", "to_port")):
        value = raw.get(field_name)
        if value is None:
            continue
        if value not in ("left", "right", "up", "down"):
            problems.append(
                f'edges[{index}].{field_name} must be left/right/up/down (got {value!r})'
            )
            continue
        setattr(edge, attr, value)
    side = raw.get("label_side")
    if side is not None and side not in ("h", "v"):
        problems.append(f'edges[{index}].label_side must be "h" or "v" (got {side!r})')
    else:
        edge.label_side = side
    return edge


def _parse_loop(raw, problems: list) -> LoopSpec:
    if not isinstance(raw, dict):
        problems.append('a "loop" diagram needs a "loop" object with stations')
        return LoopSpec()
    loop = LoopSpec()
    hub = raw.get("hub")
    if isinstance(hub, dict):
        loop.hub_label = str(hub.get("label", ""))
        loop.hub_sub = str(hub.get("sub", ""))
    elif hub is not None:
        problems.append('"loop.hub" must be an object like {"label": "Memory"}')
    for field_name in ("radius", "station_w", "station_h", "hub_w", "hub_h"):
        value = raw.get(field_name)
        if value is None:
            continue
        if not (isinstance(value, (int, float)) and value > 0):
            problems.append(f"loop.{field_name} must be positive (got {value!r})")
            continue
        setattr(loop, field_name, float(value))
    stations = raw.get("stations")
    if not isinstance(stations, list) or not stations:
        problems.append('"loop.stations" must be a non-empty list')
        return loop
    for i, raw_station in enumerate(stations):
        node = _parse_node(raw_station, f"loop.stations[{i}]", problems)
        if node is None:
            continue
        if node.x is not None or node.y is not None:
            problems.append(f"loop station {node.id!r}: positions are computed — drop x/y")
        loop.stations.append(node)
    if len(loop.stations) and not (LOOP_STATIONS[0] <= len(loop.stations) <= LOOP_STATIONS[1]):
        problems.append(
            f"a loop takes {LOOP_STATIONS[0]}–{LOOP_STATIONS[1]} stations"
            f" (got {len(loop.stations)}); split above that"
        )
    if not loop.hub_label:
        problems.append('a loop needs "loop.hub.label" (the shared state in the middle)')
    return loop


def _parse_tree(raw, problems: list) -> TreeNodeSpec | None:
    """The hierarchy: one nested node, children in reading order."""
    if not isinstance(raw, dict):
        problems.append(
            'a "tree" diagram needs a "tree" object: a node with a "label" and'
            ' optional "children"'
        )
        return None
    return _parse_tree_node(raw, "tree", problems, set())


def _parse_tree_node(raw, where: str, problems: list, ids: set) -> TreeNodeSpec | None:
    node = _parse_node(raw, where, problems)
    if node is None:
        return None
    if node.x is not None or node.y is not None:
        problems.append(f"tree node {node.id!r}: positions are computed — drop x/y")
    if node.id in ids:
        # Ids name the groups and key the layout, so two boxes cannot share one.
        problems.append(f'duplicate tree id {node.id!r} — give one of them an "id"')
    ids.add(node.id)
    children: list = []
    raw_children = raw.get("children") or []
    if not isinstance(raw_children, list):
        problems.append(f'{where}."children" must be a list')
    else:
        for i, child in enumerate(raw_children):
            parsed = _parse_tree_node(child, f"{where}.children[{i}]", problems, ids)
            if parsed is not None:
                children.append(parsed)
    return TreeNodeSpec(id=node.id, label=node.label, sub=node.sub, tag=node.tag,
                        w=node.w, h=node.h, type=node.type, focal=node.focal,
                        children=children)


def _parse_chart(raw, problems: list) -> ChartSpec | None:
    """The data table: categories, series, and the two axis titles.

    A chart cannot express a coordinate, because the value scale is the
    compiler's decision — it owns the nice-number rounding, so the axis bounds
    are not the author's to declare and a position would have no meaning to
    check against. The only geometry-adjacent keys are the page header's
    (``canvas``, ``preset``, ``margin``), which are a *minimum*, as everywhere.
    """
    if not isinstance(raw, dict):
        problems.append(
            'a "chart" diagram needs a "chart" object like'
            ' {"type": "bar", "series": [{"label": "Shipped", "values": [12, 18]}]}'
        )
        return None
    chart = ChartSpec()
    ctype = raw.get("type", "bar")
    if ctype not in CHART_TYPES:
        problems.append(
            f'chart "type" must be one of {", ".join(CHART_TYPES)} (got {ctype!r})')
    else:
        chart.type = str(ctype)

    raw_series = raw.get("series")
    if not isinstance(raw_series, list) or not raw_series:
        problems.append('"chart.series" must be a non-empty list of {"label", "values"}')
        return chart
    for i, item in enumerate(raw_series):
        if not isinstance(item, dict):
            problems.append(f"chart.series[{i}] must be an object")
            continue
        raw_values = item.get("values")
        if not isinstance(raw_values, list) or not raw_values:
            problems.append(f'chart.series[{i}] needs a non-empty "values" list')
            continue
        clean: list = []
        for j, value in enumerate(raw_values):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                problems.append(
                    f"chart.series[{i}].values[{j}] must be a finite number (got {value!r})"
                )
                continue
            clean.append(float(value))
        chart.series.append(SeriesSpec(label=str(item.get("label") or f"Series {i + 1}"),
                                       values=clean))
    if not chart.series:
        return chart

    count = max(len(s.values) for s in chart.series)
    raw_categories = raw.get("categories")
    if raw_categories is None:
        # No labels given: the categories are the positions, named by number.
        chart.categories = [str(i + 1) for i in range(count)]
    elif not isinstance(raw_categories, list) or not raw_categories:
        problems.append('"chart.categories" must be a non-empty list of labels')
    else:
        chart.categories = [str(c) for c in raw_categories]
        count = len(chart.categories)
    for i, series in enumerate(chart.series):
        if len(series.values) != count:
            problems.append(
                f"chart.series[{i}] has {len(series.values)} values but the chart has"
                f" {count} categories — one value per category"
            )

    for field_name in ("x_label", "y_label", "unit"):
        setattr(chart, field_name, str(raw.get(field_name, "")))
    grid = raw.get("grid", True)
    if not isinstance(grid, bool):
        problems.append(f'chart "grid" must be true/false (got {grid!r})')
    else:
        chart.grid = grid
    return chart


def _slug(label: str) -> str:
    out = [c.lower() if c.isalnum() else "-" for c in label.strip()]
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "node"


def load_spec(path: str) -> Spec:
    """Read and validate a spec file (raises :class:`SpecError` / OSError)."""
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SpecError([f"{path}: invalid JSON — {exc}"]) from exc
    return parse_spec(data)

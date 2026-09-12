"""Editorial diagrams (spec -> .nf.svg) — the diagram-design absorption."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from nanoframes.diagram import build_scene, compose, parse_spec
from nanoframes.diagram import geometry as geo
from nanoframes.diagram.scene import Rect, Text
from nanoframes.diagram.spec import SpecError, load_spec

SVG = "{http://www.w3.org/2000/svg}"


class FakeMeasurer:
    """Deterministic ink metrics: 0.6em per char, 0.72em cap height."""

    def __init__(self):
        self.calls = 0

    def ink(self, text, family, weight, size_px, letter_spacing=0.0):  # noqa: ARG002
        from nanoframes.measure import InkMetrics

        self.calls += 1
        per = size_px * 0.6 + letter_spacing
        w = max(size_px * 0.5, len(text) * per)
        return InkMetrics(left_dx=1.0, right_dx=w, top=-size_px * 0.72,
                          bottom=size_px * 0.2, w=w, h=size_px * 0.92)


@pytest.fixture()
def measure():
    return FakeMeasurer()


def flow_spec(**over):
    spec = {
        "diagram": "flow",
        "title": "Ingest path",
        "nodes": [
            {"id": "edge", "label": "Edge", "sub": "cdn", "x": 80, "y": 200,
             "type": "external"},
            {"id": "api", "label": "API Gateway", "x": 320, "y": 200, "type": "focal"},
            {"id": "db", "label": "Postgres", "sub": "orders", "x": 640, "y": 200,
             "type": "store"},
        ],
        "edges": [
            {"from": "edge", "to": "api", "label": "TLS"},
            {"from": "api", "to": "db", "label": "SQL"},
        ],
    }
    spec.update(over)
    return spec


def hub_centre(scene):
    hub = next(g for g in scene.groups if g.name == "hub")
    box = next(p for p in hub.parts if isinstance(p, Rect) and p.weight == "box")
    return (box.x + box.w / 2.0, box.y + box.h / 2.0)


def loop_spec(**over):
    spec = {
        "diagram": "loop",
        "title": "The self-improving loop",
        "loop": {
            "hub": {"label": "Shared memory", "sub": "one record"},
            "stations": [
                {"id": "capture", "label": "Capture", "sub": "signals in"},
                {"id": "research", "label": "Research"},
                {"id": "decide", "label": "Decide", "focal": True},
                {"id": "act", "label": "Act"},
                {"id": "measure", "label": "Measure"},
                {"id": "learn", "label": "Learn"},
            ],
        },
    }
    spec.update(over)
    return spec


# ---------------------------------------------------------------------------
# spec validation
# ---------------------------------------------------------------------------


def test_spec_rejects_unknown_kind():
    with pytest.raises(SpecError) as exc:
        parse_spec({"diagram": "sankey"})
    assert "flow, loop" in str(exc.value)


def test_spec_reports_every_problem_at_once():
    with pytest.raises(SpecError) as exc:
        parse_spec({
            "diagram": "flow",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "x": 1}],
            "edges": [{"from": "a", "to": "nope", "style": "glow"}],
        })
    problems = exc.value.problems
    assert any("edge 0" in p and "nope" in p for p in problems)
    assert any("style" in p for p in problems)
    assert any('"x" and "y"' in p for p in problems)


def test_spec_requires_explicit_flow_positions():
    with pytest.raises(SpecError) as exc:
        parse_spec({"diagram": "flow", "nodes": [{"label": "A"}]})
    assert '"x" and "y"' in str(exc.value)


def test_spec_loop_station_count_is_bounded():
    with pytest.raises(SpecError) as exc:
        parse_spec({
            "diagram": "loop",
            "loop": {"hub": {"label": "H"},
                     "stations": [{"label": f"S{i}"} for i in range(9)]},
        })
    assert "5–8 stations" in str(exc.value)


def test_spec_accepts_fit_preset():
    spec = parse_spec(flow_spec(preset="fit"))
    assert spec.preset == "fit"


def test_spec_rejects_unknown_preset():
    with pytest.raises(SpecError) as exc:
        parse_spec(flow_spec(preset="slides-16x9"))
    assert "unknown preset" in str(exc.value)


# ---------------------------------------------------------------------------
# flow geometry
# ---------------------------------------------------------------------------


def svg_root(svg_text):
    return ET.fromstring(svg_text)


def test_flow_emits_wellformed_composition(measure):
    svg = compose(flow_spec(), measurer=measure)
    root = svg_root(svg)
    assert root.get("data-width") and root.get("data-height")
    assert float(root.get("data-duration")) == 1.0
    # Centred runs are emitted per glyph (ThorVG ignores text-anchor), so the
    # document's text is a stream of characters; reconstruct it to check content.
    joined = "".join(el.text or "" for el in root.iter(SVG + "text"))
    for expected in ("Ingest path", "Edge", "API Gateway", "Postgres", "TLS", "SQL"):
        assert expected in joined
    assert "text-anchor=\"middle\"" not in svg, "ThorVG ignores text-anchor"


def test_flow_snaps_positions_to_the_4px_grid(measure):
    spec = flow_spec()
    spec["nodes"][0]["x"] = 82.5
    scene = build_scene(parse_spec(spec), measurer=measure)
    assert any("snapped to the 4px grid" in w for w in scene.warnings)
    boxes = {g.name: next(p for p in g.parts if isinstance(p, Rect) and p.weight == "box")
             for g in scene.groups if g.name.startswith("node:")}
    # 82.5 -> 84; the page offset is one shared shift, so every box keeps the
    # same relative grid spacing.
    assert boxes["node:edge"].x == 84.0
    assert boxes["node:api"].x == 320.0
    assert boxes["node:db"].x - boxes["node:api"].x == 320.0
    assert (boxes["node:api"].y - boxes["node:edge"].y) % 4 == 0


def test_flow_box_width_covers_its_text(measure):
    scene = build_scene(parse_spec(flow_spec()), measurer=measure)
    for group in scene.groups:
        if not group.name.startswith("node:"):
            continue
        box = next(p for p in group.parts if isinstance(p, Rect) and p.weight == "box")
        runs = [p for p in group.parts if isinstance(p, Text)]
        assert runs
        for run in runs:
            metrics = measure.ink(run.content, run.family, "400", run.size)
            assert metrics.w <= box.w, f"{run.content!r} overflows its box"


def test_every_connector_is_orthogonal_with_rounded_corners(measure):
    spec = flow_spec()
    spec["nodes"][2]["y"] = 360          # force an off-axis route: two corners
    scene = build_scene(parse_spec(spec), measurer=measure)
    paths = list(scene.paths())
    assert len(paths) == 2
    for path in paths:
        coords = [(float(x), float(y)) for x, y in
                  re.findall(r"([\d.]+),([\d.]+)", path.d)]
        assert len(coords) >= 2
        for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
            assert abs(x0 - x1) < 0.01 or abs(y0 - y1) < 0.01, "diagonal connector"
        if path.points[0][1] != path.points[-1][1] and path.points[0][0] != path.points[-1][0]:
            assert " Q " in path.d, "off-axis connector lacks a rounded corner"


def test_arrowheads_are_explicit_polygons(measure):
    """ThorVG does not render SVG <marker>, so heads must be real geometry."""
    svg = compose(flow_spec(), measurer=measure)
    root = svg_root(svg)
    polygons = list(root.iter(SVG + "polygon"))
    assert len(polygons) == 2
    for polygon in polygons:
        assert len(polygon.get("points").split()) == 3
    assert not list(root.iter(SVG + "marker"))


def test_shared_exit_edge_fans_attach_points(measure):
    """Two connectors leaving the same side must not share a point (rule 4)."""
    spec = flow_spec()
    spec["nodes"].append({"id": "queue", "label": "Queue", "x": 320, "y": 360})
    spec["edges"] += [
        {"from": "api", "to": "queue", "from_port": "down", "to_port": "up"},
        {"from": "api", "to": "db", "from_port": "down", "to_port": "up"},
    ]
    scene = build_scene(parse_spec(spec), measurer=measure)
    api = next(g for g in scene.groups if g.name == "node:api")
    api_box = next(p for p in api.parts if isinstance(p, Rect) and p.weight == "box")
    bottom = api_box.y + api_box.h
    starts = sorted(round(p.points[0][0], 2) for p in scene.paths()
                    if abs(p.points[0][1] - bottom) < 0.01)
    assert len(starts) == 2
    assert starts[0] != starts[1]
    assert starts[1] - starts[0] >= 12, "attach points are closer than the 12px rule"


def test_arrow_label_masks_stay_clear_of_their_stroke(measure):
    """Rule 2: the visible gap between a label mask and its connector is 6–10px.

    The label group carries only the plate and the run (paths live in their own
    group, painted first), so the check is against every connector in the scene.
    """

    scene = build_scene(parse_spec(flow_spec()), measurer=measure)
    arrows = list(scene.texts("arrow"))
    assert arrows
    connector_points = [p.points for p in scene.paths()]
    for run in arrows:
        # Clearance is from the label's *ink*, not its mask plate.
        ink_bottom = run.y + measure.ink(run.content, run.family, "400", run.size).bottom
        distance = min(geo.path_distance((run.x, ink_bottom), pts)
                       for pts in connector_points)
        # The nominal gap is ARROW_GAP (8px); at a path corner the perpendicular
        # distance to the *other* segment can be a few px tighter. The failure
        # this guards is the ink touching the stroke (distance 0).
        assert 3.0 <= distance <= 20.0, f"label ink sits {distance:.1f}px from its stroke"


def test_arrow_labels_never_overlap_a_node(measure):
    """Rule 6: a mask landing inside a node renders as a clipped text fragment."""
    from nanoframes.diagram.text import text_box

    scene = build_scene(parse_spec(flow_spec()), measurer=measure)
    boxes = list(scene.rects("box"))
    for run in scene.texts("arrow"):
        box = text_box(run, measure)
        for node in boxes:
            dx, dy = geo.rect_overlap(box, (node.x, node.y, node.w, node.h))
            if dx > 0 and dy > 0:
                assert geo.rect_contains(
                    box, (node.x, node.y, node.w, node.h)
                ), "label mask clips a node"

def test_accent_budget_is_enforced(measure):
    spec = flow_spec()
    for i in range(3):
        spec["nodes"].append({"id": f"f{i}", "label": f"Focal {i}", "x": 80, "y": 400 + 80 * i,
                              "type": "focal"})
    scene = build_scene(parse_spec(spec), measurer=measure)
    assert any("focal nodes" in w for w in scene.warnings)


def test_node_budget_warns(measure):
    spec = {"diagram": "flow", "nodes": [], "edges": []}
    for i in range(10):
        spec["nodes"].append({"id": f"n{i}", "label": f"Node {i}", "x": 80 + 160 * i, "y": 200})
    scene = build_scene(parse_spec(spec), measurer=measure)
    assert any("over the 9-node budget" in w for w in scene.warnings)


def test_hard_node_ceiling_raises(measure):
    spec = {"diagram": "flow", "nodes": [], "edges": []}
    for i in range(25):
        spec["nodes"].append({"id": f"n{i}", "label": f"Node {i}", "x": 80, "y": 80 * i})
    with pytest.raises(ValueError) as exc:
        build_scene(parse_spec(spec), measurer=measure)
    assert "split" in str(exc.value)


def test_canvas_is_derived_from_content(measure):
    scene = build_scene(parse_spec(flow_spec()), measurer=measure)
    assert scene.width % 4 == 0 and scene.height % 4 == 0
    assert scene.width >= 640 + 80 + 40          # right-most box + margin
    assert scene.height >= 200 + 48 + 40


def test_preset_sets_a_floor_on_the_canvas(measure):
    scene = build_scene(parse_spec(flow_spec(preset="doc-wide")), measurer=measure)
    assert (scene.width, scene.height) >= (1280, 720)


def test_explicit_canvas_is_respected_and_warns_when_too_small(measure):
    spec = flow_spec(canvas={"width": 400, "height": 200})
    scene = build_scene(parse_spec(spec), measurer=measure)
    assert any("grew the canvas" in w for w in scene.warnings)
    for box in scene.rects("box"):
        assert box.x + box.w <= scene.width and box.y + box.h <= scene.height


def test_explicit_canvas_is_a_minimum_not_a_cap(measure):
    spec = flow_spec(canvas={"width": 1920, "height": 1080})
    scene = build_scene(parse_spec(spec), measurer=measure)
    assert (scene.width, scene.height) == (1920.0, 1080.0)
    assert not any("grew the canvas" in w for w in scene.warnings)


def test_dark_skin_swaps_paper_and_ink(measure):
    light = compose(flow_spec(), measurer=measure)
    dark = compose(flow_spec(skin="dark"), measurer=measure)
    assert 'id="bg" width="' in light and 'fill="#f5f5f5"' in light
    assert 'id="bg" width="' in dark and 'fill="#2d3142"' in dark


def test_zones_group_their_members(measure):
    spec = flow_spec(zones=[{"id": "priv", "label": "Private", "nodes": ["api", "db"]}])
    for node in spec["nodes"]:
        if node["id"] in ("api", "db"):
            node["zone"] = "priv"
    scene = build_scene(parse_spec(spec), measurer=measure)
    zone = next(g for g in scene.groups if g.name == "zone:priv")
    box = next(p for p in zone.parts if isinstance(p, Rect) and p.weight == "zone")
    api = next(p for p in scene.rects("box")
               if p.x >= 320 and p.x < 640)  # the API box
    assert geo.rect_contains((api.x, api.y, api.w, api.h), (box.x, box.y, box.w, box.h)), \
        "zone does not contain its member node"

    assert "PRIVATE" in "".join(t.content for t in scene.texts("eyebrow"))


def test_unknown_zone_reference_is_a_spec_error():
    spec = flow_spec()
    spec["nodes"][0]["zone"] = "nope"
    with pytest.raises(SpecError) as exc:
        parse_spec(spec)
    assert "unknown zone" in str(exc.value)


# ---------------------------------------------------------------------------
# loop geometry
# ---------------------------------------------------------------------------


def test_loop_places_stations_on_the_ring(measure):
    spec = parse_spec(loop_spec())
    scene = build_scene(spec, measurer=measure)
    centers = []
    for group in scene.groups:
        if not group.name.startswith("node:"):
            continue
        box = next(p for p in group.parts if isinstance(p, Rect) and p.weight == "box")
        centers.append((box.x + box.w / 2.0, box.y + box.h / 2.0))
    assert len(centers) == 6
    hx, hy = hub_centre(scene)
    # Stations sit on one ring around the hub, within the 4px grid snap.
    radii = [math.hypot(cx - hx, cy - hy) for cx, cy in centers]
    assert max(radii) - min(radii) < 10
    top = min(centers, key=lambda c: c[1])
    assert abs(top[0] - hx) < 8  # station 0 sits at the top, over the hub


def test_loop_ring_connectors_are_arcs(measure):
    scene = build_scene(parse_spec(loop_spec()), measurer=measure)
    arcs = [p for p in scene.paths() if p.d.startswith("M ") and " A " in p.d]
    assert len(arcs) == 6
    for arc in arcs:
        assert "0 0 1" in arc.d           # clockwise sweep
        assert arc.head_fill               # every ring arrow has a head
    spans = [len(re.findall(r"A ([\d.]+)", a.d)) for a in arcs]
    assert spans == [1] * 6


def test_loop_write_back_spokes_are_dashed_and_radial(measure):
    scene = build_scene(parse_spec(loop_spec()), measurer=measure)
    spokes = [p for p in scene.paths() if p.dash == "5,4"]
    assert len(spokes) == 6
    center = hub_centre(scene)
    for spoke in spokes:
        (x0, y0), (x1, y1) = spoke.points
        u = (x1 - x0, y1 - y0)
        v = (x1 - center[0], y1 - center[1])
        cross = u[0] * v[1] - u[1] * v[0]
        # Spokes are cast from the ideal ring centre; the drawn hub box is grid-
        # snapped, so its centre can sit ~2px off that ray. Under 4 degrees.
        assert abs(cross) / (math.hypot(*u) * math.hypot(*v)) < 0.07, "spoke is not radial"


def test_loop_hub_is_the_only_ink_filled_box(measure):
    scene = build_scene(parse_spec(loop_spec()), measurer=measure)
    filled = [p for p in scene.rects("box") if p.fill_opacity == 1.0 and p.fill != "#ffffff"]
    assert len(filled) == 1


def test_loop_station_focal_uses_accent(measure):
    scene = build_scene(parse_spec(loop_spec()), measurer=measure)
    focal = [p for p in scene.rects("box") if p.stroke == "#eb6c36"]
    assert len(focal) == 1


def test_loop_canvas_contains_every_box(measure):
    scene = build_scene(parse_spec(loop_spec()), measurer=measure)
    for box in scene.rects("box"):
        assert box.x >= 0 and box.y >= 0
        assert box.x + box.w <= scene.width and box.y + box.h <= scene.height


def test_loop_radius_is_raised_to_clear_the_hub(measure):
    spec = loop_spec()
    spec["loop"]["radius"] = 40
    scene = build_scene(parse_spec(spec), measurer=measure)
    for spoke in [p for p in scene.paths() if p.dash == "5,4"]:
        assert spoke.points[0] != spoke.points[1]


# ---------------------------------------------------------------------------
# reveal + composition contract
# ---------------------------------------------------------------------------


def test_static_output_has_no_timing_attributes(measure):
    svg = compose(flow_spec(), measurer=measure)
    assert "data-start" not in svg
    assert "data-fade" not in svg


def test_reveal_staggers_groups_and_sets_duration(measure):
    svg = compose(flow_spec(reveal=True), measurer=measure)
    root = svg_root(svg)
    assert float(root.get("data-duration")) > 1.0
    starts = [float(g.get("data-start")) for g in root.iter(SVG + "g")
              if g.get("data-start")]
    assert len(starts) >= 6
    assert len(set(starts)) == len(starts), "two groups reveal at the same instant"
    assert all(abs(s / 0.16 - round(s / 0.16)) < 0.01 for s in starts)
    assert all(g.get("data-fade") for g in root.iter(SVG + "g") if g.get("data-start"))


def test_explicit_duration_wins(measure):
    svg = compose(flow_spec(reveal=True, duration=9.5), measurer=measure)
    assert float(svg_root(svg).get("data-duration")) == 9.5


def test_composition_is_deterministic(measure):
    assert compose(flow_spec(), measurer=measure) == compose(flow_spec(), measurer=measure)
    assert compose(loop_spec(), measurer=measure) == compose(loop_spec(), measurer=measure)


def test_generated_composition_parses_and_lints_clean(tmp_path):
    """With a real measurer, the emitted SVG is a lint-clean composition."""
    from nanoframes.lint import lint_string
    from nanoframes.render import measurer

    m = measurer()
    svg = compose(flow_spec(), measurer=m)
    findings = lint_string(svg, measurer=m)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors, errors

    svg_loop = compose(loop_spec(title=""), measurer=m)
    errors = [f for f in lint_string(svg_loop, measurer=m) if f.severity == "error"]
    assert not errors, errors


def test_generated_files_render_pixels(tmp_path):
    """End-to-end: spec -> .nf.svg -> ThorVG PNG with ink on it."""
    from nanoframes.parse import parse_file
    from nanoframes.render import measurer, render_frame

    m = measurer()
    for name, spec in (("flow", flow_spec()), ("loop", loop_spec())):
        path = tmp_path / f"{name}.nf.svg"
        path.write_text(compose(spec, measurer=m, composition_id=name), encoding="utf-8")
        doc = parse_file(str(path))
        img = render_frame(doc, 0.0, warn_blank=False).convert("RGBA")
        alpha = img.getchannel("A")
        assert alpha.getextrema()[1] > 0, f"{name} rendered fully transparent"
        ink = sum(1 for p in img.getdata() if p[3] > 8 and p[:3] != (245, 245, 245))
        assert ink > 500, f"{name} rendered almost nothing ({ink} ink pixels)"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_cli(*argv):
    return subprocess.run([sys.executable, "-m", "nanoframes", *argv],
                          capture_output=True, text=True)


def test_cli_builds_a_composition(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(flow_spec()), encoding="utf-8")
    out = tmp_path / "diagram.nf.svg"
    proc = run_cli("diagram", str(spec_path), "-o", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    assert "wrote" in proc.stdout
    assert "<svg" in out.read_text(encoding="utf-8")


def test_cli_reports_spec_errors_without_writing(tmp_path):
    spec_path = tmp_path / "bad.json"
    spec_path.write_text(json.dumps({"diagram": "flow", "nodes": [{"label": "A"}]}),
                         encoding="utf-8")
    proc = run_cli("diagram", str(spec_path))
    assert proc.returncode == 1
    assert "x" in proc.stderr
    assert not (tmp_path / "bad.nf.svg").exists()


def test_cli_check_lints_the_result(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(loop_spec()), encoding="utf-8")
    proc = run_cli("diagram", str(spec_path), "--check")
    assert proc.returncode == 0, proc.stderr


def test_cli_reports_budget_warnings(tmp_path):
    spec = flow_spec()
    for i in range(8):
        spec["nodes"].append({"id": f"n{i}", "label": f"N{i}", "x": 80 + 100 * i, "y": 360})
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    proc = run_cli("diagram", str(spec_path))
    assert proc.returncode == 0, proc.stderr
    assert "9-node budget" in proc.stdout


def test_load_spec_surfaces_json_errors(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SpecError) as exc:
        load_spec(str(path))
    assert "invalid JSON" in str(exc.value)


def test_geometry_helpers():
    assert geo.q4(82.5) == 84
    assert not geo.on_grid(82.5)
    points, length = geo.elbow((0, 0), (100, 100), "right")
    assert points[0] == (0, 0) and points[-1] == (100, 100)
    assert length > 0
    d = geo.path_d(points)
    assert d.startswith("M 0,0") and " Q " in d
    straight, _ = geo.elbow((0, 0), (0, 80), "down")
    assert len(straight) == 2
    points, _ = geo.elbow((0, 0), (100, 100), "right")
    assert geo.point_at(points, 0) == (0, 0)
    assert geo.point_at(points, 10_000) == (100, 100)
    pts, at = geo.arrowhead([(0, 0), (40, 0)])
    assert len(pts.split()) == 3 and at[2] == pytest.approx(0.0)
    open_pts = geo.open_head([(0, 0), (40, 0)])
    assert len(open_pts.split()) == 3
    assert geo.segment_distance((5, 5), (0, 0), (10, 0)) == pytest.approx(5.0)
    assert geo.rect_overlap((0, 0, 10, 10), (5, 5, 10, 10)) == (5, 5)
    assert geo.rect_contains((1, 1, 2, 2), (0, 0, 10, 10))
    assert not geo.rect_contains((0, 0, 10, 10), (1, 1, 2, 2))


def test_text_width_budget_matches_measured_metrics(measure):
    from nanoframes.diagram import text as txt

    metrics = txt.measure(measure, "Gateway", "Arial", "600", 12)
    assert metrics.width == pytest.approx(7 * 12 * 0.6)
    assert txt.is_mono("'Sarasa Mono SC', monospace")
    assert not txt.is_mono("Arial, sans-serif")
    w, h = txt.box_size(measure, "Gateway", "tech:8080", "API", {"label": 12, "sub": 9,
                                                                 "tag": 8,
                                                                 "min_box_h": 48},
                        "Arial", "'Sarasa Mono SC', monospace")
    assert w % 4 == 0 and h >= 48


def test_tracked_runs_stay_one_element(measure):
    """Tracked text is a single <text> whose width carries the tracking."""
    from nanoframes.diagram import text as txt

    run = txt.tracked_run(100.0, 20.0, "region", 8, "#4f5d75",
                          "'Sarasa Mono SC', monospace", 1.12, anchor="middle",
                          kind="eyebrow")
    assert run.content == "REGION" and run.tracking == 1.12
    plain = txt.visual_width(measure, "REGION", run.family, "400", 8, 0.0, 0.0)
    tracked = txt.visual_width(measure, "REGION", run.family, "400", 8, 0.0, 1.12)
    assert tracked > plain


def test_unsupported_browser_idioms_never_reach_the_output(measure):
    """ThorVG: rgba() paints black, <marker> is ignored, letter-spacing is ignored."""
    svg = compose(flow_spec(reveal=True), measurer=measure)
    assert "rgba(" not in svg
    assert "marker" not in svg
    assert "letter-spacing" not in svg
    assert "font-weight" not in svg        # not resolvable offline; weights are doc-only
    assert "style=" not in svg


def test_warnings_helper_does_not_render():
    from nanoframes.diagram import warnings_for

    assert warnings_for(flow_spec(), measurer=FakeMeasurer()) == []


def test_a_centred_run_is_one_element_centred_on_its_anchor(measure):
    """No per-glyph emission: one <text>, placed so its ink centres on the anchor.

    ThorVG ignores `text-anchor` and left-aligns every run, so the emitter
    computes the compensating x from the measured ink. Getting that wrong (or
    splitting the run per glyph) is how CJK overlapped and Latin spread out.
    """
    from nanoframes.diagram.emit import _text_markup

    for content in ("Learn", "感知", "Shared Memory"):
        run = Text(x=200.0, y=100.0, content=content, size=12, fill="#000",
                   family="Arial", anchor="middle", kind="label")
        markup = _text_markup(run, measure)
        assert markup.count("<text") == 1, f"{content!r} must be one <text>"
        x = float(re.search(r'\bx="([-\d.]+)"', markup).group(1))
        ink = measure.ink(content, "Arial", "400", 12)
        centre = x - ink.left_dx + ink.w / 2.0
        assert abs(centre - 200.0) < 1.0, f"{content!r} centres at {centre:.1f}"
        assert f">{content}<" in markup


# ---------------------------------------------------------------------------
# sketchy (hand-drawn) skin
# ---------------------------------------------------------------------------


def test_sketchy_skin_is_deterministic(measure):
    """The wobble is a pure function of the shape's coordinates and name."""
    a = compose(flow_spec(skin="sketchy"), measurer=measure)
    b = compose(flow_spec(skin="sketchy"), measurer=measure)
    assert a == b


def test_sketchy_draws_outlines_as_wobbly_paths(measure):
    scene = build_scene(parse_spec(flow_spec(skin="sketchy")), measurer=measure)
    wobbly = [p for p in scene.paths() if " Q " in p.d and p.d.startswith("M ")]
    assert len(wobbly) >= 8, "each box edge should bow as its own stroke"
    # Plain node boxes keep only their fill; the outline is the rough paths.
    for group in scene.groups:
        if not group.name.startswith("node:"):
            continue
        boxes = [p for p in group.parts if isinstance(p, Rect) and p.weight == "box"]
        assert boxes and all(b.stroke is None for b in boxes), \
            "a sketchy box must not also emit a straight outline"


def test_sketchy_upholds_the_warm_paper_canvas(measure):
    svg = compose(flow_spec(skin="sketchy"), measurer=measure)
    assert 'fill="#f8f6ef"' in svg          # the register's exact base color
    assert "rgba(" not in svg               # ThorVG paints rgba solid black


def test_sketchy_wobble_stays_local(measure):
    """A stroke may look hand-drawn, but it must not wander off its shape."""
    from nanoframes.diagram import sketchy

    for name in ("node:edge", "zone:priv", "ring:capture"):
        for d in sketchy.rough_rect(100.0, 200.0, 120.0, 48.0, name):
            for x, y in re.findall(r"(-?[\d.]+),(-?[\d.]+)", d):
                assert 100.0 - 4 <= float(x) <= 220.0 + 4
                assert 200.0 - 4 <= float(y) <= 248.0 + 4


def test_sketchy_arcs_are_sampled_within_the_radius(measure):
    from nanoframes.diagram import sketchy

    d = sketchy.rough_arc(300.0, 300.0, 200.0, -90.0, -30.0, "ring:capture")
    points = [(float(x), float(y)) for x, y in re.findall(r"(-?[\d.]+),(-?[\d.]+)", d)]
    assert len(points) >= 7
    radii = [math.hypot(x - 300.0, y - 300.0) for x, y in points]
    assert all(abs(r - 200.0) <= 4 for r in radii)


def test_plain_skins_emit_no_wobble(measure):
    svg = compose(flow_spec(), measurer=measure)
    scene = build_scene(parse_spec(flow_spec()), measurer=measure)
    assert "#f8f6ef" not in svg
    # Every connector is a straight/elbow path with no quadratic bows of its own.
    for path in scene.paths():
        assert " M " not in path.d, "a clean connector should be one path"


def test_diagram_text_is_exact_with_the_real_measurer():
    """The layout's text fits its boxes and centres on its anchors, measured for real.

    The layout tests above use a synthetic measurer so they do not need ThorVG.
    This one runs the same flow through the renderer-exact Measurer, which is the
    only way to catch a disagreement between "the width the box was sized for"
    and "the width the emitter places".
    """
    from nanoframes.diagram.text import text_box
    from nanoframes.render import measurer

    m = measurer()
    scene = build_scene(parse_spec(flow_spec()), measurer=m)
    for group in scene.groups:
        if not group.name.startswith("node:"):
            continue
        box = next(p for p in group.parts if isinstance(p, Rect) and p.weight == "box")
        for run in [p for p in group.parts if isinstance(p, Text)]:
            ink = m.ink(run.content, run.family, "400", run.size)
            assert ink.w <= box.w, f"{run.content!r} is wider than its box"
            if run.anchor == "middle":
                # Where the emitter will put it, per its own rule: the drawn
                # span's centre lands on the anchor within rounding.
                placed = run.x - ink.w / 2.0 + ink.left_dx
                centre = placed + ink.w / 2.0
                assert abs(centre - run.x) <= 1.0, f"{run.content!r} centres at {centre:.1f}"
    for run in scene.texts("arrow"):
        plate = text_box(run, m)
        ink = m.ink(run.content, run.family, "400", run.size)
        assert plate[2] >= ink.w, "an arrow label's plate must cover its ink"

"""The tree grammar — the computed layout, and the seam it opened.

`flow` and `loop` are locked by their shipped examples (tests/test_diagram.py
rebuilds them byte for byte, tests/digests.json pins their frames), so the
interesting questions here are about the *new* compiler: does the spec refuse
coordinates, does the algorithm produce a tidy grid-aligned chart through the
shared page machinery, and does the grammar table stay in step with the parser.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import pytest

from nanoframes.diagram import GRAMMARS, build_scene, compose, parse_spec
from nanoframes.diagram import geometry as geo
from nanoframes.diagram.scene import Path, Rect
from nanoframes.diagram.spec import KINDS, SpecError

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "examples")


class FakeMeasurer:
    """Deterministic ink metrics: 0.6em per char, 0.72em cap height."""

    def ink(self, text, family, weight, size_px, letter_spacing=0.0):  # noqa: ARG002
        from nanoframes.measure import InkMetrics

        per = size_px * 0.6 + letter_spacing
        w = max(size_px * 0.5, len(text) * per)
        return InkMetrics(left_dx=1.0, right_dx=w, top=-size_px * 0.72,
                          bottom=size_px * 0.2, w=w, h=size_px * 0.92)


@pytest.fixture()
def measure():
    return FakeMeasurer()


def tree_spec(**over):
    spec = {
        "diagram": "tree",
        "canvas": {"width": 1280, "height": 520},
        "title": "Platform team",
        "tree": {
            "id": "root", "label": "Platform", "type": "focal",
            "children": [
                {"id": "runtime", "label": "Runtime", "sub": "bake + cache",
                 "children": [{"id": "frames", "label": "Frames"},
                              {"id": "cache", "label": "Cache"}]},
                {"id": "quality", "label": "Quality", "type": "store",
                 "children": [{"id": "lint", "label": "Lint"}]},
            ],
        },
    }
    spec.update(over)
    return spec


def boxes(scene) -> dict:
    """``id -> (x, y, w, h)`` for every node box as drawn."""
    out = {}
    for group in scene.groups:
        if not group.name.startswith("node:"):
            continue
        for part in group.parts:
            if isinstance(part, Rect) and part.weight == "box":
                out[group.name[len("node:"):]] = (part.x, part.y, part.w, part.h)
    return out


def connectors(scene) -> dict:
    """``edge:parent->child -> Path`` for every drawn reporting line."""
    out = {}
    for group in scene.groups:
        if group.name.startswith("edge:"):
            out[group.name[len("edge:"):]] = next(
                p for p in group.parts if isinstance(p, Path))
    return out


def build(data, measurer=None):
    return build_scene(parse_spec(data), measurer=measurer)


# ---------------------------------------------------------------------------
# the seam: the grammar table and the parser agree
# ---------------------------------------------------------------------------


def test_the_grammar_table_covers_every_kind():
    """`diagram` decides the grammar in the spec; the table must know them all."""
    assert set(GRAMMARS) == set(KINDS) == {"flow", "loop", "tree"}


def test_every_grammar_is_one_compiler(measure):
    """Same signature, same return type: that is the whole grammar contract."""
    specs = {
        "flow": {"diagram": "flow", "nodes": [{"label": "A", "x": 0, "y": 0}]},
        "loop": {"diagram": "loop",
                 "loop": {"hub": {"label": "H"},
                          "stations": [{"label": f"S{i}"} for i in range(5)]}},
        "tree": tree_spec(),
    }
    for kind in KINDS:
        scene = build_scene(parse_spec(specs[kind]), measurer=measure)
        assert scene.groups and scene.width > 0 and scene.height > 0


def test_unknown_kind_lists_the_grammars():
    with pytest.raises(SpecError) as exc:
        parse_spec({"diagram": "sankey"})
    assert "flow, loop, tree" in str(exc.value)


# ---------------------------------------------------------------------------
# the spec: a hierarchy, never coordinates
# ---------------------------------------------------------------------------


def test_tree_spec_takes_a_nested_shape_without_positions():
    spec = parse_spec(tree_spec())
    assert spec.kind == "tree"
    assert spec.tree.id == "root"
    assert [c.id for c in spec.tree.children] == ["runtime", "quality"]
    assert spec.tree.children[0].children[1].id == "cache"
    assert spec.tree.children[1].children[0].children == []


def test_tree_rejects_authored_positions():
    data = tree_spec()
    data["tree"]["children"][0]["x"] = 80
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "positions are computed" in str(exc.value)
    assert "runtime" in str(exc.value)


def test_tree_needs_a_tree():
    with pytest.raises(SpecError) as exc:
        parse_spec({"diagram": "tree", "title": "no tree"})
    assert '"tree"' in str(exc.value)


def test_tree_children_must_be_a_list():
    data = tree_spec()
    data["tree"]["children"] = {"label": "oops"}
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "must be a list" in str(exc.value)


def test_tree_rejects_duplicate_ids():
    """Ids name the groups and key the layout, so two boxes cannot share one."""
    data = tree_spec()
    data["tree"]["children"][1]["id"] = "runtime"
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "duplicate tree id" in str(exc.value)


def test_tree_reports_a_bad_node_by_its_path():
    data = tree_spec()
    data["tree"]["children"][1]["children"][0].pop("label")
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "tree.children[1].children[0]" in str(exc.value)


def test_tree_label_becomes_the_id():
    data = tree_spec()
    data["tree"]["children"][0]["children"][0].pop("id")
    assert parse_spec(data).tree.children[0].children[0].id == "frames"


def test_tree_layout_knobs_are_validated():
    with pytest.raises(SpecError) as exc:
        parse_spec(tree_spec(h_gap=-4))
    assert "h_gap" in str(exc.value)
    assert parse_spec(tree_spec(v_gap=96)).v_gap == 96


# ---------------------------------------------------------------------------
# the layout: the algorithm half
# ---------------------------------------------------------------------------


def test_boxes_land_on_the_4px_grid(measure):
    """The grammar snaps box corners with the shared `geo.q4`, not a local grid.

    No title band here: the page moves the whole figure by the title's ink
    overhang (see the test below), which is one page-level constant rather than
    layout drift. With that out of the way every box corner is a grid point.
    """
    scene = build(tree_spec(title="", canvas={"width": 1280, "height": 440}), measure)
    placed = boxes(scene)
    assert set(placed) == {"root", "runtime", "quality", "frames", "cache", "lint"}
    for name, (x, y, w, h) in placed.items():
        assert geo.on_grid(x) and geo.on_grid(y), (name, x, y)
        assert geo.on_grid(w) and geo.on_grid(h), (name, w, h)


def test_the_title_band_offsets_the_tree_exactly_as_it_offsets_a_flow(measure):
    """The fractional y is the page's, and both grammars inherit the same one.

    `finish` nudges content down when the title's ink rises above the margin, so
    an authored 220 draws at 226.2 (architecture.nf.svg). A computed layout must
    land on that same offset — the grammar owns no vertical placement of its own.
    """
    flow = build_scene(parse_spec({
        "diagram": "flow", "title": "T", "canvas": {"width": 480, "height": 240},
        "nodes": [{"id": "a", "label": "A", "x": 40, "y": 160}]}), measurer=measure)
    flow_y = boxes(flow)["a"][1]
    assert not geo.on_grid(flow_y)                 # the page moved it, not the author
    tree = boxes(build(tree_spec(title="T"), measure))
    assert {round(y % 4, 2) for _, y, _, _ in tree.values()} == {round(flow_y % 4, 2)}


def test_authored_gaps_are_used_as_given_on_the_shared_grid(measure):
    """The knobs are the grammar's; the grid they land on is `geometry`'s."""
    placed = boxes(build(tree_spec(title="", h_gap=64, v_gap=80), measure))
    assert all(geo.on_grid(v) for box in placed.values() for v in box)
    row = sorted((b for b in placed.values() if b[1] == placed["frames"][1]),
                 key=lambda b: b[0])
    assert {b[0] - (a[0] + a[2]) for a, b in zip(row, row[1:])} == {64}
    # One grid-snapped pitch for the whole chart: the tallest box plus v_gap,
    # so a shorter box simply gets more air around it.
    row_h = max(h for _, _, _, h in placed.values())
    assert placed["runtime"][1] - placed["root"][1] == geo.ceil4(row_h + 80)


def test_siblings_keep_their_gap_and_do_not_overlap(measure):
    placed = boxes(build(tree_spec(), measure))
    for depth in {y for _, y, _, _ in placed.values()}:
        row = sorted((b for b in placed.values() if b[1] == depth), key=lambda b: b[0])
        for a, b in zip(row, row[1:]):
            assert b[0] - (a[0] + a[2]) >= 44, (a, b)   # H_GAP minus the grid snap


def test_every_parent_is_centred_over_its_children(measure):
    """The tidy-layout invariant: a box sits over the extremes below it."""
    data = tree_spec()
    scene = build(data, measure)
    placed = boxes(scene)

    def centre(name):
        x, _, w, _ = placed[name]
        return x + w / 2.0

    def pairs(node):
        children = node.get("children", [])
        if children:
            yield node, children
        for child in children:
            yield from pairs(child)

    for parent, children in pairs(data["tree"]):
        wants = (centre(children[0]["id"]) + centre(children[-1]["id"])) / 2.0
        assert abs(centre(parent["id"]) - wants) <= 2.0, parent["id"]


def test_the_root_is_centred_on_the_canvas(measure):
    scene = build(tree_spec(), measure)
    x, _, w, _ = boxes(scene)["root"]
    assert abs((x + w / 2.0) - scene.width / 2.0) <= 2.0


def test_the_root_centring_yields_to_the_margins(measure):
    """A chart wider than its canvas is pinned to the margin, not pushed off it."""
    data = tree_spec(canvas=None, preset=None)
    data["tree"]["children"][0]["label"] = "A very long branch name indeed"
    scene = build(data, measure)
    placed = boxes(scene)
    left = min(x for x, _, _, _ in placed.values())
    right = max(x + w for x, _, w, _ in placed.values())
    assert left >= 40 - 2 and right <= scene.width - 40 + 2


def test_rows_are_uniform(measure):
    """Same depth, same y — one row pitch for the whole chart."""
    scene = build(tree_spec(), measure)
    placed = boxes(scene)
    assert placed["root"][1] < placed["runtime"][1] < placed["frames"][1]
    assert placed["runtime"][1] == placed["quality"][1]
    assert placed["frames"][1] == placed["cache"][1] == placed["lint"][1]


def test_a_shallow_branch_tucks_under_a_deep_one(measure):
    """Contour threading, which is the difference from evenly-spaced columns.

    A layout that reserved each subtree's full width would push the leaf clear
    of the fan's whole extent. Reingold–Tilford only has to clear the contours
    it actually meets, so two boxes at *different* depths share a column — while
    two at the same depth still never touch.
    """
    data = tree_spec()
    data["tree"]["children"] = [
        {"id": "fan", "label": "Fan", "children": [
            {"id": "f1", "label": "Leaf one"}, {"id": "f2", "label": "Leaf two"}]},
        {"id": "solo", "label": "Solo"},
    ]
    placed = boxes(build(data, measure))
    assert placed["solo"][0] < placed["f2"][0] + placed["f2"][2]
    for depth in {y for _, y, _, _ in placed.values()}:
        row = sorted((b for b in placed.values() if b[1] == depth), key=lambda b: b[0])
        assert all(n[0] >= p[0] + p[2] for p, n in zip(row, row[1:]))


def test_layout_is_deterministic(measure):
    assert compose(tree_spec(), measurer=measure) == compose(tree_spec(), measurer=measure)


def test_a_deep_chain_stays_a_column(measure):
    data = {"diagram": "tree", "canvas": {"width": 600, "height": 520},
            "tree": {"id": "a", "label": "A", "children": [
                {"id": "b", "label": "B", "children": [
                    {"id": "c", "label": "C", "children": [
                        {"id": "d", "label": "D"}]}]}]}}
    placed = boxes(build(data, measure))
    assert len({x + w / 2.0 for x, _, w, _ in placed.values()}) == 1


def test_a_wide_tree_is_warned_about_but_built(measure):
    data = tree_spec()
    data["tree"]["children"] = [{"label": f"Box {i}", "id": f"b{i}"} for i in range(16)]
    scene = build(data, measure)
    assert any("budget" in w for w in scene.warnings)
    assert len(boxes(scene)) == 17


# ---------------------------------------------------------------------------
# connectors
# ---------------------------------------------------------------------------


def test_every_reporting_line_is_drawn_once(measure):
    scene = build(tree_spec(), measure)
    assert set(connectors(scene)) == {"root->runtime", "root->quality",
                                      "runtime->frames", "runtime->cache",
                                      "quality->lint"}


def test_a_connector_lands_on_the_childs_top_edge_pointing_down(measure):
    scene = build(tree_spec(), measure)
    placed = boxes(scene)
    for name, path in connectors(scene).items():
        parent, child = name.split("->")
        px, py, pw, ph = placed[parent]
        cx, cy, cw, ch = placed[child]
        assert path.points[0] == (px + pw / 2.0, py + ph)
        assert path.points[-1] == (cx + cw / 2.0, cy)
        assert path.head_at is not None and path.head_at[2] == pytest.approx(90.0)


def test_siblings_share_one_trunk(measure):
    """Documented divergence from `flow`: the shared trunk *is* the relation."""
    data = tree_spec()
    data["tree"]["children"][0]["children"].append({"label": "Third", "id": "third"})
    scene = build(data, measure)
    buses = {name: path.points[1][1] for name, path in connectors(scene).items()
             if name.startswith("root->")}
    assert len(set(buses.values())) == 1


def test_a_child_directly_below_its_parent_gets_a_straight_line(measure):
    data = {"diagram": "tree", "canvas": {"width": 400, "height": 400},
            "tree": {"id": "p", "label": "P", "children": [{"id": "c", "label": "C"}]}}
    path = next(iter(connectors(build(data, measure)).values()))
    assert len(path.points) == 2
    assert path.points[0][0] == path.points[1][0]


# ---------------------------------------------------------------------------
# the page machinery is shared, not re-derived
# ---------------------------------------------------------------------------


def test_the_preset_sets_the_canvas_and_the_ramp(measure):
    scene = build(tree_spec(preset="slide-16x9", canvas=None), measure)
    assert (scene.width, scene.height) == (1280, 720)
    title = next(p for g in scene.groups if g.name == "header"
                 for p in g.parts if p.kind == "title")
    assert title.size == 40                     # the presentation ramp, from tokens


def test_the_title_block_and_legend_come_from_the_page(measure):
    scene = build(tree_spec(), measure)
    names = [g.name for g in scene.groups]
    assert names[-2:] == ["header", "legend"]      # legend hangs off the bottom
    kinds = {p.kind for g in scene.groups if g.name == "header" for p in g.parts}
    assert kinds == {"title"}


def test_one_node_type_means_no_legend(measure):
    data = tree_spec()
    for node in (data["tree"], *data["tree"]["children"]):
        node.pop("type", None)
    assert "legend" not in [g.name for g in build(data, measure).groups]


def test_reveal_staggers_the_same_clock(measure):
    scene = build(tree_spec(reveal=True), measure)
    starts = [g.start for g in scene.groups if g.start]
    assert starts == sorted(starts) and len(starts) > len(boxes(scene))
    assert scene.duration > 1.0


def test_the_sketchy_skin_draws_the_tree_rough(measure):
    scene = build(tree_spec(skin="sketchy"), measure)
    node = next(g for g in scene.groups if g.name == "node:root")
    assert any(isinstance(p, Path) for p in node.parts)
    assert scene.groups[-1].name == "legend"       # the page's strip, still last


def test_the_tree_renders_with_the_real_measurer():
    from nanoframes.render import measurer

    scene = build_scene(parse_spec(tree_spec(preset="doc-wide", canvas=None)),
                        measurer=measurer())
    assert scene.warnings == []
    assert all(box[2] >= 80 and box[3] >= 48 for box in boxes(scene).values())


# ---------------------------------------------------------------------------
# CLI: one verb per grammar
# ---------------------------------------------------------------------------


def run_cli(*argv):
    return subprocess.run([sys.executable, "-m", "nanoframes", *argv],
                          capture_output=True, text=True)


def test_cli_tree_builds_a_composition(tmp_path):
    spec_path = tmp_path / "org.json"
    spec_path.write_text(json.dumps(tree_spec()), encoding="utf-8")
    out = tmp_path / "org.nf.svg"
    proc = run_cli("tree", str(spec_path), "-o", str(out), "--check")
    assert proc.returncode == 0, proc.stderr
    assert "wrote" in proc.stdout and "<svg" in out.read_text(encoding="utf-8")


def test_cli_tree_default_output_name(tmp_path):
    spec_path = tmp_path / "org.nf.json"
    spec_path.write_text(json.dumps(tree_spec()), encoding="utf-8")
    proc = run_cli("tree", str(spec_path))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "org.nf.svg").exists()


def test_cli_tree_reports_spec_errors(tmp_path):
    spec_path = tmp_path / "bad.json"
    data = tree_spec()
    data["tree"]["children"][0]["x"] = 4
    spec_path.write_text(json.dumps(data), encoding="utf-8")
    proc = run_cli("tree", str(spec_path))
    assert proc.returncode == 1
    assert "positions are computed" in proc.stderr


def test_each_verb_refuses_the_other_grammars_spec(tmp_path):
    flow = tmp_path / "flow.json"
    flow.write_text(json.dumps({"diagram": "flow", "nodes": [{"label": "A", "x": 0, "y": 0}]}),
                    encoding="utf-8")
    tree = tmp_path / "tree.json"
    tree.write_text(json.dumps(tree_spec()), encoding="utf-8")
    wrong = run_cli("tree", str(flow))
    assert wrong.returncode == 2 and "nanoframes diagram" in wrong.stderr
    other = run_cli("diagram", str(tree))
    assert other.returncode == 2 and "nanoframes tree" in other.stderr


def test_the_shipped_org_chart_is_this_grammar():
    spec = json.load(open(os.path.join(EXAMPLES, "org-chart.nf.json"), encoding="utf-8"))
    assert spec["diagram"] == "tree"
    assert not any("x" in node or "y" in node for node in _all_nodes(spec["tree"]))


def _all_nodes(node):
    yield node
    for child in node.get("children", []):
        yield from _all_nodes(child)


def test_the_shipped_org_chart_has_one_line_into_every_box_but_the_root():
    """The rendered example is an org chart: n boxes, n-1 lines, all arriving downward."""
    from nanoframes.diagram import load_spec

    scene = build_scene(load_spec(os.path.join(EXAMPLES, "org-chart.nf.json")),
                        measurer=FakeMeasurer())
    placed = boxes(scene)
    drawn = connectors(scene)
    assert len(drawn) == len(placed) - 1
    assert all(math.isclose(p.head_at[2], 90.0) for p in drawn.values())

"""The chart grammar — the two primitives it adds, and the seam it reuses.

`flow`/`loop`/`tree` are locked by their shipped examples (tests/test_diagram.py
rebuilds them byte for byte, tests/digests.json pins their frames), so the
questions here are about the *new* compiler: does the spec refuse every
coordinate, does the tick algorithm produce 1/2/5 × 10^k boundaries, does the
plot land on the shared 4px grid, and is a bar's height exactly proportional to
its value — asserted against the scene IR, never against SVG text.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import pytest

from nanoframes.diagram import GRAMMARS, build_scene, compose, load_spec, parse_spec
from nanoframes.diagram import geometry as geo
from nanoframes.diagram.chart import format_tick, nice_step, nice_ticks
from nanoframes.diagram.scene import Path, Rect, Text
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


def chart_spec(**over):
    spec = {
        "diagram": "chart",
        "title": "",
        "chart": {
            "type": "bar",
            "categories": ["Q1", "Q2", "Q3", "Q4"],
            "series": [{"label": "Shipped", "values": [12, 18, 9, 21]}],
            "x_label": "Quarter",
            "y_label": "Frames",
            "unit": "k",
        },
    }
    spec.update(over)
    return spec


def build(data, measurer=None):
    return build_scene(parse_spec(data), measurer=measurer)


# -- reading the IR ----------------------------------------------------------


def bars(scene) -> list:
    """``(x, y, w, h)`` for every bar drawn, in paint order."""
    out = []
    for group in scene.groups:
        if not group.name.startswith("series:"):
            continue
        for part in group.parts:
            if isinstance(part, Rect) and part.weight == "box":
                out.append((part.x, part.y, part.w, part.h))
    return out


def named_paths(scene, name: str) -> list:
    for group in scene.groups:
        if group.name == name:
            return [p for p in group.parts if isinstance(p, Path)]
    return []


def paths(scene) -> list:
    return [p for g in scene.groups for p in g.parts if isinstance(p, Path)]


def plot_box(scene) -> tuple:
    """``(x0, y0, x1, y1)`` of the plot area, read off the two axis rules."""
    axis = named_paths(scene, "axis")
    left = next(p for p in axis if p.points[0][0] == p.points[-1][0])
    bottom = next(p for p in axis if p.points[0][1] == p.points[-1][1])
    return (left.points[0][0], left.points[0][1],
            left.points[0][0] + (bottom.points[-1][0] - bottom.points[0][0]),
            left.points[-1][1])


def tick_ys(scene) -> list:
    return [p.points[0][1] for p in paths(scene) if p.points[0][0] != p.points[-1][0]]


# ---------------------------------------------------------------------------
# the seam: the grammar table and the parser agree
# ---------------------------------------------------------------------------


def test_the_chart_is_one_of_the_grammars(measure):
    assert "chart" in GRAMMARS and "chart" in KINDS
    scene = build(chart_spec(), measure)
    assert scene.groups and scene.width > 0 and scene.height > 0


def test_each_verb_refuses_the_other_grammars_spec(tmp_path):
    chart = tmp_path / "chart.json"
    chart.write_text(json.dumps(chart_spec()), encoding="utf-8")
    tree = tmp_path / "tree.json"
    tree.write_text(json.dumps({"diagram": "tree",
                                "tree": {"label": "A"}}), encoding="utf-8")
    wrong = run_cli("tree", str(chart))
    assert wrong.returncode == 2 and "nanoframes chart" in wrong.stderr
    other = run_cli("chart", str(tree))
    assert other.returncode == 2 and "nanoframes tree" in other.stderr
    flow = tmp_path / "flow.json"
    flow.write_text(json.dumps({"diagram": "flow", "nodes": [{"label": "A", "x": 0, "y": 0}]}),
                    encoding="utf-8")
    assert run_cli("chart", str(flow)).returncode == 2


# ---------------------------------------------------------------------------
# the spec: a data table, never a coordinate
# ---------------------------------------------------------------------------


def test_the_spec_takes_a_table_and_nothing_else():
    spec = parse_spec(chart_spec())
    assert spec.kind == "chart"
    assert spec.chart.type == "bar"
    assert spec.chart.categories == ["Q1", "Q2", "Q3", "Q4"]
    assert spec.chart.series[0].label == "Shipped"
    assert spec.chart.series[0].values == [12.0, 18.0, 9.0, 21.0]
    assert (spec.chart.x_label, spec.chart.y_label, spec.chart.unit) == \
        ("Quarter", "Frames", "k")


def test_a_missing_chart_object_is_named():
    with pytest.raises(SpecError) as exc:
        parse_spec({"diagram": "chart", "title": "no table"})
    assert '"chart"' in str(exc.value)


def test_unknown_chart_type_is_refused():
    data = chart_spec()
    data["chart"]["type"] = "pie"
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "bar, line" in str(exc.value)


def test_series_needs_values():
    with pytest.raises(SpecError) as exc:
        parse_spec({"diagram": "chart", "chart": {"series": [{"label": "S"}]}})
    assert "non-empty" in str(exc.value)


def test_one_value_per_category():
    data = chart_spec()
    data["chart"]["series"][0]["values"] = [1, 2, 3]
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "one value per category" in str(exc.value)


def test_values_must_be_finite_numbers():
    data = chart_spec()
    data["chart"]["series"][0]["values"] = [1, 2, "three", 4]
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "finite number" in str(exc.value)


def test_a_missing_category_list_is_numbered():
    """The x axis is still labelled when the author only gives the numbers."""
    data = chart_spec()
    del data["chart"]["categories"]
    assert parse_spec(data).chart.categories == ["1", "2", "3", "4"]


def test_grid_must_be_a_boolean():
    data = chart_spec()
    data["chart"]["grid"] = "yes"
    with pytest.raises(SpecError) as exc:
        parse_spec(data)
    assert "grid" in str(exc.value)


# ---------------------------------------------------------------------------
# the tick algorithm: the 1/2/5 × 10^k ladder
# ---------------------------------------------------------------------------


def _mantissa(value: float) -> float:
    return value / 10.0 ** math.floor(math.log10(abs(value)))


@pytest.mark.parametrize("lo, hi", [(0, 10), (0, 1), (-5, 37), (0, 1e6)])
def test_the_step_is_always_1_2_or_5_times_a_power_of_ten(lo, hi):
    """A reader divides by 2 or by 5 without thinking, and by 3.7 never."""
    ticks, (start, stop) = nice_ticks(lo, hi)
    assert len(ticks) >= 2
    step = ticks[1] - ticks[0]
    mantissa = _mantissa(step)
    assert mantissa == pytest.approx(1.0, rel=1e-9) or \
        mantissa == pytest.approx(2.0, rel=1e-9) or \
        mantissa == pytest.approx(5.0, rel=1e-9)
    # the ladder covers the data, and is evenly spaced end to end
    assert start <= lo and stop >= hi
    assert ticks[-1] == pytest.approx(stop)
    assert all(t == pytest.approx(start + i * step)
               for i, t in enumerate(ticks))


@pytest.mark.parametrize("lo, hi", [(0, 10), (0, 1), (-5, 37), (0, 1e6)])
def test_every_tick_is_on_the_step(lo, hi):
    ticks, _ = nice_ticks(lo, hi)
    step = ticks[1] - ticks[0]
    for value in ticks:
        assert abs(value / step - round(value / step)) < 1e-6, value


def test_the_ladder_is_the_expected_one():
    assert nice_ticks(0, 10)[0] == [0, 2, 4, 6, 8, 10]
    assert nice_ticks(0, 1)[0] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert nice_ticks(-5, 37)[0] == [-10, 0, 10, 20, 30, 40]
    assert nice_ticks(0, 1e6)[0] == [0, 200000, 400000, 600000, 800000, 1000000]


def test_nice_step_snaps_up_to_the_next_ladder_value():
    assert nice_step(0.0001) == pytest.approx(0.0001)
    assert nice_step(1.5) == 2.0
    assert nice_step(3) == 5.0
    assert nice_step(8) == 10.0
    assert nice_step(0) == 1.0 and nice_step(-1) == 1.0


def test_a_degenerate_range_is_widened_never_divided_by():
    """All-zero and single-value series have a zero span; the scale must not."""
    for lo, hi in ((0, 0), (7, 7), (-3, -3)):
        ticks, (start, stop) = nice_ticks(lo, hi)
        assert stop > start
        assert len(ticks) >= 2


def test_an_all_zero_series_builds(measure):
    """The whole chart, not just the scale: no ZeroDivisionError, no empty plot."""
    data = chart_spec()
    data["chart"]["series"][0]["values"] = [0, 0, 0, 0]
    scene = build(data, measure)
    assert bars(scene) == []                     # no bar for a zero value
    assert len(named_paths(scene, "axis")) >= 2  # the axes are still there


def test_a_single_value_series_builds(measure):
    data = chart_spec()
    data["chart"]["categories"] = ["only"]
    data["chart"]["series"][0]["values"] = [42]
    scene = build(data, measure)
    assert len(bars(scene)) == 1


def test_a_single_point_line_series_draws_its_marker(measure):
    """One category is a marker, not a degenerate path: there is no line to draw."""
    data = chart_spec()
    data["chart"]["type"] = "line"
    data["chart"]["categories"] = ["only"]
    data["chart"]["series"][0]["values"] = [42]
    scene = build(data, measure)
    assert len(bars(scene)) == 1                     # the marker
    assert all(p.points for p in paths(scene))       # and no empty path


def test_a_non_zero_value_keeps_a_pixel_of_ink(measure):
    """A tiny value is small, not absent — the bar keeps one pixel of ink."""
    data = chart_spec(preset=None)
    data["chart"]["categories"] = ["big", "tiny"]
    data["chart"]["series"][0]["values"] = [1000000, 1]
    scene = build(data, measure)
    assert len(bars(scene)) == 2
    assert min(h for _, _, _, h in bars(scene)) >= 1.0


def test_tick_labels_are_exact_decimals():
    assert [format_tick(v) for v in (0, 2, 0.2, 0.6, 200000, -10)] == \
        ["0", "2", "0.2", "0.6", "200000", "-10"]


# ---------------------------------------------------------------------------
# the layout: axis, ticks and bars on the shared 4px grid
# ---------------------------------------------------------------------------


def test_axis_ticks_and_bars_land_on_the_4px_grid(measure):
    """The plot's geometry is `geo`'s, not a local ruler's.

    Bar *heights* are exempt and asserted separately below: a height that snaps
    to the grid is no longer proportional to its value, and proportion is what a
    bar chart is for.
    """
    scene = build(chart_spec(), measure)
    x0, y0, x1, y1 = plot_box(scene)
    assert geo.on_grid(x0) and geo.on_grid(x1)
    assert geo.on_grid(y0) and geo.on_grid(y1)
    for y in tick_ys(scene):
        assert geo.on_grid(y), y
    for x, y, w, h in bars(scene):
        assert geo.on_grid(x) and geo.on_grid(w), (x, w)
        assert geo.on_grid(y + h), "the baseline a bar is measured from"  # noqa: B015


def test_a_bar_is_exactly_proportional_to_its_value(measure):
    """The one invariant the whole scale exists for: height / value is constant."""
    values = [12, 18, 9, 21]
    data = chart_spec()
    data["chart"]["series"][0]["values"] = values
    scene = build(data, measure)
    drawn = bars(scene)
    assert len(drawn) == len(values)
    _, _, _, baseline = plot_box(scene)             # the zero rule: all values > 0
    ratios = [(baseline - y) / v for (_, y, _, _), v in zip(drawn, values)]
    assert max(ratios) - min(ratios) < 1e-9
    # and that ratio is the scale the axis shows: plot pixels per axis unit
    _, y0, _, y1 = plot_box(scene)
    _, (lo, hi) = nice_ticks(0, max(values))
    assert ratios[0] == pytest.approx((y1 - y0) / (hi - lo), rel=1e-6)


def test_bars_sit_under_their_category(measure):
    """Bar centres are the band centres — modulo the 4px snap — and so are the labels."""
    scene = build(chart_spec(), measure)
    x0, _, x1, _ = plot_box(scene)
    drawn = bars(scene)
    pitch = (x1 - x0) / len(drawn)
    centres = [x0 + pitch * (i + 0.5) for i in range(len(drawn))]
    for (x, _, w, _), want in zip(drawn, centres):
        assert x + w / 2.0 == pytest.approx(want, abs=2.0)
    labels = [p for g in scene.groups if g.name == "axis" for p in g.parts
              if isinstance(p, Text) and p.kind == "sub" and p.anchor == "middle"]
    assert [p.content for p in labels] == ["Q1", "Q2", "Q3", "Q4"]
    assert [p.x for p in labels] == pytest.approx(centres, abs=0.01)


def test_the_value_axis_always_contains_zero(measure):
    """A bar needs a zero baseline; a line whose axis does not is exaggerated."""
    for values in ([12, 18, 9, 21], [-5, -9, -2, -7], [-4, 8, -3, 11]):
        data = chart_spec()
        data["chart"]["series"][0]["values"] = values
        scene = build(data, measure)
        _, (lo, hi) = nice_ticks(min(0, min(values)), max(0, max(values)))
        assert lo <= 0 <= hi
        # every bar starts at the same rule, and that rule is drawn as an axis
        zero_ends = {round(y + h, 2) if v >= 0 else round(y, 2)
                     for (_, y, _, h), v in zip(bars(scene), values)}
        assert len(zero_ends) == 1
        rules = {round(p.points[0][1], 2) for p in named_paths(scene, "axis")
                 if p.points[0][1] == p.points[-1][1]}
        assert zero_ends <= rules


def test_negative_values_put_the_zero_rule_inside_the_plot(measure):
    data = chart_spec()
    data["chart"]["series"][0]["values"] = [-4, 8, -3, 11]
    scene = build(data, measure)
    _, y0, _, y1 = plot_box(scene)
    rules = [p for p in named_paths(scene, "axis")
             if p.points[0][1] == p.points[-1][1]]
    inside = [p for p in rules if y0 < p.points[0][1] < y1]
    assert inside, "a signed series needs the zero rule drawn inside the plot"


def test_gridlines_are_the_ticks_but_not_the_baseline(measure):
    """The zero rule is an axis, not a grid line — it is what bars are measured from."""
    scene = build(chart_spec(), measure)
    grid = named_paths(scene, "grid")
    ticks, _ = nice_ticks(0, 21)
    _, y0, _, y1 = plot_box(scene)
    ys = {p.points[0][1] for p in grid}
    assert len(grid) == len(ticks) - 1              # every tick but zero
    assert y0 in ys and y0 == min(ys)               # the top tick
    assert y1 not in ys                             # the baseline


def test_turning_the_grid_off_removes_the_rules_not_the_axis(measure):
    data = chart_spec()
    data["chart"]["grid"] = False
    scene = build(data, measure)
    assert named_paths(scene, "grid") == []
    assert len(named_paths(scene, "axis")) > 2


def test_grouped_bars_do_not_overlap(measure):
    data = chart_spec()
    data["chart"]["series"] = [
        {"label": "Shipped", "values": [12, 18, 9, 21]},
        {"label": "Held", "values": [4, 6, 3, 8]},
    ]
    drawn = bars(build(data, measure))
    assert len(drawn) == 8
    for i in range(0, 8, 2):
        left, right = drawn[i], drawn[i + 1]
        assert left[0] + left[2] <= right[0] + 0.01


def test_a_line_series_is_one_polyline_and_a_dot_per_value(measure):
    data = chart_spec()
    data["chart"]["type"] = "line"
    scene = build(data, measure)
    assert len(named_paths(scene, "grid")) >= 1
    line = [p for p in paths(scene) if not p.dash and p.stroke_width == 2.0]
    assert len(line) == 1
    assert len(line[0].points) == 4
    assert len(bars(scene)) == 4                    # the point markers


def test_the_canvas_is_the_declared_page_and_the_plot_fills_it(measure):
    scene = build(chart_spec(canvas={"width": 1280, "height": 720}), measure)
    assert (scene.width, scene.height) == (1280, 720)
    x0, y0, x1, y1 = plot_box(scene)
    assert x1 - x0 > 600 and y1 - y0 > 300          # a figure, not a thumbnail


def test_the_preset_sets_the_canvas_and_the_ramp(measure):
    scene = build(chart_spec(preset="slide-16x9", title="T"), measure)
    assert (scene.width, scene.height) == (1280, 720)
    title = next(p for g in scene.groups if g.name == "header"
                 for p in g.parts if p.kind == "title")
    assert title.size == 40                          # the presentation ramp


def test_fit_derives_the_canvas_from_the_content(measure):
    scene = build(chart_spec(preset=None), measure)
    x0, _, x1, _ = plot_box(scene)
    rail = min(p.x for g in scene.groups for p in g.parts
               if isinstance(p, Text) and p.kind == "sub" and p.anchor == "start")
    assert rail == pytest.approx(40, abs=1)          # the figure starts on the margin
    assert 40 < x0 < x1 < scene.width - 40           # and the plot sits inside it
    assert scene.width < 700                         # a 4-category chart is narrow


def test_the_title_band_offsets_the_chart_exactly_as_it_offsets_a_flow(measure):
    """The fractional y is the page's, and every grammar inherits the same one."""
    flow = build_scene(parse_spec({
        "diagram": "flow", "title": "T", "canvas": {"width": 480, "height": 240},
        "nodes": [{"id": "a", "label": "A", "x": 40, "y": 160}]}), measurer=measure)
    flow_y = next(p.y for g in flow.groups if g.name == "node:a"
                  for p in g.parts if isinstance(p, Rect) and p.weight == "box")
    assert not geo.on_grid(flow_y)
    scene = build(chart_spec(title="T"), measure)
    _, y0, _, y1 = plot_box(scene)
    assert round(y0 % 4, 2) == round(flow_y % 4, 2)
    assert round(y1 % 4, 2) == round(flow_y % 4, 2)


def test_the_plot_is_centred_on_a_wider_canvas(measure):
    """The *figure* is centred (labels and all), snapped to the grid, inside the margins."""
    scene = build(chart_spec(canvas={"width": 1600, "height": 720}), measure)
    x0, _, x1, _ = plot_box(scene)
    rail = min(p.x for g in scene.groups for p in g.parts
               if isinstance(p, Text) and p.kind == "sub" and p.anchor == "start")
    assert (rail + x1 + 6) / 2.0 == pytest.approx(scene.width / 2.0, abs=4.0)
    assert rail >= 40 and rail > 44          # it really moved off the margin
    assert geo.on_grid(x0) and geo.on_grid(rail)


def test_layout_is_deterministic(measure):
    assert compose(chart_spec(), measurer=measure) == compose(chart_spec(), measurer=measure)


# ---------------------------------------------------------------------------
# the page machinery is shared, not re-derived
# ---------------------------------------------------------------------------


def test_two_series_get_the_legend_and_one_does_not(measure):
    assert "legend" not in [g.name for g in build(chart_spec(), measure).groups]
    data = chart_spec()
    data["chart"]["series"].append({"label": "Held", "values": [1, 2, 3, 4]})
    scene = build(data, measure)
    legend = next(g for g in scene.groups if g.name == "legend")
    text = [p.content for p in legend.parts if isinstance(p, Text)]
    assert "SHIPPED" in text and "HELD" in text


def test_the_shipped_palette_paints_the_second_series(measure):
    data = chart_spec()
    data["chart"]["series"].append({"label": "Held", "values": [1, 2, 3, 4]})
    scene = build(data, measure)
    fills = {p.fill for g in scene.groups if g.name.startswith("series:")
             for p in g.parts if isinstance(p, Rect) and p.weight == "box"}
    from nanoframes.diagram.tokens import resolve

    tokens = resolve("light", None)
    assert fills == {tokens.accent, tokens.link}


def test_reveal_staggers_the_same_clock(measure):
    """The data reveals; the axes are furniture and are simply there."""
    from nanoframes.diagram.canvas import REVEAL_STEP

    data = chart_spec(reveal=True)
    data["chart"]["series"].append({"label": "Held", "values": [1, 2, 3, 4]})
    scene = build(data, measure)
    series = [(g.start, g.fade) for g in scene.groups if g.name.startswith("series:")]
    assert [start for start, _ in series] == [0.0, REVEAL_STEP]
    assert all(fade > 0 for _, fade in series)
    assert all(g.fade == 0 for g in scene.groups if not g.name.startswith("series:"))


def test_the_sketchy_skin_draws_the_bars_rough(measure):
    scene = build(chart_spec(skin="sketchy"), measure)
    first = next(g for g in scene.groups if g.name == "series:0")
    assert any(isinstance(p, Path) for p in first.parts)
    assert any(isinstance(p, Rect) for p in first.parts)   # the plate underneath


def test_value_labels_only_when_one_series_says_the_reading(measure):
    data = chart_spec()
    scene = build(data, measure)
    labels = [p.content for g in scene.groups if g.name == "labels"
              for p in g.parts if isinstance(p, Text)]
    assert labels == ["12", "18", "9", "21"]
    data["chart"]["series"].append({"label": "Held", "values": [1, 2, 3, 4]})
    assert "labels" not in [g.name for g in build(data, measure).groups]


def test_a_wide_chart_is_warned_about_but_built(measure):
    data = chart_spec()
    data["chart"]["categories"] = [f"C{i}" for i in range(20)]
    data["chart"]["series"][0]["values"] = list(range(1, 21))
    scene = build(data, measure)
    assert any("budget" in w for w in scene.warnings)
    assert len(bars(scene)) == 20


def test_the_chart_renders_with_the_real_measurer():
    from nanoframes.render import measurer

    scene = build_scene(parse_spec(chart_spec(preset="doc-wide")), measurer=measurer())
    assert scene.warnings == []
    assert (scene.width, scene.height) == (1280, 720)


# ---------------------------------------------------------------------------
# CLI: one verb per grammar, and the shipped examples
# ---------------------------------------------------------------------------


def run_cli(*argv):
    return subprocess.run([sys.executable, "-m", "nanoframes", *argv],
                          capture_output=True, text=True)


def test_cli_chart_builds_a_composition(tmp_path):
    spec_path = tmp_path / "table.json"
    spec_path.write_text(json.dumps(chart_spec()), encoding="utf-8")
    out = tmp_path / "table.nf.svg"
    proc = run_cli("chart", str(spec_path), "-o", str(out), "--check")
    assert proc.returncode == 0, proc.stderr
    assert "wrote" in proc.stdout and "<svg" in out.read_text(encoding="utf-8")


def test_cli_chart_default_output_name(tmp_path):
    spec_path = tmp_path / "table.nf.json"
    spec_path.write_text(json.dumps(chart_spec()), encoding="utf-8")
    proc = run_cli("chart", str(spec_path))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "table.nf.svg").exists()


def test_cli_chart_reports_spec_errors(tmp_path):
    spec_path = tmp_path / "bad.json"
    data = chart_spec()
    data["chart"]["series"][0]["values"] = [1, 2]
    spec_path.write_text(json.dumps(data), encoding="utf-8")
    proc = run_cli("chart", str(spec_path))
    assert proc.returncode == 1
    assert "one value per category" in proc.stderr


@pytest.mark.parametrize("name", ["throughput.nf.json", "net-change.nf.json"])
def test_the_shipped_charts_are_data_tables(name):
    spec = json.load(open(os.path.join(EXAMPLES, name), encoding="utf-8"))
    assert spec["diagram"] == "chart"
    assert "nodes" not in spec and "edges" not in spec
    for key in ("x", "y", "w", "h", "canvas", "width", "height"):
        assert key not in spec["chart"], key
    for series in spec["chart"]["series"]:
        assert set(series) == {"label", "values"}


@pytest.mark.parametrize("name", ["throughput.nf.json", "net-change.nf.json"])
def test_the_shipped_charts_build_warning_free(name):
    from nanoframes.render import measurer

    scene = build_scene(load_spec(os.path.join(EXAMPLES, name)), measurer=measurer())
    assert scene.warnings == []
    # paint order: the rules first, the series over them (the paper is `#bg`)
    assert [g.name for g in scene.groups][:2] == ["grid", "axis"]

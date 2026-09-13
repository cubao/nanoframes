"""The chart grammar: a data table → a scaled, ticked chart.

The third *computed* grammar (``tree`` was the second): the spec carries the
numbers and their labels and nothing else — no coordinates, no pixel sizes, not
even an axis bound — and the compiler turns the table into geometry. Two
primitives live here that no other grammar needed, and only here:

* a **linear scale** — a value → a position, over a domain the compiler
  *chooses* rather than one the author declares;
* a **tick algorithm** — an axis is *read*, not measured, so its boundaries have
  to land on numbers a reader can divide: 1, 2 or 5 times a power of ten.

Everything else is inherited. The page machinery (``nanoframes.diagram.canvas``)
supplies the paper, the title band, the legend, the reveal clock and the canvas
floor; ``geometry`` supplies the 4px grid; ``tokens`` supplies the palette;
``text`` supplies the measured runs. A chart is one entry of the package's
grammar table (:data:`nanoframes.diagram.GRAMMARS`) producing the same
:class:`~nanoframes.diagram.scene.Scene`, so it lints, renders, animates and
digests exactly like a diagram.

Two taste rules are worth stating because they are decisions, not defaults:

* **The value axis always contains zero.** A bar needs a zero baseline to say
  anything true about proportion, and a line whose axis starts at the smallest
  observed value exaggerates every wiggle; one rule for both is worth the flat
  line it occasionally draws.
* **Grid, axis and ticks are the same four numbers everywhere** — the top tick,
  the zero baseline, the band pitch — so the plot's geometry is derived from the
  tick count rather than from a target pixel height. That is also what keeps
  every rule on the 4px grid after a round of nice-number rounding.
"""

from __future__ import annotations

import math

from nanoframes.diagram import geometry as geo
from nanoframes.diagram import sketchy
from nanoframes.diagram import text as txt
from nanoframes.diagram.canvas import (
    LEGEND_H,
    REVEAL_FADE,
    Canvas,
    box_parts,
    rough,
)
from nanoframes.diagram.scene import Group, Path, Rect, Scene, Text
from nanoframes.diagram.spec import Spec
from nanoframes.diagram.tokens import FONT_MONO, PRESETS, Tokens

# One tick's worth of plot height, before the tick count is known: the plot is
# `ceil4(PLOT_H_HINT / gaps) * gaps` tall, so every gridline is an exact
# multiple of a grid multiple below the baseline.
PLOT_H_HINT = 320.0
PLOT_H_MAX = 640.0
PLOT_H_MIN = 64.0
# Air between the value axis and its tick labels, and the tick mark's own length.
TICK_LEN = 6.0
TICK_GAP = 6.0
# Narrowest band a category may get, and the air a category label adds on top.
# The maximum keeps a one- or two-category chart from drawing a bar a third of
# the page wide: past this the plot is centred instead of stretched.
BAND_MIN = 64.0
BAND_MAX = 160.0
BAND_PAD = 24.0
# A bar takes this fraction of its band (or of the sub-band a grouped series gets).
BAR_RATIO = 0.62
BAR_FILL = 0.9
DOT = 4.0
# One ramp line of air for an axis title eyebrow, above the plot or below the
# category labels.
EYEBROW_H = 24.0
# Value labels are the single-series reading; with several series the y axis is.
VALUE_LABEL_PAD = 6.0

TARGET_TICKS = 5
# Taste budgets, as warnings: a chart past either reads as a table.
BUDGET_CATEGORIES = 12
BUDGET_SERIES = 4
# Series paints, in order, from the page's token set: the first series carries
# the accent (it is the claim), the rest are the quieter inks.
_SERIES_PAINT = ("accent", "link", "muted", "ink", "soft")


# ---------------------------------------------------------------------------
# the two new primitives: a scale and a tick algorithm
# ---------------------------------------------------------------------------


def nice_step(raw: float) -> float:
    """The next 1/2/5 × 10^k step at or above ``raw``.

    This is the whole reason an axis is legible: a reader divides by 2 or by 5
    without thinking and by 3.7 never. Heckbert's *Nice Numbers for Graph
    Labels* (Graphics Gems, 1990) in its simplest form — snap the mantissa up to
    the next of 1, 2, 5, 10 and keep the exponent.
    """
    if not math.isfinite(raw) or raw <= 0:
        return 1.0
    exponent = math.floor(math.log10(raw))
    base = 10.0 ** exponent
    fraction = raw / base
    for multiple in (1.0, 2.0, 5.0, 10.0):
        if fraction <= multiple + 1e-9:
            return float(multiple * base)
    return float(10.0 * base)


def nice_ticks(lo: float, hi: float, target: int = TARGET_TICKS) -> tuple[list, tuple]:
    """``(ticks, (lo, hi))`` — a 1/2/5 × 10^k ladder covering ``[lo, hi]``.

    The domain that comes back is the ticks' own extent, not the input's: an
    axis labelled 0, 10, 20, …, 40 for data topping out at 37 is the point of
    the algorithm. A degenerate input (every value zero, or a single value) is
    widened rather than divided by: the scale's span is never zero.
    """
    if not (math.isfinite(lo) and math.isfinite(hi)):
        lo, hi = 0.0, 1.0
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        lo, hi = (0.0, 1.0) if lo == 0 else (min(0.0, lo), max(0.0, hi))
    step = nice_step((hi - lo) / float(target))
    start = math.floor(lo / step + 1e-9) * step
    stop = math.ceil(hi / step - 1e-9) * step
    gaps = int(round((stop - start) / step))
    if gaps < 1:
        # A step that swallowed the whole range: one interval is always enough.
        stop, gaps = start + step, 1
    ticks = [round(start + i * step, 10) for i in range(gaps + 1)]
    return ticks, (ticks[0], ticks[-1])


def format_tick(value: float) -> str:
    """A tick's text: an integer when it is one, else the shortest exact decimal."""
    if abs(value) < 1e-9:
        return "0"
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):d}"
    return f"{value:.10f}".rstrip("0").rstrip(".") or "0"


# ---------------------------------------------------------------------------
# the compiler
# ---------------------------------------------------------------------------


def build_chart(spec: Spec, tokens: Tokens, measurer) -> Scene:
    """Compile a chart spec into a scene (the grammar's one entry point)."""
    b = Canvas(spec, tokens, measurer)
    t = tokens
    chart = spec.chart
    if chart is None:
        raise ValueError('a "chart" diagram needs a "chart" object')

    n = len(chart.categories)
    k = len(chart.series)
    if n > BUDGET_CATEGORIES:
        b.warnings.append(
            f"{n} categories over the {BUDGET_CATEGORIES}-category budget — a chart this"
            " wide reads as a table: split it by period, or show one window"
        )
    if k > BUDGET_SERIES:
        b.warnings.append(
            f"{k} series over the {BUDGET_SERIES}-series budget — one line per claim:"
            " fold the rest into a total, or split the chart"
        )

    ramp = t.ramp
    tick_size = float(ramp["sub"])
    cat_size = float(ramp["sub"] + 1)
    val_size = float(ramp["tag"] + 1)

    # -- the value scale ------------------------------------------------------
    # Zero is in the domain by construction (see the module docstring), so the
    # data's own extremes only ever push one end of it.
    values = [v for series in chart.series for v in series.values]
    ticks, (lo, hi) = nice_ticks(min(0.0, min(values, default=0.0)),
                                 max(0.0, max(values, default=0.0)))
    gaps = len(ticks) - 1
    step = (hi - lo) / gaps
    zero_tick = int(round((0.0 - lo) / step))
    target_w, target_h = _target(spec)

    # -- measured text, and the gutters it needs ------------------------------
    y_labels = [format_tick(v) for v in ticks]
    y_w = max(txt.measure(measurer, s, FONT_MONO, "400", tick_size).width
              for s in y_labels)
    cat_metrics = [txt.measure(measurer, c, FONT_MONO, "400", cat_size)
                   for c in chart.categories]
    cat_ascent = max(-m.top for m in cat_metrics)
    cat_descent = max(m.bottom for m in cat_metrics)
    cat_h = cat_ascent + cat_descent
    # The label rail is the margin itself and the tick labels are left-aligned on
    # it, so the figure's left edge is the margin exactly and `finish` has no
    # reason to shift the chart — a shift would leave the plot off the 4px grid.
    rail = spec.margin
    plot_left = geo.ceil4(rail + TICK_LEN + TICK_GAP + y_w + TICK_GAP)
    right_pad = TICK_GAP

    header = b.header_height()
    y_title = _axis_title(chart.y_label, chart.unit)
    value_labels = chart.type == "bar" and k == 1
    # Both bands above the plot are grid multiples, so the plot's own top is one.
    top_pad = geo.ceil4(val_size + VALUE_LABEL_PAD) if value_labels else 0.0
    legend_h = LEGEND_H if _wants_legend(spec, k) else 0.0

    # -- the two scales, in pixels --------------------------------------------
    # A declared page is filled: a chart is a figure, and four categories huddled
    # in a corner of a 1280x720 canvas read as a mistake. `fit` (no canvas, no
    # preset) takes the natural size instead. A band is an *even* number of grid
    # cells because its centre — where the bar and the tick mark go — is half a
    # band from its left edge, and a grid-point centre needs an even count.
    band_natural = geo.ceil8(max(BAND_MIN, max(m.width for m in cat_metrics) + BAND_PAD))
    band_w = band_natural
    if target_w is not None:
        avail_w = target_w - 2 * spec.margin - (plot_left - rail) - right_pad
        band_w = min(BAND_MAX, max(band_natural, geo.floor8(avail_w / n)))
    plot_w = band_w * n
    content_w = plot_left + plot_w + right_pad - rail

    chrome = (2 * spec.margin + header + (EYEBROW_H if y_title else 0.0)
              + top_pad
              + TICK_LEN + TICK_GAP + cat_h + TICK_GAP
              + (EYEBROW_H if chart.x_label else 0.0) + legend_h)
    # The plot's height is the tick count times a grid-multiple step, so every
    # gridline is an exact multiple of 4 below the baseline — which is also what
    # makes a bar's height exactly proportional to its value. Filling a declared
    # page rounds that step *down*, so the plot never pushes the page past the
    # size the author asked for.
    if target_h is None:
        px_per_step = max(PLOT_H_MIN, geo.ceil4(PLOT_H_HINT / gaps))
    else:
        px_per_step = geo.floor4(max(0.0, target_h - chrome) / gaps)
    px_per_step = max(PLOT_H_MIN, min(px_per_step, geo.floor4(PLOT_H_MAX / gaps)))
    plot_h = px_per_step * gaps

    # -- the page box ---------------------------------------------------------
    figure_top = spec.margin + header
    plot_top = figure_top + (EYEBROW_H if y_title else 0.0) + top_pad
    plot_bottom = plot_top + plot_h
    zero_y = plot_bottom - zero_tick * px_per_step
    cat_top = plot_bottom + TICK_LEN + TICK_GAP
    x_label_top = cat_top + cat_h + TICK_GAP
    figure_bottom = x_label_top + (EYEBROW_H if chart.x_label else 0.0)
    content_h = figure_bottom - figure_top

    floor = (geo.ceil4(content_w + 2 * spec.margin),
             geo.ceil4(content_h + 2 * spec.margin + header + legend_h))
    minimum = (max(target_w or 0.0, floor[0]), max(target_h or 0.0, floor[1]))
    origin = _origin(minimum[0], content_w, spec.margin)
    ox = origin - rail

    def band_centre(index: int) -> float:
        return ox + plot_left + band_w * index + band_w / 2.0

    def value_y(value: float) -> float:
        return plot_bottom - (value - lo) / step * px_per_step

    # -- the rules: grid, then the axes over it -------------------------------
    x0, x1 = ox + plot_left, ox + plot_left + plot_w
    grid = Group(name="grid", start=0.0, fade=0.0)
    if chart.grid:
        for i in range(gaps + 1):
            if i == zero_tick:
                continue          # the baseline is drawn as an axis, not as a grid
            y = _r2(plot_bottom - i * px_per_step)
            grid.parts.append(_rule([(x0, y), (x1, y)], t.rule_solid, 1.0,
                                    f"grid:{i}", t))

    axis = Group(name="axis", start=0.0, fade=0.0)
    axis.parts.append(_rule([(x0, plot_top), (x0, plot_bottom)], t.rule, 1.2,
                            "axis:y", t))
    axis.parts.append(_rule([(x0, plot_bottom), (x1, plot_bottom)], t.rule, 1.2,
                            "axis:x", t))
    if zero_tick > 0:
        # A domain with negative values puts the zero rule inside the plot; it is
        # what the bars are measured from, so it is drawn as an axis rule.
        y = _r2(plot_bottom - zero_tick * px_per_step)
        axis.parts.append(_rule([(x0, y), (x1, y)], t.rule, 1.2, "axis:zero", t))
    for i, label in enumerate(y_labels):
        y = _r2(plot_bottom - i * px_per_step)
        axis.parts.append(_rule([(x0 - TICK_LEN, y), (x0, y)], t.rule_solid, 1.0,
                                f"ytick:{i}", t))
        metrics = txt.measure(measurer, label, FONT_MONO, "400", tick_size)
        axis.parts.append(Text(
            x=round(origin, 1), y=round(y - (metrics.top + metrics.bottom) / 2.0, 1),
            content=label, size=tick_size, fill=t.muted, family=FONT_MONO,
            anchor="start", kind="sub"))
    for i, category in enumerate(chart.categories):
        cx = round(band_centre(i), 1)
        axis.parts.append(_rule([(cx, plot_bottom), (cx, plot_bottom + TICK_LEN)],
                                t.rule_solid, 1.0, f"xtick:{i}", t))
        axis.parts.append(Text(
            x=cx, y=round(plot_bottom + TICK_LEN + TICK_GAP + cat_ascent, 1),
            content=category, size=cat_size, fill=t.muted, family=FONT_MONO,
            anchor="middle", kind="sub"))
    if y_title:
        axis.parts.append(_eyebrow(origin, figure_top, y_title, tick_size, t.muted,
                                   "start"))
    if chart.x_label:
        axis.parts.append(_eyebrow((x0 + x1) / 2.0, x_label_top, chart.x_label,
                                   tick_size, t.muted, "middle"))

    # -- the series -----------------------------------------------------------
    groups = [b.background(minimum[0], minimum[1]), grid, axis]
    labels = Group(name="labels", start=0.0, fade=0.0)
    for j, series in enumerate(chart.series):
        paint = _series_paint(t, j)
        g = Group(name=f"series:{j}")
        g.start, g.fade = b.slice(REVEAL_FADE)
        style = {"fill": paint, "fill_opacity": BAR_FILL, "stroke": paint,
                 "stroke_opacity": 1.0, "stroke_width": 1.0}
        if chart.type == "bar":
            sub = band_w if k == 1 else band_w / k
            bar_w = max(4.0, geo.q4(sub * BAR_RATIO))
            for i, value in enumerate(series.values):
                centre = (band_centre(i) if k == 1
                          else band_centre(i) - band_w / 2.0 + sub * (j + 0.5))
                top, bottom = sorted((value_y(value), zero_y))
                if value and bottom - top < 1.0:
                    # A non-zero value that rounds away is still a value: one
                    # pixel of ink says "small", and drawing nothing would say
                    # "none". A true zero keeps drawing nothing.
                    bottom = top + 1.0
                if bottom - top < 0.5:
                    continue      # a zero value draws no bar; its label says "0"
                g.parts += box_parts(geo.q4(centre - bar_w / 2.0), _r2(top),
                                     bar_w, _r2(bottom - top), f"bar:{j}:{i}",
                                     style, t, rx=2.0)
                if value_labels:
                    metrics = txt.measure(measurer, format_tick(value), FONT_MONO,
                                          "400", val_size)
                    top_y = (top - val_size - VALUE_LABEL_PAD / 2.0 if value >= 0
                             else bottom + VALUE_LABEL_PAD / 2.0)
                    labels.parts.append(Text(
                        x=round(centre, 1), y=round(top_y - metrics.top, 1),
                        content=format_tick(value), size=val_size, fill=t.muted,
                        family=FONT_MONO, anchor="middle", kind="sub"))
        else:
            points = [(round(band_centre(i), 2), _r2(value_y(v)))
                      for i, v in enumerate(series.values)]
            if len(points) >= 2:
                g.parts.append(_series_line(points, paint, f"series:{j}", t))
            for x, y in points:
                # A marker per value, which is also what a one-category series
                # draws: there is no line to draw between a point and itself.
                g.parts.append(Rect(x=_r2(x - DOT / 2.0), y=_r2(y - DOT / 2.0),
                                    w=DOT, h=DOT, rx=1.0, fill=paint,
                                    fill_opacity=1.0, weight="box"))
        groups.append(g)
    if labels.parts:
        groups.append(labels)

    head = Group(name="header", start=0.0, fade=0.0)
    head.parts += b.title_block()
    if head.parts:
        groups.append(head)
    items = (_legend_items(chart, t) if _wants_legend(spec, k) else [])
    return b.to_scene(groups, minimum=minimum, place=b.legend(minimum[0], items))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _r2(value: float) -> float:
    return round(value, 2)


def _origin(min_w: float, content_w: float, margin: float) -> float:
    """The figure's left edge: centred in the slack, on the grid, inside the margins.

    Snapping the *slack* rather than the edge keeps the shift a grid multiple,
    which is what lets the plot's own coordinates stay on the 4px grid after the
    figure has been centred on a wide canvas.
    """
    slack = max(0.0, min_w - content_w - 2.0 * margin)
    return margin + geo.q4(slack / 2.0)


def _target(spec: Spec) -> tuple:
    """The declared page size, or ``(None, None)`` when the canvas is derived.

    A preset is a page like an explicit ``canvas`` is (both are a *minimum*
    everywhere else in the package), and a chart fills the page it is given
    rather than floating in the middle of it.
    """
    if spec.canvas:
        return spec.canvas
    if spec.preset and spec.preset in PRESETS:
        return PRESETS[spec.preset][0], PRESETS[spec.preset][1]
    return None, None


def _axis_title(label: str, unit: str) -> str:
    """The value axis' title, with the unit folded in: ``Frames (k)``.

    The unit is part of how the axis is read, not a separate piece of furniture —
    one eyebrow above the plot says both, and no tick label carries a suffix it
    would have to repeat.
    """
    parts = [label] if label else []
    if unit:
        parts.append(f"({unit})")
    return " ".join(parts)


def _eyebrow(x: float, top: float, content: str, size: float, fill: str,
             anchor: str) -> Text:
    """An axis title, with its *em box* starting at ``top``.

    Aligning the em box rather than the ink is what keeps the figure's own
    conservative bounds starting exactly at the page margin: ``union_bounds``
    measures a run from ``baseline - size``, so a run whose em box starts at the
    margin reports a box that starts there too — and the page then has no reason
    to nudge the figure, which would take the plot off the 4px grid.
    """
    return Text(x=round(x, 1), y=round(top + size, 1), content=content, size=size,
                fill=fill, family=FONT_MONO, anchor=anchor, kind="label")


def _series_paint(tokens: Tokens, index: int) -> str:
    """The series' paint: the accent first, then the page's quieter inks."""
    return getattr(tokens, _SERIES_PAINT[index % len(_SERIES_PAINT)])


def _wants_legend(spec: Spec, series_count: int) -> bool:
    """The legend is on when asked for, or when 2+ series need telling apart."""
    if spec.legend is not None:
        return spec.legend
    return series_count >= 2


def _legend_items(chart, tokens: Tokens) -> list:
    return [(series.label.upper(), _series_paint(tokens, i),
             _series_paint(tokens, i), None)
            for i, series in enumerate(chart.series)]


def _polyline_d(points: list) -> str:
    d = f"M {geo.r2(points[0][0])},{geo.r2(points[0][1])}"
    return d + "".join(f" L {geo.r2(x)},{geo.r2(y)}" for x, y in points[1:])


def _rule(points: list, stroke: str, width: float, name: str, tokens: Tokens) -> Path:
    """One straight rule — axis, gridline or tick mark; hand-drawn on the sketchy skin."""
    if rough(tokens):
        d = "".join(sketchy.wobbly_line(a[0], a[1], b[0], b[1], sketchy._seed(name), i)
                    for i, (a, b) in enumerate(zip(points, points[1:])))
    else:
        d = _polyline_d(points)
    return Path(d=d, stroke=stroke, stroke_width=width, points=list(points))


def _series_line(points: list, paint: str, name: str, tokens: Tokens) -> Path:
    """A line series: the polyline through the band centres, sharp-cornered.

    No rounded corners — that is the connector grammar's idiom for a route, and a
    data line that bends like a router cable misreads as one.
    """
    if rough(tokens):
        d = ""
        for i, (a, b) in enumerate(zip(points, points[1:])):
            d += sketchy.wobbly_line(a[0], a[1], b[0], b[1], sketchy._seed(name), i,
                                     amp=sketchy.JITTER * 0.5)
    else:
        d = _polyline_d(points)
    return Path(d=d, stroke=paint, stroke_width=2.0, points=list(points))

# Chart specs (`nanoframes chart`)

`nanoframes chart <spec.json>` plots a **data table** — a bar or line chart,
a quarterly series, a trend with a signed month — into an ordinary **`.nf.svg`
composition**. The spec carries the numbers, their category labels and the axis
titles, and nothing else: no coordinates, no pixel sizes, not even the bounds of
the value axis. The compiler picks those, because it is the part that knows how
to round them to numbers a reader can divide.

```bash
nanoframes chart table.json -o table.nf.svg     # build a composition
nanoframes chart table.json --check             # build, then lint the result
nanoframes render table.nf.svg --t 0 -o shot.png  # a still
nanoframes video  table.nf.svg -o out.mp4         # with "reveal": true
```

## One of the grammars

`nanoframes diagram`, `nanoframes tree` and `nanoframes chart` are three front
doors onto one contract. A **grammar** is its own spec plus its own
data→geometry algorithm, and every grammar emits the same scene — so tokens, the
4px grid, measured text, the legend, the reveal timeline, the canvas rules and
every ThorVG workaround ([docs/diagram.md](diagram.md#thorvg-gaps)) are shared,
not re-implemented.

| grammar | command | the input it compiles |
|---|---|---|
| `flow` | `nanoframes diagram` | nodes with explicit `x`/`y`, plus edges |
| `loop` | `nanoframes diagram` | stations on a computed ring, plus a hub |
| `tree` | [`nanoframes tree`](tree.md) | a nested node list |
| `chart` | `nanoframes chart` | a data table (this page) |

Reach for `chart` when the *numbers are the argument*. It is deliberately not a
plotting library: one primitive per chart type, no stacking, no logarithmic or
secondary axis, no per-point styling. A chart that needs those is a `flow` spec
you place by hand, or two charts.

## The spec

```json
{
  "diagram": "chart",
  "preset": "doc-wide",
  "title": "Frames shipped",
  "subtitle": "Four quarters, one series",
  "chart": {
    "type": "bar",
    "categories": ["Q1", "Q2", "Q3", "Q4"],
    "series": [
      {"label": "Shipped", "values": [12, 18, 9, 21]}
    ],
    "x_label": "Quarter",
    "y_label": "Frames",
    "unit": "k",
    "grid": true
  }
}
```

The header keys are the ones in [docs/diagram.md](diagram.md#the-spec)
(`diagram`, `skin`, `preset`, `canvas`, `title`, `subtitle`, `legend`, `margin`,
`fps`, `dpi`, `duration`, `reveal`). `chart` holds the table:

| key | values | notes |
|---|---|---|
| `type` | `bar` (default), `line` | one primitive per type: bars grow from the zero baseline, a line is a polyline with a marker per value |
| `categories` | list of labels, left to right | the x axis is a **band** scale: every category gets an equal band. Omitted, the categories are numbered `1..n` |
| `series` | list of `{"label", "values"}` | one number per category, exactly — a length mismatch is a spec error, not a trim |
| `x_label` / `y_label` | strings | axis titles; the x title sits under the category labels, the y title above the plot |
| `unit` | string | folded into the y title (`Frames (k)`) rather than repeated on every tick |
| `grid` | `true` (default) | horizontal rules at the ticks; the zero rule is drawn either way |

`x`, `y`, `w`, `h` and every pixel size are **refused by omission** — there is
nowhere in the shape to write one, and the axis bounds are not the author's to
declare: the compiler owns the nice-number rounding that makes them readable, so
an authored bound could only be silently overridden. `canvas` and `preset` are a
*minimum*, as in every other grammar: the plot fills the page it is given and
grows the page rather than clipping.

## What the compiler guarantees

- **A scale, not a stretch.** The value axis contains zero (a bar needs a zero
  baseline, and a line axis that starts at the smallest observed value
  exaggerates every wiggle), and its bounds land on a **1/2/5 × 10^k** step —
  Heckbert's *Nice Numbers for Graph Labels* (Graphics Gems, 1990). Data topping
  out at 37 gets an axis to 40; data from −5 to 37 gets −10 … 40.
- **Bar height is exactly proportional to value**, and a bar of zero draws no
  bar. All-zero and single-value series widen the domain instead of dividing by
  a zero span.
- **Grid-aligned rules.** The plot's height is the tick count times a
  grid-multiple step, and a band is an even number of grid cells (so its centre
  — where the bar and its tick mark go — is a grid point). Every axis line, tick
  mark and bar *corner* lands on the shared 4px grid. Bar *heights* deliberately
  do not: a height snapped to the grid is no longer proportional to its value.
- **Measured text.** Tick labels, category labels and value labels are measured
  through the same ThorVG path the render uses, so the y-axis gutter is exactly
  the widest label plus its air.
- **The page is shared.** Title band, legend (2+ series), reveal clock, canvas
  floor and margin handling all come from `nanoframes.diagram.canvas`.
- **Determinism.** Same spec, same bytes. Every coordinate is rounded to 2
  decimals; text measurement is cached per distinct string.

## Reading the plot

The value axis' title carries the unit, the tick labels carry the numbers, and
the category labels sit under their band centres. A single-series bar chart also
labels each bar with its value — one series *is* the reading, and the label saves
a trip to the axis. With several series that would be clutter, so the labels are
dropped and the y axis carries the reading instead.

Series are painted in a fixed order from the page's tokens: the accent first (it
is the claim), then link, muted, ink and soft. A grouped bar chart splits each
band between its series; nothing is stacked.

## Library API

```python
from nanoframes.diagram import GRAMMARS, build_scene, parse_spec, render
from nanoframes.diagram.chart import nice_step, nice_ticks, format_tick

scene = build_scene(parse_spec(spec_dict))   # spec -> scene IR
scene.warnings                               # budget findings

nice_ticks(0, 37)        # ([0, 10, 20, 30, 40], (0.0, 40.0))
nice_step(3)             # 5.0
format_tick(0.6)         # "0.6"

GRAMMARS                                     # {"flow", "loop", "tree", "chart"} -> compiler
```

The scene IR is the testable surface here too: `tests/test_chart.py` asserts the
tick ladder, the grid, the zero baseline and the proportionality of every bar
against the IR rather than against SVG text.

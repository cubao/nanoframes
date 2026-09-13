# diagram-chart — layout grammar for `"diagram": "chart"`

Read with `diagram-design.md`. Applies to: bar/line chart, trend, quarter-on-
quarter comparison, a signed series, any figure whose argument **is the
numbers** and where the axis bounds are the point.

Contract and spec keys: [docs/chart.md](../../docs/chart.md).
Motion conventions for data on screen: `recipe-data-stats.md`.

## The division of labor

**You** choose the table: the categories in reading order, one value per
category, the series labels, the axis titles and the unit. **The builder** owns
every coordinate: the value scale, the axis bounds and their 1/2/5 × 10^k
ticks, the band pitch, the bars or the polyline, the grid, the legend, the
canvas.

There is nowhere to write an `x`, a `y`, a width or even an axis maximum. That
is stricter than it sounds and it is deliberate: a *nice* axis is a rounding
decision, so an authored bound could only be silently overridden — and an axis
the author believes they set is worse than no axis at all.

```bash
nanoframes chart table.json -o table.nf.svg --check
nanoframes render table.nf.svg --t 0 -o shot.png
```

## When a chart grammar, and when something else

| the input | grammar |
|---|---|
| numbers per category, and the axis is the argument | `nanoframes chart` |
| a few big numbers, or one hero value, as a composition | hand-authored `.nf.svg` (~`recipe-data-stats.md`) |
| boxes and relations, where arrangement is the argument | `nanoframes diagram` (`flow`) |

Do **not** reach for this grammar to draw a dashboard: it is one plot, one value
axis, one or two series. Stat cards, progress bars and hero numbers are motion
compositions — write them as `.nf.svg`.

## Authoring recipe

1. **One claim per chart.** The title states the insight ("Frames shipped"), not
   the axis. If two claims need telling, they are two charts.
2. **Bar when the categories are discrete and you compare them; line when the x
   order is a continuum.** A line between four unrelated categories invents a
   trend; a bar per month hides one.
3. **≤ 12 categories, ≤ 4 series** — warned above. Past that it reads as a
   table: split the window, or show the latest period.
4. **Zero is always in the axis.** Bars need a zero baseline to be honest, and
   lines are not exempt here; the compiler will not truncate for you.
5. **Put the unit in `unit`**, not in every tick label — it folds into the y
   title (`Frames (k)`).
6. **Category order is the message.** Nothing sorts for you (no "by value"), so
   order by time, by size, or by the story.
7. **One series gets value labels; several do not.** The single-series label is
   the reading; with several series the y axis carries it and labels are clutter.

## What the builder decides for you

- The tick ladder (1/2/5 × 10^k), the axis bounds, the grid, the zero rule.
- Bar height exactly proportional to value; a zero value draws no bar.
- Bands of equal width, each an even number of 4px cells so the bar centre and
  its tick mark are grid points; the plot fills the page it is given.
- The legend, from the series labels, when there are 2+ of them.
- `"reveal": true` fades the series in order; the axes and grid are furniture
  and are simply there.

## Anti-patterns (any of these is an automatic redo)

| anti-pattern | why it fails |
|---|---|
| `"type": "line"` across four unrelated categories | it invents a trend the data does not have |
| two value axes (units and values) | one axis per chart; make it two charts |
| 20 categories in one plot | it is a table; split the window |
| a stacked bar asked for as two series | not supported, on purpose — the reading is a part-to-whole and a second axis |
| a chart used to draw stat cards or a dashboard | that is a motion composition, not a plot |
| an "axis maximum" written into the spec | there is no such key; nice-number rounding owns it |

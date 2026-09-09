# Recipe: data, stats & charts

Adapted from text-to-lottie `references/recipe-data-stats.md` (MIT). Applies
to: KPI numbers, stat cards, bar/line charts, comparisons, progress,
dashboards, "before/after" figures. **Serious data = calm.** The motion's
job is to direct attention to the insight, not to entertain.

## Defaults

- One data **archetype** before authoring: single hero number, KPI grid
  (2–4 cards), bar comparison, line/trend, progress to goal, triad
  (three equal stats), label + value pairs. The archetype decides layout.
- The headline states the **insight**, not the axis ("orders up 34 %" — the
  number is the focal; decorations serve it).
- One semantic accent color for the data point that matters; everything else
  neutral.
- **Direct labels** next to their data — no legend-hunting. Data glyphs are
  mono (`Sarasa Mono SC`) so digits never jitter.
- Stat groups: borderless in negative space, or even cards with **one**
  surface tone and at most a single hairline of one color between equal
  columns. No outer framing card (see `design-taste.md`).
- When real data is missing, use clearly fake-but-plausible values and say
  so; placeholder third-party logos/headshots stay generic.

## Presets (behavior briefs)

1. **hero-number** — one giant value is the whole frame: it scales in
   (`0.9 → 1.0`, settle-back allowed), then label + unit + source line enter
   beneath after it resolves.
2. **kpi-grid** — 2–4 stat cards; each card's number reveals as the card
   enters (stagger ≈ 0.15 s), bars/indicators fill, labels last.
3. **bar-compare** — bars grow from the baseline: each bar is a rect scaled
   `[1, 0] → [1, 1]` with its bottom edge fixed (translate to anchor);
   stagger ≈ 0.1 s; the winning bar carries the accent color and lands
   slightly last.
4. **trend-line** — a `<path>` line reveals left→right via a covering chip
   that translates away, or a per-segment cascade (see loaders
   `stroke-trace`); points pop in mono labels as the line passes them.
5. **progress-goal** — bar fills (scale-x, anchored), percent counts up in
   mono; a marker ticks at the goal line.
6. **compare-before-after** — two panels; each number enters with its label;
   a hairline divider; the delta (accent) pops last with a settle-back.

## Timing (seconds)

| piece | duration |
|---|---|
| compact stat card | 1 – 2 s |
| multi-card / chart | 2 – 3.5 s (cards/segments staggered) |
| count-up value | ~0.8 – 1.2 s, near-linear digits then `ease-out` settle |
| label/unit after number | +0.2 – 0.4 s |

**No bounce for serious data.** Calm `ease-out`; bars/lines `ease-out` or
near-`linear` traces.

## Construction notes (nanoframes mechanics)

- **Count-ups have no text interpolation.** Simulate: successive `<text>`
  elements (mono!) each holding one value, windows `data-start` ~0.1 s apart,
  fading 0→1 fast so only one is visible at a time — or keep it honest: show
  the final number and animate the *geometry* (bar fill) toward it, which
  reads as the count-up without fake digits.
- Bars anchored at the baseline: place the rect's top at `baseline - h` and
  scale from `[1, 0]` with `transform-origin` unavailable — compensate with
  translate: scale `[1, s]` + translate `[0, h(1-s)]` on the same keyframes
  (values in the keyframe JSON, both animated), or pre-bake heights as
  separate rects per step when only a few steps exist.
- Bars with rounded corners: rounding distorts when scaling a rect — keep
  the radius small, or reveal via `data-start` presence instead of scale.
- Axis/hairlines: thin rects or lines, fade in once (before data), then
  stay.
- Number + label rows share a baseline → cap-center the mixed-size runs
  (`design-taste.md`); use mono for the number and a smaller mono label for
  the same look.

## Failure modes & acceptance

- The baseline trap: label and value sharing a baseline sinks the label.
- Bouncing/snappy motion on serious figures.
- Digits jittering (proportional face) — mono only.
- Numbers entering before their container/card → meaningless motion.
- Eyeballed vertical rhythm instead of one consistent spacing step.
- Check frames: first bar/number, midpoint stagger, resolve (number lands +
  label), final hold — the last frame must read as a clean chart.

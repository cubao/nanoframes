---
name: nanoframes
description: >-
  Produce a video or animated visual from an SVG composition, rendered offline
  and deterministically by ThorVG — no browser. Use when an agent wants to make
  a motion graphic, title card, data-viz still, explainer, or clip and iterate
  fast locally with `check`, `preview`, and `render`. Guides the production loop:
  plan -> write a `.nf.svg` -> `check` -> `preview` a frame -> `render` frames/video.
---

# nanoframes

nanoframes is an offline, browserless alternative to HTML-to-video frameworks.
You write one valid SVG file plus a small JSON animation timeline, and every
frame is rasterized deterministically by ThorVG (`thorvg-python`) to PNG, then
muxed to MP4 with ffmpeg. Because there is no browser, iteration is ~6ms/frame.

## Production loop

For any "make me a video / animated card / motion graphic" request:

1. **Plan** — canvas size, duration, fps, beats. Decide what moves (translate /
   scale / rotate), fades, and what stays static.
2. **Write** a `.nf.svg` composition (see contract below). Start from
   `nanoframes init <name>` (the template ships with the package); repo
   checkouts additionally carry `examples/`.
3. **Check** — `nanoframes check <comp>.nf.svg` lints the contract (exit 1 on
   errors). Fix until ok.
4. **Preview** a frame — `nanoframes preview <comp>.nf.svg --t 2.0` renders and
   opens that second. If it comes out empty or an element is missing, run
   `nanoframes debug <comp>.nf.svg --t 2.0` instead of guessing: it names the
   element whose geometry misses the canvas.
5. **Render** — single frame, full batch, or video:
   `nanoframes render <comp>.nf.svg --t 2.0 -o shot.png`
   `nanoframes render <comp>.nf.svg -o out/`
   `nanoframes video <comp>.nf.svg -o out.mp4`

**Draft before you commit.** For any composition longer than a few seconds,
export once with `--scale 0.5` (or `0.25`) and watch the whole clip before
paying for the full-quality render: the draft makes the canvas and every
embedded `<image>` smaller, which is where the time actually goes. Draft
output is for judging timing and composition, not for delivery — re-export at
the default scale for the final file.

Iterate: tweak the SVG/edit keyframes -> preview again -> render. Visual
regressions are caught by `tests/snapshots/` (regenerate after intentional
changes with `python3 -m nanoframes.scripts.snapshots`).

## Craft references (read only what the task routes to)

This file is the thin control plane. Design/motion craft lives in
`references/` next to this file (`skills/nanoframes/references/`, shipped in
the wheel with the rest of the skill). Read `references/README.md` (translation
conventions + mechanical rules) plus **only** the routed references below — do
not open the whole library.

| User intent | References to read when present |
| --- | --- |
| Any new/edit/verify composition | `references/README.md` |
| Title card, quote, kinetic typography, CJK headline, words moving | `references/recipe-typography.md` + `design-taste.md` + `motion-taste.md` |
| Logo, wordmark, brand lockup animation | `references/recipe-logo.md` + `design-taste.md` + `motion-taste.md` |
| Lower third, name tag, caption bar, overlay card | `references/recipe-lower-thirds.md` + `design-taste.md` + `motion-taste.md` |
| Loader, spinner, icon animation, success/error/warning state | `references/recipe-loaders-icons.md` + `motion-taste.md` |
| Data, stats, KPI, chart, metrics, count-up, dashboard figure | `references/recipe-data-stats.md` + `design-taste.md` + `motion-taste.md` |
| Long-form, explainer, multi-idea, feature list, timeline, before/after, recap | `references/chapter-transitions.md` + `motion-taste.md` |
| Seamless loop requested | `motion-taste.md` (loops) + the routed recipe |
| "premium", "clean", "minimal", "modern", "sleek", "polished" | `design-taste.md` (restraint defaults) + the routed recipe |

Mixed prompts: choose one primary recipe from the main deliverable, then add
secondary references (e.g. a logo stat card uses `recipe-logo.md` +
`recipe-data-stats.md`).

## Design defaults (always apply)

These few defaults are non-negotiable for every composition; see
`design-taste.md` for the full reasoning.

- **Premium means subtract, not add.** Carry premium with scale, weight,
  brightness, spacing, and timing — never with cards, borders, dividers,
  shadows, glow, or stacked tints.
- **Chrome/container budget is 0 by default.** Separate with whitespace and
  alignment first, a single hairline second, a filled card last and only when
  it does a job.
- **One surface tone, one accent system, one type idea.** Never stack two
  near-black/near-white tints; one loud color per frame; serif = editorial,
  grotesque = product, mono (`Sarasa Mono SC`) = technical/CJK.
- **The final frame is a poster.** It must work as a clean still with the
  message intact — settle and hold before the clip ends.
- **Design quality is a completion blocker.** A render that is generic,
  crowded, or chrome-heavy is not done.

## Composition contract (a `.nf.svg`)

**Canvas** (root `<svg>`): `data-width`, `data-height`, `data-fps` (default 30),
`data-duration` (seconds), optional `data-composition-id`.

**Element presence**: `data-start` (enter time, sec), `data-duration` (how long
visible, default = comp duration), `data-fade` (fade seconds at clip start —
**mirrored as a fade-out at the clip end**).

**Animation** `<script type="application/nanoframes+json">` (wrap in `CDATA`):
one `animations` array. Each entry has a CSS `target` (`#id`, `.class`, or tag)
and ordered `keyframes`. A keyframe is `{ "t": sec, "<prop>": value, "ease":
"linear|ease-in|ease-out|ease-in-out" }`. Numeric props interpolate (with
easing), hex colors interpolate RGB.

Supported animated props:
- `opacity` (0..1)
- `transform`: `{"translate":[x,y], "scale":[sx,sy], "rotate":deg}` — for a
  pivot on the element itself use `"rotate": {"deg": deg, "center": "auto"}`
- `fill` / `stroke` (`#RRGGBB`)

## Rules to keep renders valid & deterministic

- Canvas MUST have positive `data-width`/`data-height`; `data-duration` > 0.
- Every animation `target` must actually match an element (lint enforces this).
- Keep keyframes within `[0, data-duration]` (lint warns otherwise). The
  evaluator sorts by `t` itself, so file order does not matter.
- Could any clip exceed the composition duration? Keep `data-start + data-duration`
  within the total — otherwise `check` warns.
- `transform` order is baked as translate -> rotate -> scale.
- **`rotate` pivots on the canvas origin `(0,0)` unless told otherwise** —
  `rotate(deg)` alone throws an element authored at (480,300) to about
  (-300,-480). Write `{"deg": deg, "center": "auto"}` to spin an element where
  it is, or `[deg, cx, cy]` for an explicit point; the same form must be used
  in every keyframe of that animation. `check` warns when a missing pivot would
  swing an element away.
- **An animated `transform` layers inside the element's own `transform`**, so
  `<g id="crank" transform="translate(480 360)">` keeps its position while it
  spins. Geometry that leaves the canvas is clipped at the edge (the frame
  pins its viewport to the canvas) — but geometry that never lands on the
  canvas draws nothing, which `check` warns about.
- **Seamless loop:** the last rendered frame is `duration - 1/fps`, not
  `duration`. Finish the motion by then, hold it, and verify with
  `nanoframes debug <comp> --loop`. See [composition.md](../../docs/composition.md).
- Relative `<image href>` paths resolve against the composition's directory.
- **Text just works for CJK**: a bundled monospace face (Sarasa Mono SC) is the
  default fallback, so Chinese renders solidly and monospaced without any font
  setup. Use `font-family="Sarasa Mono SC"` for deterministic-width Chinese;
  `nanoframes fonts list|add|verify` manages extra faces. Auto layout
  (`data-bg` chips, `data-wrap`, `data-curve-d`, `data-fit`) and the
  `text_handler` escape hatch for exotic text are documented in
  [text-capabilities.md](../../docs/text-capabilities.md).
- ThorVG rasterizes the **SVG Tiny 1.2** subset — avoid CSS layout, filters,
  or SVG2-only geometry attributes. Prefer primitives + gradients + transforms.

## Minimal working example

```svg
<svg xmlns="http://www.w3.org/2000/svg"
     data-width="960" data-height="540" data-fps="30" data-duration="6.0"
     data-composition-id="intro">
  <rect id="bg" width="960" height="540" fill="#0a1128"/>
  <text id="title" x="60" y="120" font-family="Arial" font-size="72"
        fill="#f4f7ff" data-fade="0.4" data-duration="6.0">nanoframes</text>
  <script type="application/nanoframes+json"><![CDATA[{
    "animations": [{
      "target": "#title",
      "keyframes": [
        {"t": 0.0, "opacity": 0.0, "transform": {"translate": [0, 30]}},
        {"t": 0.7, "opacity": 1.0, "transform": {"translate": [0, 0]}, "ease": "ease-out"}
      ]
    }]
  }]]></script>
</svg>
```

## Commands

```bash
nanoframes init <name>                  # scaffold <name>.nf.svg
nanoframes check <comp>.nf.svg          # lint; exit 1 on errors
nanoframes debug <comp>.nf.svg --t 2    # where each element's geometry lands per frame
nanoframes debug <comp>.nf.svg --loop   # + first/last frame diff (loop seam)
nanoframes preview <comp>.nf.svg --t 2  # render one frame + open
nanoframes render <comp>.nf.svg --t 2 -o shot.png
nanoframes render <comp>.nf.svg -o out/        # full batch of frames
nanoframes video  <comp>.nf.svg -o out.mp4     # ffmpeg MP4
nanoframes video  <comp>.nf.svg -o out.mp4 --scale 0.5       # draft: half-size, ~4x faster
nanoframes video  <comp>.nf.svg -o out.mp4 --audio bgm.mp3   # + audio mux
nanoframes measure <comp>.nf.svg        # renderer-exact glyph widths
nanoframes fonts list|add|verify|install          # CJK font toolbox
nanoframes lottie <scene.json> -o out.mp4         # ThorVG Lottie loader -> MP4
nanoframes walkthrough                  # regenerate the one-take tour (build/)
```

**When a frame comes out empty or an element is missing, run
`nanoframes debug`** — it lists each element's post-transform box, whether it
is on-canvas, and (with the clip scan) whether it is ever visible. A frame that
draws nothing renders as a valid, fully transparent PNG, so this is the command
that turns a blank output into a named culprit.

`nanoframes` with no arguments prints where the docs and this skill live
(`nanoframes --help` prints the same pointers — also available via `python -m nanoframes`). Full contract:
[composition.md](../../docs/composition.md). Engine/toolchain:
[architecture.md](../../docs/architecture.md). Text story & caveats:
[text-capabilities.md](../../docs/text-capabilities.md).

All of `docs/` and `skills/` ship inside the installed package too
(`site-packages/nanoframes/docs`, `site-packages/nanoframes/skills`), so an
installed agent gets the same references.

## Lottie scenes (import-render, not authoring)

Lottie/Bodymovin JSON is an accepted **input** format, never an authoring
surface: `nanoframes lottie <scene.json> -o out.mp4` renders a lottie.json
scene (e.g. a text-to-lottie deliverable) with ThorVG's native Lottie loader
and muxes a deterministic MP4 — no browser, no Skottie. Canvas, fps and
length come from the scene itself; sibling images/fonts resolve next to the
file; the loader's coverage is ThorVG's Lottie implementation. Contract:
[docs/lottie.md](../../../docs/lottie.md) (this skill's
`references/README.md` translation conventions do **not** apply — a Lottie
scene carries its own keyframes). When the task is authoring new motion,
write `.nf.svg` instead and let the craft references route you.
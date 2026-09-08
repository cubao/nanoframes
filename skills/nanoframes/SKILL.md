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
2. **Write** a `.nf.svg` composition (see contract below). Reuse `examples/`
   and `nanoframes init <name>` for a template.
3. **Check** — `nanoframes check <comp>.nf.svg` lints the contract (exit 1 on
   errors). Fix until ok.
4. **Preview** a frame — `nanoframes preview <comp>.nf.svg --t 2.0` renders and
   opens that second.
5. **Render** — single frame, full batch, or video:
   `nanoframes render <comp>.nf.svg --t 2.0 -o shot.png`
   `nanoframes render <comp>.nf.svg -o out/`
   `nanoframes video <comp>.nf.svg -o out.mp4`

Iterate: tweak the SVG/edit keyframes -> preview again -> render. Visual
regressions are caught by `tests/snapshots/` (regenerate after intentional
changes with `python3 -m nanoframes.scripts.snapshots`).

## Composition contract (a `.nf.svg`)

**Canvas** (root `<svg>`): `data-width`, `data-height`, `data-fps` (default 30),
`data-duration` (seconds), optional `data-composition-id`.

**Element presence**: `data-start` (enter time, sec), `data-duration` (how long
visible, default = comp duration), `data-fade` (fade-in sec).

**Animation** `<script type="application/nanoframes+json">` (wrap in `CDATA`):
one `animations` array. Each entry has a CSS `target` (`#id`, `.class`, or tag)
and ordered `keyframes`. A keyframe is `{ "t": sec, "<prop>": value, "ease":
"linear|ease-in|ease-out|ease-in-out" }`. Numeric props interpolate (with
easing), hex colors interpolate RGB.

Supported animated props:
- `opacity` (0..1)
- `transform`: `{"translate":[x,y], "scale":[sx,sy], "rotate":deg}`
- `fill` / `stroke` (`#RRGGBB`)

## Rules to keep renders valid & deterministic

- Canvas MUST have positive `data-width`/`data-height`; `data-duration` > 0.
- Every animation `target` must actually match an element (lint enforces this).
- Keep keyframes sorted by `t`, within `[0, data-duration]`.
- Could any clip exceed the composition duration? Keep `data-start + data-duration`
  within the total — otherwise `check` warns.
- `transform` order is baked as translate -> rotate -> scale.
- Relative `<image href>` paths resolve against the composition's directory.
  Text renders with a system font loaded automatically.
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
nanoframes preview <comp>.nf.svg --t 2  # render one frame + open
nanoframes render <comp>.nf.svg --t 2 -o shot.png
nanoframes render <comp>.nf.svg -o out/        # full batch of frames
nanoframes video  <comp>.nf.svg -o out.mp4     # ffmpeg MP4
```

Full contract: `docs/composition.md`. Engine/toolchain: `docs/architecture.md`.
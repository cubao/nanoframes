# nanoframes Architecture

## North star

**Write a frame as SVG. Render frames, and a video, without a browser.** Built so an AI coding
agent can iterate fast and deterministically on every local change: `check` → `preview` →
`render` in milliseconds, no browser, no network.

## Why SVG + ThorVG (instead of HTML + Chromium)

Hyperframes uses HTML/CSS + a browser engine + GSAP, and captures frames through Chromium to a
seekable MP4. That is powerful but heavy and non-deterministic in some dimensions:

- The browser is a huge, opaque surface; agents can't inspect it locally without it.
- HTML/CSS layout is complex; matching pixel output requires capture round-trips.

nanoframes chooses the minimal deterministic subset that still covers typical motion-graphic
output:

- **Authoring surface = SVG**, which is (a) a first-class native output of language models, (b)
  declarative, (c) directly rasterizable.
- **Rendering engine = ThorVG** (`thorvg-python`), an embedded SVG rasterizer (conforms to
  *SVG Tiny 1.2* — see `../thorvg.wiki/SVG-Support.md`). No browser, no DOM, pure software raster
  → Pillow → PNG/MP4. Deterministic and trivially iterable.
- The `frames-pack` toolchain already demonstrated offline ThorVG→PNG rendering; we reuse that
  pattern (thorvg-python + Pillow), and we reuse hyperframes' *timing/intent* ideas (clip
  in/out, tracks, seek) but <b>flatten animation to a declarative timeline</b> instead of GSAP.

## Pipeline

```
composition.nf.svg  (SVG scene + embedded <script> JSON animation timeline)
        │  parse (stdlib xml) → nanoframes.Composition
        v
 seek(t): evaluate animation timeline → per-frame property values
        │
        v
 bake(t): merge visibility + animated props into a frame-specific SVG
        │
        v
 thorvg render → Pillow PNG   (single frame, or batch)
        │
        v
 ffmpeg → deterministic MP4   (P1)
```

Every stage is pure and deterministic given `(composition, t, fps)`. No web surface anywhere.

## Composition model

A composition is one `.nf.svg` file (valid SVG) carrying:

- root `<svg>` canvas metadata: `data-width`, `data-height`, `data-fps`, `data-duration`
  (`data-composition-id` optional).
- per-element presence: `data-start` + `data-duration` (absolute seconds, clip in/out) and
  optional `data-fade` (fade-in/out seconds). Elements outside their window are not rasterized.
- an embedded `<script type="application/nanoframes+json">` holding the **animation timeline**:
  ordered animations, each targeting elements by CSS selector (`#id`, `.class`) with keyframe
  lists over time.

Detailed contract: `docs/composition.md`.

## Animation timeline (declarative, seekable)

Hyperframes uses GSAP timelines loaded into the browser. We replace JS with a deterministic
keyframe JSON timeline evaluated by `seek(t)`:

- supported animated properties: `opacity`, `transform` (`translate`, `scale`, `rotate`),
  `fill`, `stroke` (interpolated color).
- keyframes are `{ "t": <sec>, <props>: value }`; between keyframes we interpolate linearly,
  optionally eased (`linear`, `ease-in`, `ease-out`, `ease-in-out`).
- clip + fade is folded into effective opacity so visibility, fade and animation compose into a
  single `opacity` / `transform` baked value per frame.

This is deliberately *small*. Full GSAP/CSS expressiveness is out of scope; the payoff is fast,
deterministic, inspectable motion.

## Rendering (thorvg-python)

- `bake(t)` writes a temp standalone SVG (strips the `<script>`, applies the computed attrs).
- a renderer creates `thorvg_python.Engine` + `SwCanvas`, sets the target size, loads the SVG as
  a `Picture`, `add → update → draw → sync`, and reads a Pillow image via `get_pillow()`.
- Energy is per-frame and isolated, so batch rendering stays deterministic and trivially
  parallelizable later.

## Scope decisions (what we drop from hyperframes)

| Hyperframes scope              | nanoframes |
|--------------------------------|------------|
| HTML/CSS + browser capture     | SVG + ThorVG software raster |
| GSAP / Lottie / Three.js / anime | declarative keyframe timeline (v1) |
| inline `<video>` playback      | static `<image>` only (v1); no video-in-scene |
| full audio mixing (buses, ducking) | optional FFmpeg audio mux passthrough (deferred P2) |
| hosted / Lambda / GCP rendering | local offline render only |
| Figma import, Remotion port     | out of scope |
| 20 authoring workflows          | a few core example templates |
| frame.md / design.md system     | composition doc + lint (v1) |
| binary TreePack compressed pack | deferred optional binary cache (P2) |

**Kept:** deterministic seekable frames, clip timing, `check`/`preview`/`render` agent loop,
MP4 export, and an agent-facing skill.

## Non-goals

- No browser, no network, no live media.
- No JS runtime / no GSAP semantics.
- No production audio mastering; no cloud rendering.

## Milestones

- **v1 (done, 2026-09)** composition model + parser, timeline evaluator, ThorVG
  frame renderer, CLI (`init`/`check`/`render`/`preview`/`video`/`measure`/
  `fonts`/`walkthrough`), MP4 export + audio mux, fast re-render cache,
  renderer-exact text story (chips/wrap/curve/fit), bundled mono CJK font,
  `text_handler` escape hatch, example compositions + visual snapshot suite,
  agent skill (`skills/nanoframes/SKILL.md`).
- **Deferred** optional binary tree-pack cache; CLI bridge for `text_handler`
  (it is a library-API feature by design); in-scene video.

`docs/` and `skills/` ship inside the pip wheel as `nanoframes/docs` and
`nanoframes/skills`; `nanoframes` (no args) prints their installed locations.
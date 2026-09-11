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
  The baked root carries `viewBox="0 0 W H"` (unless the author declared one): ThorVG otherwise
  infers a picture's size from its content bounding box, so a single element outside the canvas
  rescales — or blanks — the whole frame. Pinning the viewport makes off-canvas geometry exactly
  what it should be: clipped.
- a renderer creates `thorvg_python.Engine` + `SwCanvas`, sets the target size, loads the SVG as
  a `Picture`, `add → update → draw → sync`, and reads a Pillow image via `get_pillow()`.
- Energy is per-frame and isolated, so batch rendering stays deterministic and trivially
  parallelizable later.

### Geometry: bounds, lint, debug

A frame's visual failures are geometric before they are visual, so `nanoframes.bounds` answers
them with arithmetic instead of rasterization: shape geometry → affine transform chain →
axis-aligned box. `lint` samples the timeline and warns when an element never lands on the canvas
or a pivotless `rotate` would swing it away; `nanoframes debug` (`nanoframes.diagnose`) prints
each element's box, how many frames it is actually visible in, and the pixel diff across a loop's
seam. Text boxes come from the same renderer-exact `Measurer` the layout passes use, so a
reported box is the box that gets drawn.

### Draft rendering (`--scale`)

Per-frame cost is dominated by what a frame *contains*, not by how large it is drawn: ThorVG
resamples every `<image>` source into its destination rect on every frame, so a 1560x991 board
costs the same on a 1600x1200 canvas as on a 400x300 one. Shrinking only the canvas therefore
buys ~10%; the resolution knob has to reach the assets to be worth having.

`nanoframes.scale` does both. `draft_size` sizes the canvas (rounded to even pixels, since
`yuv420p` rejects odd dimensions) and `prescale_images` rewrites each distinct `<image>` source
once, before the frame loop, to a disk-cached copy at that scale. ThorVG then resamples from a
small source, and per-frame cost scales the way you would expect. The authored path is recorded
in `data-src`, so a later pass at a different scale resizes the original rather than a copy.

Draft output is for judging timing and composition — it is not a pixel-exact downscale of the
full-quality frame, so deliver at the default scale.

## Scope decisions (what we drop from hyperframes)

| Hyperframes scope              | nanoframes |
|--------------------------------|------------|
| HTML/CSS + browser capture     | SVG + ThorVG software raster |
| GSAP / Lottie / Three.js / anime | declarative keyframe timeline (v1) — *except* Lottie **import-render**: ThorVG's native Lottie loader turns a lottie.json scene into a deterministic MP4 (`nanoframes lottie`, 0.1.1). Lottie is an accepted *input format*, not an authoring surface |
| inline `<video>` playback      | static `<image>` only (v1); no video-in-scene |
| full audio mixing (buses, ducking) | optional FFmpeg audio mux passthrough (deferred P2) |
| hosted / Lambda / GCP rendering | local offline render only |
| Figma import, Remotion port     | out of scope |
| 20 authoring workflows          | a few core example templates |
| frame.md / design.md system     | composition doc + lint (v1); craft references in the skill |
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
- **0.1.0 (2026-09)** — the first published release: v1's feature set, packaged.
  `docs/` and `skills/` are force-included into the wheel and a bare
  `nanoframes` prints where they landed, so an installed agent still finds the
  composition contract. Publishing is sdist-only through `make upload`, with
  the build backend pinned to `hatchling==1.27.0` — the last hatchling that
  still served the then-supported Python floor as a build backend while
  emitting Metadata-Version 2.4, which the twine in use accepts.
- **0.1.1 (2026-09)** — the skill's **craft reference library**, absorbed from
  text-to-lottie (MIT): `design-taste`, `motion-taste`, five recipes
  (typography / logo / lower-thirds / loaders-icons / data-stats),
  `chapter-transitions` and a translation-conventions README, all re-expressed
  for the `.nf.svg` declarative timeline (frames → seconds, no off-canvas
  motion, trim-path idioms → opacity/transform). The dependency floor was made
  honest in the same release: `thorvg-python>=1.1.3` and `requires-python
  >=3.9` — thorvg-python subscripts `ctypes.Array[...]`, a 3.9+ feature, so the
  previous `>=3.8` floor could never actually have imported. A PEP 701 nested
  f-string in the `measure` header, which killed every invocation on Python
  3.8–3.11, went with it.
- **0.1.2 (2026-09)** — `nanoframes lottie`: Lottie JSON import-render via
  ThorVG's native loader (scene `w`/`h`/`fr`/`ip`/`op`, scene-relative assets,
  deterministic full-pass render), making the text-to-lottie deliverable an
  accepted *input* format rather than an authoring surface. Ships
  `docs/lottie.md`, a hand-authored `examples/lottie/bounce.json`, and a
  walkthrough section; `mux_frames_to_mp4` is extracted from `render_video` so
  both pipelines share one deterministic ffmpeg option set.
- **0.1.3 (2026-09)** — `--help` prints the docs/skill guide too. Agents reach
  for `--help` first and were walking into subcommands without ever seeing the
  composition contract; the pointer block moved into a shared
  `_resource_lines()` used by both the bare-invocation guide and the parser
  epilog, so the two cannot drift.
- **0.1.4 (2026-09)** — `--scale` draft renders. ThorVG re-resamples every
  `<image>` source into its destination rect on *every* frame, so scaling only
  the canvas bought ~10% no matter how small it got; `nanoframes.scale` instead
  rewrites each distinct local image once, before the frame loop, into a
  disk-cached copy at the render scale. Measured on a 1425-frame 1600×1200 clip
  over a 1560×991 board: 2m47s before, 49s at `--scale 0.5`, 17s at `0.25`,
  with full-quality output byte-identical. `--scale` also gained one meaning
  across `render`/`preview`/`video`/`lottie` (it had been an ffmpeg `-vf
  scale=`, which rasterized full-size and threw the pixels away).
- **0.1.5 (2026-09)** — field feedback from a 21-iteration clip (a 960×540
  pelican-on-a-bicycle loop) reported three failures that shared one shape: the
  composition rendered *something valid and silently wrong*. The baked root
  `<svg>` carried no `width`/`height`/`viewBox`, so ThorVG sized the picture
  from its **content bounding box** — one element outside the canvas rescaled
  and shifted the entire frame (measured 84.6% opaque coverage at `master-demo`
  t=0.1; larger excursions went fully transparent). `bake` now pins the
  viewport unless the author declared one, which makes off-canvas geometry
  exactly what it should be: clipped. An animated `transform` also layers
  *inside* the element's own static transform instead of replacing it, and
  `rotate`'s pivot became expressible at all. The failure mode had been
  invisible, so `nanoframes.bounds` + `nanoframes.diagnose` back a new
  `nanoframes debug` command — per-element post-transform boxes per frame,
  on-canvas/clipped/off-canvas classification, a whole-clip visibility scan,
  and the pixel diff between a loop's two seam frames — and `check` gained
  findings for geometry that never lands on the canvas.
- **0.1.6 (2026-09)** — one pivot concept for transforms: `"center"` (`"auto"`
  for the element's own geometry box, or `[cx, cy]`) now anchors `scale` as
  well as `rotate`, replacing the object form `{"rotate": {"deg":…,
  "center":…}}` that 0.1.5 had introduced hours earlier and never released.
  `check` errors on every transform value `bake` cannot express, with a test
  locking lint and bake to the same set. The pivot warning then found real
  instances in the shipped corpus — the `init` template's accent bar grew from
  the canvas corner, `master-demo`'s orbs and rule and `title-card`'s accent
  bar with it — so the template and all three examples were re-anchored, and a
  dogfood test keeps the corpus at *zero* `check` findings.
- **0.1.7 (2026-09)** — the Lottie import-render path was validated against a
  real corpus (ThorVG's own `test/resources` scenes plus `airbnb/lottie-web`'s
  animation gallery — 29 scenes, all render) and two defects surfaced, both
  about alpha. ThorVG's software canvas defaults to an alpha-*premultiplied*
  colorspace while the binding hands that buffer to Pillow's straight-alpha
  `frombuffer("RGBA")`, so every semi-transparent pixel came back darkened by
  its own alpha — on one corpus scene a quarter of the frame — and the MP4 path
  (`yuv420p` discards alpha) kept the darkened RGB. The un-premultiplied
  colorspace is now requested through `render.set_canvas_target`, shared by the
  SVG and Lottie renderers. Separately: a Lottie scene carries no scene-level
  background (the format has no such property), so an MP4 flattened the
  transparent canvas onto black and light-page animations became shapes in a
  void. `nanoframes lottie` now composites frames onto `--bg` — white by
  default, the page these scenes are authored against; `none` keeps the alpha
  for `--keep-frames`.
- **Deferred** optional binary tree-pack cache; CLI bridge for `text_handler`
  (it is a library-API feature by design); in-scene video; Lottie markers
  surfaced in the CLI; remaining recipe ports (product-promo,
  ui-microinteractions, diagram/technical, visual-effects).

`docs/` and `skills/` ship inside the pip wheel as `nanoframes/docs` and
`nanoframes/skills`; `nanoframes` (no args, or `--help`) prints their installed locations.
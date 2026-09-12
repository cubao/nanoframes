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
 media pre-pass: extract video frames (content-keyed cache); load nested compositions
        │
        v
 seek(t): evaluate animation timeline → per-frame property values
        │
        v
 bake(t): merge visibility + animated props into a frame-specific SVG
        │        (+ point video <image>s at their frame; inline nested compositions)
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

The checking is deliberately split into the two things a model cannot verify for itself —
**arithmetic** and **pixels** — and never into aesthetics, which it can. Every finding carries a
stable `code`, so the loop is closable programmatically: `check --json` emits
`{ok, errors, warnings, findings:[{severity, code, element, t, message}]}` and `debug --json`
emits the frame report, the clip scan and the loop seam. The always-on checks name the failures
that render as *something valid and wrong*:

| code | catches |
|---|---|
| `geometry.never_on_canvas` | geometry that draws nothing in any frame |
| `transform.no_pivot` | a `rotate`/`scale` around the origin that throws the element off its mark |
| `animation.outside_visibility` | an animation that runs entirely outside its element's window |
| `animation.target_unmatched` | a selector that matches no element |
| `transform.value_invalid` / `animation.transform_shape_mixed` | values bake cannot express, or shapes the interpolator cannot blend |
| `asset.missing` / `image.bad_aspect` / `media.*` | a missing asset, an unknown `data-aspect`, a video without ffmpeg or mapped past its source |
| `clip.*`, `canvas.*`, `animation.keyframe_out_of_range` | timing and canvas metadata that is out of range |

Two checks are **opt-in**, declared on the root `<svg>`, because they encode taste rather than
truth and must stay silent until asked for: `data-safe-margin="N"` (text must stay inside an
N-px inset — text only, since a full-bleed background touches every edge by design) and
`data-palette-budget="N"` (distinct declared paint colors). `check` also follows nested
compositions, so a defect inside an embedded child surfaces through the parent.

### Frame cache

A frame is a pure function of (source bytes, time, canvas size), so it is cached
on disk under a hash of exactly those — the full source bytes are folded in, so
any edit invalidates the whole clip's frames and the canvas size is in the key,
so draft and delivery frames coexist.

`nanoframes.cache.FrameCache` stores each frame as a plain PNG
(`files/<aa>/<hash>.png`) and keeps its bookkeeping in a
[diskcache](https://github.com/grantjenks/python-diskcache) SQLite index — that
gives per-entry TTL, capacity culling and cross-process locking, and the module
only owns the part diskcache does not: *"this key's value is this file"*. What
the index cannot do is become the truth: the payload directory is, so a missing
or foreign index is rebuilt from it on open, which is also how a cache written
by an earlier flat layout migrates without user action.

The cache maintains itself (a week's TTL, a byte cap, a sweep of crashed
in-flight writes) and never fails a render: a contended index read is a miss, a
contended write is skipped, and a payload deleted behind the index is
re-rendered. `nanoframes cache` reports it; `--clear` and `--trim` are the
manual levers.

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

## Embedded media (and why it is a pre-pass, not a renderer feature)

Three things can be embedded: a picture, a video, another composition. All three are normalized
*before* baking, so the renderer never grows a feature and every existing tool keeps working on a
media-heavy composition:

- **Pictures** — `data-aspect` computes the aspect-correct box, because ThorVG ignores
  `preserveAspectRatio` and stretches a picture to its declared `width`/`height`.
- **Video** — ThorVG is an SVG/Lottie rasterizer and cannot play video, and it does not need to:
  `media.MediaCache` extracts the source once into a frame sequence (content-keyed, and extracted
  *at the render scale*, which is where the draft speedup comes from), and baking points the node
  at the frame its time maps to. The mapping is one pure function,
  `src_t = data-in + (t - data-start) * data-speed` (wrapped under `data-loop`, clamped
  otherwise) — the same shape as `seek(t)`, which is what keeps a frame a pure function of
  `(source, t, canvas)`. Audio in the media is not mixed: a composition's audio is `video --audio`.
- **Another composition** — an `<image href="child.nf.svg">` is *inlined*: ThorVG cannot draw an
  SVG file as an `<image>` source (probed), so the child is baked at the mapped time and its tree
  replaces the node inside a scaling group. The child's own timeline runs on the mapped clock, so
  one badge composition can appear at speed 1 in one place and looping from its middle in another.

Preparation runs on the owned document and application on the *baked copy*, so
`Document.identity` — and with it the frame cache key — always describes the sources rather than
any generated frame. `refs.media_fingerprint` folds the content of every referenced file into
that identity, because a frame is a pure function of the composition *and its assets*: editing a
picture under an unchanged path has to invalidate the frames that drew it. The limitation is
stated rather than hidden: **media is a time-mapped rectangle of pixels** — no blending modes, no
speed ramps, no multi-track audio. Contract: [media.md](media.md).

## Scope decisions (what we drop from hyperframes)

| Hyperframes scope              | nanoframes |
|--------------------------------|------------|
| HTML/CSS + browser capture     | SVG + ThorVG software raster |
| GSAP / Lottie / Three.js / anime | declarative keyframe timeline (v1) — *except* Lottie **import-render**: ThorVG's native Lottie loader turns a lottie.json scene into a deterministic MP4 (`nanoframes lottie`, 0.1.1). Lottie is an accepted *input format*, not an authoring surface |
| inline `<video>` playback      | a video is extracted to a frame sequence and drawn as an `<image>` per frame (`data-in` / `data-speed` / `data-loop`); no decoder inside the renderer, and embedded media is silent |
| full audio mixing (buses, ducking) | optional FFmpeg audio mux passthrough — a composition's audio is `--audio`, and embedded media carries none |
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
- **0.1.8 (2026-09)** — `nanoframes diagram`: the editorial diagram craft of
  `cathrynlavery/diagram-design` (MIT) absorbed as a spec → `.nf.svg` builder
  rather than ported as HTML. Two layout grammars ship — `flow` (explicit node
  positions; the builder owns box sizing from measured text, orthogonal
  connector routing with per-edge port fanning, masked arrow labels, zones,
  legend, 4px-grid snap) and `loop` (the source's parametric ring: circular-arc
  flow cut against station boxes, dashed radial write-backs, derived canvas) —
  plus the source's complexity budgets as warnings and its §6 connector rules
  as unit tests. The build surfaced five ThorVG gaps, each worked around and
  documented in `docs/diagram.md`: `<marker>` is never drawn (arrowheads are
  computed polygons), `rgba(...)` paints solid black (hex + `fill-opacity`),
  `letter-spacing` and `text-anchor` are ignored (tracked and centred runs are
  emitted per character/glyph at the calibrated advance), and `<pattern>` (the
  dotted-paper variant) rasterizes to nothing. `text-anchor` mattered most: it
  silently left-aligned every node label, overflowing boxes that had been sized
  for centred text.
- **0.1.9 (2026-09)** — the hand-drawn register: `"skin": "sketchy"` draws any
  diagram with hand-drawn strokes. The browser version of this look is an SVG
  turbulence filter, which ThorVG does not rasterize, so the wobble is computed
  geometry instead (`nanoframes.diagram.sketchy`): every edge bowed and drawn
  twice, ring arcs sampled and displaced perpendicular to the radius, seeded
  from each shape's name so the same spec renders byte-identically on every
  machine. The palette follows the hand-drawn explainer convention
  (`hi-nikola/hand-drawn-explainer-video-nikola`, Apache-2.0): warm-white
  `#f8f6ef` page, marker outlines, one restrained accent. Structure is
  untouched — grid, budgets, connector clearance and centred text are the same
  as every other skin, and text is never roughened. The prompt-catalog side of
  that ecosystem (`yang0/handraw-style`'s 261 numbered art directions) is
  referenced for choosing a *look*, not ported: it addresses image generation,
  not SVG.
- **0.1.11 (2026-09)** — the frame cache was rebuilt on
  [diskcache](https://github.com/grantjenks/python-diskcache) (`nanoframes
  cache` now reports frames, bytes and TTL, with `--clear`/`--trim`). The
  design is the one from `bagless.utils.cached_files`: one plain file per key,
  per-key TTL, a byte capacity cap with opportunistic eviction, atomic
  placement, multi-process safety — absorbed rather than vendored, so the
  payload stays a PNG any tool can open and the index stays disposable. The
  payload directory is the source of truth: an index that is missing, stale or
  from the previous flat layout is rebuilt from it on open, which is how this
  checkout's existing 3995-frame cache migrated with no user action. Adding two
  dependencies (`diskcache`, `loguru`) was an explicit call; diskcache is
  stdlib-only itself and does the locking/TTL/culling that a hand-rolled index
  cannot do safely.
- **0.1.10 (2026-09)** — two corrections from using the diagram generator for
  real. Text placement stopped being per-glyph: ThorVG ignores `text-anchor`
  *and* resolves every family to the one loaded face, so a run's drawn width is
  its measured ink — one `<text>` at `x - ink/2 + left_bearing` is exact, where
  the per-glyph workaround could (and did) drift, overlap CJK, or lose the
  space glyph. And delivery resolution became a first-class control:
  `--dpi F` (on `render`/`preview`/`video`) re-rasterizes the same drawing at
  F x the pixel density — the frames were always re-rasterized (a 1px line
  lands on 8 real pixels at 8x), there was simply no way to ask for it, so a
  1280x720 preset read as "low resolution" on a retina screen. Diagram specs
  may carry a `dpi` hint, and `nanoframes diagram` prints the 2x command.
- **0.2.0 (2026-09)** — the media and verification batch. Two things a model cannot
  check for itself, made first-class. **Verification:** every lint finding gained a
  stable `code`, with `check --json` / `debug --json` for programmatic consumption;
  the oracle grew three checks (an animation whose whole span falls outside its
  element's window; `data-safe-margin` and `data-palette-budget`, both opt-in so
  they stay silent until asked for) and now follows nested compositions, so a
  defect inside an embedded child surfaces through the parent. **Media:**
  `data-aspect` (ThorVG ignores `preserveAspectRatio` — probed), video-backed
  `<image>` (extraction cache, `data-in`/`data-speed`/`data-loop` time mapping,
  per-frame injection), and nested `.nf.svg` inlining (ThorVG cannot load an SVG
  file as an `<image>` source — probed), which is composition reuse with the
  child's timeline on the mapped clock. The frame cache key now folds in the
  content of every referenced asset, fixing a latent staleness bug where swapping
  a picture under an unchanged `href` served frames of the old one. Three defects
  were found and fixed on the way, each of the silent kind this batch exists to
  hunt: `xlink:href` was baked with an auto-generated `ns1:` prefix that ThorVG
  does not resolve (an empty frame), `prescale_images` would call `Image.open` on a
  video source and raise out of a draft render, and `data-fit`/`data-anchor` were
  already taken by `<text>`, so the media attributes are `data-aspect`/`data-in`.
- **Deferred** optional binary tree-pack cache; CLI bridge for `text_handler`
  (it is a library-API feature by design); Lottie markers surfaced in the CLI;
  remaining recipe ports (product-promo, ui-microinteractions, diagram types
  beyond flow/loop, visual-effects); blending modes, speed ramps and multi-track
  audio (see [media.md](media.md#determinism-and-limits)).

`docs/` and `skills/` ship inside the pip wheel as `nanoframes/docs` and
`nanoframes/skills`; `nanoframes` (no args, or `--help`) prints their installed locations.
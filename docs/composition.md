# nanoframes composition contract

A composition is a single **`.nf.svg`** file: valid SVG + an embedded animation
timeline. Rendering is deterministic: the same `(composition, t, fps)` always
yields the same frame.

## Canvas (root `<svg>`)

| attribute | default | meaning |
|---|---|---|
| `data-width` / `data-height` | — (required) | output canvas, pixels |
| `data-fps` | `30` | frames per second |
| `data-duration` | `1.0` | total duration, seconds |
| `data-composition-id` | — | name used for frame/video output |

`width`/`height` are accepted as fallbacks for `data-width`/`data-height`.

## Element presence (clip in/out)

| attribute | default | meaning |
|---|---|---|
| `data-start` | `0` | absolute start time, seconds |
| `data-duration` | = composition duration | how long the clip is visible |
| `data-fade` | `0` | fade-in seconds at clip start (fade-out mirrors at clip end) |

Outside its `[start, start+duration]` window an element is `display:none` (not
rasterized). Fade and clip fold into the effective opacity.

## Animation timeline

Embedded as `<script type="application/nanoframes+json"><![CDATA[ … ]]></script>`.
The JSON has one `animations` array; each animation has a CSS `target` (selector
`#id`, `.class`, or tag) and ordered `keyframes`. Per keyframe: `t` (seconds),
any animated properties, and an optional `ease` (`linear` | `ease-in` |
`ease-out` | `ease-in-out`, default `linear`).

```json
{
  "animations": [
    {
      "target": "#title",
      "keyframes": [
        { "t": 0.0, "opacity": 0.0, "transform": { "translate": [0, 30] } },
        { "t": 0.7, "opacity": 1.0, "transform": { "translate": [0, 0] }, "ease": "ease-out" }
      ]
    }
  ]
}
```

Between keyframes, numeric properties interpolate **linearly** (after easing);
colors interpolate RGB; anything non-interpolable holds the earlier keyframe.

### Supported properties

| property | value | interpolation |
|---|---|---|
| `opacity` | float `0..1` | linear/eased |
| `transform` | `{"translate":[x,y], "rotate":deg, "scale":[sx,sy], "center":"auto"}` | elementwise |
| `fill` / `stroke` | `#RRGGBB` (or `#RRGGBBAA`) | RGB lerp |

Bake emits `transform="translate(x,y) rotate(d) scale(sx,sy)"` (translate ·
rotate · scale order).

#### Pivots: `center` for `rotate` and `scale`

SVG's own shorthand turns and grows an element around **`(0,0)`** — the canvas
origin, not the element. A long arm authored at `(480, 300)` swept by a bare
`rotate(90)` lands near `(-300, -480)`, i.e. off-canvas, where it draws nothing;
a rule authored at `y=150` with `"scale": [1, 0.02]` collapses toward the top
edge instead of growing in place. `center` is the anchor for both:

| form | pivots on |
|---|---|
| *(omitted)* | the origin `(0,0)` — SVG semantics, right for geometry authored around it |
| `"center": "auto"` | the element's own geometry box center |
| `"center": [cx, cy]` | an explicit point |
| `"rotate": [deg, cx, cy]` | an explicit point for that rotate only (wins over `center`) |

```json
{ "t": 0.0, "transform": { "translate": [480, 360], "rotate": 0, "center": "auto" } }
{ "t": 0.0, "transform": { "scale": [1.0, 0.02], "center": "auto" } }
```

`"center": "auto"` resolves per element at bake time to the center of the
element's own geometry (a group's children included), so it is the form to
reach for when you mean "spin / grow this thing where it is — or where it is
parked by its parent". It bakes to
`translate(cx,cy) <op> translate(-cx,-cy)`, once per anchored op. `scale` also
accepts a bare number (`"scale": 0.5`) for uniform scaling.

Keep the *same* shape across an animation's keyframes: the interpolator only
blends matching shapes (a number cannot interpolate into a pivot list, so it
holds the earlier value, and a bare `scale` holds while a `[sx,sy]` moves).
`nanoframes check` warns about both traps — an unanchored `rotate`/`scale` that
would throw the element off its mark, and shapes that change across keyframes —
and errors on values bake cannot express (a `rotate` written as an object, a
malformed `center`/`scale`), so the render never fails on them mid-clip.

#### Animated transforms layer inside the element's own

A keyframe `transform` is *motion*, not a replacement: bake emits
`transform="<the element's own> <animated>"`, so a positioned element keeps its
position while it animates.

```svg
<g id="crank" transform="translate(480 360)">   <!-- static position -->
  <line .../>                                   <!-- animated rotate spins here -->
</g>
```

That is exactly equivalent to nesting a wrapper group
(`<g transform="translate(480 360)"><g id="crank">…`), so the single-layer
form is safe to use. Only `opacity`, `transform`, `fill` and `stroke` are
overwritten by the timeline; every other attribute stays as authored.

## Geometry and the canvas

The baked frame pins its viewport to the composition's canvas
(`viewBox="0 0 data-width data-height"`), so **the canvas is exactly what the
composition declares**: geometry that leaves it is clipped at the edge and
nothing else changes. Declaring your own `viewBox` on the root `<svg>` is kept
as authored, which is the escape hatch for rendering a larger coordinate system
into the canvas.

Clipping is not an error, but two geometry mistakes render as *nothing at all*
with no other symptom, and `nanoframes check` warns about both:

- **geometry that never lands on the canvas** in any frame (an element
  translated out, or a pivot that throws it away);
- **a pivotless `rotate`** whose pivot sits far from the element (see above).

`nanoframes debug <comp>` reports where each element's box actually lands per
frame, and flags the ones that paint nothing; it also compares a loop's seam
frames.

A box landing on the canvas is not proof that anything of the element reached
the picture — a later sibling can paint over it, and every arithmetic reading
still says `on-canvas`. `nanoframes debug <comp> --pixels` answers that
question by **hiding each named element in turn and re-rendering the same
frame**: an element whose removal changes no pixel is buried, and the report
says so. It costs one render per element, so it is opt-in. Naming an element
(`id="…"`) is how it opts into being reported — a background rectangle is
covered by anything full-bleed drawn after it, and saying so every time would
train the reader to ignore the line.

## Seamless loops

`frame_count = round(duration × fps)` and rendering walks `t = i/fps` for
`i` in `0 … frame_count-1`. **The clip's last frame is therefore
`T' = duration - 1/fps`, not `duration`** — one frame short. A player looping
the file plays last frame → frame 0, so *that* pair is the seam:

- finish the motion by `T' = duration - 1/fps`, and hold it to the end;
- make frame 0 and frame `T'` identical in position, opacity and color — which
  means a full-cycle animation reaches its starting state exactly at `T'`, not
  at `duration`;
- verify with `nanoframes debug <comp> --loop`, which renders both seam frames
  and reports the fraction of pixels that differ.

```json
{ "animations": [{ "target": "#orbit", "keyframes": [
  { "t": 0.0,   "transform": { "rotate": 0   } },
  { "t": 1.9667, "transform": { "rotate": 360 } },   // T' for duration=2.0, fps=30
  { "t": 2.0,   "transform": { "rotate": 360 } }     // hold the seam state
] }] }
```

A keyframe placed at `duration` alone is one frame too late: the last rendered
frame still sits just before the end state, so the loop jumps.

## Media

- **Raster images**: `<image href="assets/foo.png" />` (relative paths are
  dereferenced against the composition directory).
- **Fonts**: text renders with a system font loaded automatically (Arial /
  DejaVuSans fallback). Declare `font-family`, `font-size`, `font-weight` as in SVG.

## Supported SVG surface

ThorVG rasterizes the **SVG Tiny 1.2** subset — see
`../thorvg.wiki/SVG-Support.md`. Shapes (`rect`, `circle`, `ellipse`, `path`,
`polygon`, `polyline`, `line`), `<image>`, gradients, `<text>`/`<tspan>`,
`<g>`, `clipPath`/`mask`, and transforms are supported. Layout/CSS keep their
SVG meaning but only within that subset.

### Known ThorVG behaviors

- **Text needs a loaded font.** ThorVG only rasterizes `<text>` after a font is
  registered (`Text.font_load`, done automatically per engine). Renders are
  therefore limited to fonts present on the host unless you supply one.
- **A frame that draws nothing is a valid PNG.** If every element is outside
  its clip window at a time, or its geometry is off-canvas, the frame comes out
  fully transparent — no error, no exception. Rendering prints a warning to
  stderr when that happens; run `nanoframes debug` to see which element is to
  blame.
- **`visibility` is ignored.** Probed, not assumed: `visibility="hidden"` and
  `visibility="collapse"` leave the element in the picture. `display="none"` is
  what hides, and it is honoured. `check` warns when it sees either value
  (`render.inert_attribute`), because the alternative is a wrong frame with no
  error. `opacity="0"` also works, but leaves the element in the tree to be
  composited.

## Text auto-layout (`data-*` on `<text>`)

Measured by the same ThorVG SVG loader that rasterizes the frame, so background
chips / wrapped lines / curved text always line up with the rendered glyphs.

| attr | meaning | default |
|---|---|---|
| `data-bg="COLOR"` | auto-sized rounded background chip behind the text | — |
| `data-bg-rx` | chip corner radius | `10` |
| `data-bg-pad-x` / `data-bg-pad-y` | ink-to-chip padding | `12` / `8` |
| `data-wrap="WIDTH"` | wrap text into stacked `<text>` lines fitting `WIDTH` px | — |
| `data-fit="WIDTH"` | auto-shrink font-size (floor `data-fit-min`) so the text fits | `data-fit-min=9` |
| `data-curve-d="PATH"` | place each char along a sampled SVG path `d` | — |
| `data-curve-circle="cx,cy,r[,startDeg]"` | place each char along a circle | — |

`data-wrap` breaks on spaces for Latin and between ideographs for CJK, and it
applies the Japanese line-break rules (禁則処理): a line never opens on a closing
punctuation mark (`。，、）` …) and never ends on an opening one (`（「` …), the
previous unit being sent down with the offender when the pair still fits. A
unit wider than the box on its own — a long unbroken word — is split by
character rather than placed whole, since overflowing the box silently is worse
than a mid-word break. Line advance is `1.2 × font-size`.

When auto-layout is used without a `Measurer` (e.g. a bare `bake_svg` call) it
is a no-op, so plain compositions bake exactly as before. See
`docs/text-capabilities.md` for the full audit and caveats.

## External raster text (`text_handler`)

Text that ThorVG fonts cannot cover — LaTeX math, an exotic brand face, emoji —
is rendered *outside* the framework by a library callback. Pass
`text_handler=callable` to `bake_svg` / `render_frame`; every
`<text data-raster="kind">` is offered to it as a `TextRequest` (content, kind,
style, fill, raw attrs). The handler returns **PNG bytes** and the node is
replaced by an `<image>` at an anchor-driven bbox, or `None` to keep the normal
ThorVG font path (auto-layout `data-*` still applies in that case).

| attr | meaning | default |
|---|---|---|
| `data-raster="KIND"` | opt in to the handler; `KIND` is passed through for dispatch | — |
| `data-in` | which bbox corner/edge sits at `(x, y)`: `top-*` / `middle-*` / `bottom-*` × `-left` / `-center` / `-right` | `center` |
| `data-width` / `data-height` | target box px; PNG is uniformly contained (no distortion) | natural size |
| `data-yaw` | degrees clockwise, rotating the image around the anchor point | `0` |

Contract: `x`/`y` mean the anchor point (not an SVG baseline) while rasterized;
bytes must decode as PNG (anything else raises at bake time); a handler should
be a deterministic pure function of the request and is invoked once per node
per bake — `render_frame` bypasses `FrameCache` whenever a handler is supplied
(its key knows nothing about the handler); CLI rendering has no handler and
falls back to fonts. See `nanoframes/rastertext.py` and
`tests/test_rastertext.py` for the reference contract.

## Fonts

A bundled **monospace CJK** face ships with nanoframes
(`fonts/SarasaMonoSC-Regular-noliga.ttf`, Sarasa Mono SC, ligature feature
stripped). Use `font-family="Sarasa Mono SC"` for deterministic-width Chinese
labels (each Han char = `font-size` px wide). Query it with
`nanoframes fonts list`; add other faces with `nanoframes fonts add <path>`.

## CLI examples

```bash
nanoframes doctor                   # can this machine render? (each failure names its fix)
nanoframes verify my-video.nf.svg   # all gates, one envelope, one exit code
nanoframes init my-video            # scaffold a .nf.svg
nanoframes check my-video.nf.svg    # lint (exit 1 on errors)
nanoframes debug my-video.nf.svg --t 2.0        # where each element lands, frame by frame
nanoframes debug my-video.nf.svg --pixels       # + hide each element to find buried ones
nanoframes debug my-video.nf.svg --loop         # + compare the loop's seam frames
nanoframes measure my-video.nf.svg  # report renderer-exact text widths
nanoframes render my-video.nf.svg --t 2.0          # single frame PNG
nanoframes render my-video.nf.svg --t 2.0 --dpi 2  # same frame, 2x pixel density
nanoframes preview my-video.nf.svg --t 2.0         # render + open
nanoframes render my-video.nf.svg -o frames        # full batch
nanoframes video my-video.nf.svg -o out.mp4        # MP4 via ffmpeg
nanoframes video my-video.nf.svg -o out.mp4 --audio track.mp3   # + audio mux
```
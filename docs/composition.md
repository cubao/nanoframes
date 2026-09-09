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
| `data-track-index` | `0` | track/ordering hint for clip overlap lint |

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
| `transform` | `{"translate":[x,y], "scale":[sx,sy], "rotate":deg}` | elementwise |
| `fill` / `stroke` | `#RRGGBB` (or `#RRGGBBAA`) | RGB lerp |

Bake emits `transform="translate(x,y) rotate(d) scale(sx,sy)"` (translate ·
rotate · scale order).

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

- **Keep transformed elements on-canvas.** An element whose transformed extent
  leaves the canvas (especially rotated, partially off-screen) is clipped
  coarsely: ThorVG paints **black** over the off-screen extent. Animate within
  the frame (fade/scale/grow in place, translate inside bounds) rather than
  sliding in from outside the canvas.
- **Text needs a loaded font.** ThorVG only rasterizes `<text>` after a font is
  registered (`Text.font_load`, done automatically per engine). Renders are
  therefore limited to fonts present on the host unless you supply one.

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
| `data-anchor` | which bbox corner/edge sits at `(x, y)`: `top-*` / `middle-*` / `bottom-*` × `-left` / `-center` / `-right` | `center` |
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
nanoframes init my-video            # scaffold a .nf.svg
nanoframes check my-video.nf.svg    # lint (exit 1 on errors)
nanoframes measure my-video.nf.svg  # report renderer-exact text widths
nanoframes render my-video.nf.svg --t 2.0          # single frame PNG
nanoframes preview my-video.nf.svg --t 2.0         # render + open
nanoframes render my-video.nf.svg -o frames        # full batch
nanoframes video my-video.nf.svg -o out.mp4        # MP4 via ffmpeg
nanoframes video my-video.nf.svg -o out.mp4 --audio track.mp3   # + audio mux
```
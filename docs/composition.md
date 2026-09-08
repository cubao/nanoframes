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

## CLI examples

```bash
nanoframes init my-video            # scaffold a .nf.svg
nanoframes check my-video.nf.svg    # lint (exit 1 on errors)
nanoframes render my-video.nf.svg --t 2.0          # single frame PNG
nanoframes preview my-video.nf.svg --t 2.0         # render + open
nanoframes render my-video.nf.svg -o frames        # full batch
nanoframes video my-video.nf.svg -o out.mp4        # MP4 via ffmpeg
nanoframes video my-video.nf.svg -o out.mp4 --audio track.mp3   # + audio mux
```
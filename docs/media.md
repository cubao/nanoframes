# Embedded media (`<image>` with video, pictures, or another composition)

A composition can draw three kinds of embedded media, and all three are placed
by the same time model — the one `seek(t)` already uses. Nothing here adds an
execution path: each case resolves to geometry or to a picture *before* baking,
so the renderer, the frame cache, `--scale`, `check` and `debug` keep working on
a media-heavy composition unchanged.

| what | how it is spelled |
|---|---|
| a picture | `<image href="assets/board.png" width="…" height="…"/>` |
| a video | `<image href="clip.mp4" …/>` — extracted frames, mapped by time |
| another composition | `<image href="lower-third.nf.svg" …/>` — inlined |

All three take the ordinary clip timing (`data-start`, `data-duration`,
`data-fade`) and the ordinary transform system.

## Keeping aspect: `<image data-aspect>`

ThorVG ignores `preserveAspectRatio` and always stretches a picture to its
declared `width`/`height` (probed: a 2:1 source in a 1:1 box renders
identically full-bleed for every `preserveAspectRatio` value). So "do not
distort my screenshot" is computed geometry instead.

| `data-aspect` | result |
|---|---|
| *(absent)* / `"stretch"` | ThorVG's own behaviour — the picture fills the box, distorted if the aspect differs |
| `"contain"` | scaled down to fit inside the box, centred (letterbox) |
| `"cover"` | scaled up to fill the box and **clipped** to it |

`data-aspect` needs a declared `width`/`height` to fit into; without one the
picture is drawn at its intrinsic size and the attribute does nothing. The
intrinsic size is read from the file (cached on path + size + mtime). `cover`
emits a `<clipPath>` for the box — ThorVG *does* honor `clip-path`, which is
the opposite of what the other gaps led us to expect.

`check` warns on an unknown value (`image.bad_aspect`); the renderer silently
leaves the geometry as authored, which is the right runtime behaviour and a
confusing authoring experience.

## Video

A video source cannot be rasterized by ThorVG (it is an SVG/Lottie engine), so
the media pre-pass extracts it once into a frame sequence and baking points the
node at the frame its time maps to.

### Time mapping

```
src_t = data-in + (t - data-start) * data-speed
```

| attribute | default | meaning |
|---|---|---|
| `data-in` | `0` | seconds into the source where this clip starts (the in-point) |
| `data-speed` | `1` | playback rate; `2` is double time, `0.5` half, `0` holds one frame |
| `data-loop` | off | wrap `src_t` modulo the source length instead of holding the last frame |

Without `data-loop` the picture **freezes on the last frame** once the mapped
time runs past the end; with it, it repeats. A negative `data-speed` plays
backwards (the wrap is modulo, so a loop still advances). This is a pure
function of `t`, which is the whole point: a frame stays a pure function of
`(source, t, canvas)`, so the cache and every inspection tool keep working.

`check` warns when a window maps past the end of its own source
(`media.out_of_range`) — a visible freeze that is easy to author by accident —
and when `data-in`/`data-speed` are not numbers (`media.bad_attribute`).

### The extraction cache

Each distinct source is extracted once, keyed by **(content hash, fps, scale)**:

- content-keyed, so editing the video invalidates its own frames;
- extracted **at the render scale**, which is where the draft speedup comes
  from — ThorVG resamples every picture into its destination rect on every
  frame, so a small source is what makes a draft draft;
- the sequence directory is the source of truth and a `.complete` marker means
  it finished, so a crashed extraction is redone rather than half-used.

`nanoframes cache` reports extracted sequences and `--clear` removes them with
the frames. The extraction cache is separate from the frame cache and is **not**
disabled by `--no-cache` (`--no-cache` is about re-rendering frames, not about
re-decoding a video).

**ffmpeg/ffprobe are required** for a composition with video. `check` reports
`media.missing_tool` as an *error* when a video is present and ffmpeg is not on
PATH, because the render genuinely cannot work.

### Audio

Embedded media is **visual only**. A video's own audio track is not mixed; the
composition's audio is the file passed to `nanoframes video --audio`. (No
multi-track mixing, no ducking — that is an NLE's job, not this one's.)

## Nested compositions (reuse)

An `<image>` pointing at another `.nf.svg` **inlines** that composition:

```svg
<image id="badge" href="badge.nf.svg" x="120" y="250" width="200" height="200"
       data-start="0.4" data-duration="3.6" data-speed="2.0"/>
```

This is the reuse story: a logo sting, a lower third, or a compiled diagram can
each be one composition embedded in many parents. The child's **own timeline
runs on the mapped clock** — `data-in`, `data-speed` and `data-loop` mean
exactly what they mean for video, so one child can appear at speed 1 in one
place and looping from its middle in another. `data-aspect` and the element's
own `transform` apply as they do everywhere else.

It has to be inlined rather than referenced because ThorVG cannot draw an SVG
file as an `<image>` source (probed: an SVG source renders nothing, where a PNG
renders — with either `href` or `xlink:href`, with or without a declared box).
So the child is baked at the mapped time and its baked tree replaces the node
inside a group that scales the child canvas into the element's box. A child's
generated clip-path ids are namespaced per child, since it shares the parent's
id space.

**Two consequences worth knowing:**

- The child is baked *inside* the parent's frame, so a child with its own
  `data-fade` will fade **out** at the end of its own window. A composition
  meant to be reused should keyframe its entrance rather than use `data-fade`,
  so it holds a visible final state when a parent clamps to its last frame.
- `check` follows nested compositions: a defect inside a child is a defect in
  the parent's output, so linting the parent lints the children and prefixes
  their findings with the child's file name. The depth cap (4) doubles as the
  cycle guard — a composition embedding itself stops with `media.nested_depth`
  instead of recursing forever.

`debug` reports a nested composition by the `<image>` element's declared box;
it does not bake the child (that happens at render time). See
`examples/nested-card.nf.svg` (a parent placing one badge three ways) and
`examples/badge.nf.svg` (the child).

## Caching and determinism

A frame is a pure function of the composition **and its local assets**, so the
render identity folds in the content of every referenced file
(`refs.media_fingerprint`). Editing a referenced picture — or the video, or a
nested child — under an unchanged path invalidates the frames that drew it.
Asset-free compositions keep the plain source hash, so no existing cache key
moved when this landed.

## ThorVG gaps (probed, not assumed)

| feature | behavior | what we do instead |
|---|---|---|
| `preserveAspectRatio` | ignored — the picture is stretched to its box | `data-aspect` computes the geometry |
| an SVG file as an `<image>` source | renders **nothing** | nested compositions are inlined |
| `clip-path` / `<clipPath>` | **works** (both on a `<g>` and on the element) | `data-aspect="cover"` clips with it |
| `<marker>`, `rgba()`, `letter-spacing`, `text-anchor`, `<pattern>`, `<filter>` | see [diagram.md](diagram.md#thorvg-gaps) | per that table |

## Determinism and limits

- Same inputs, same bytes: extraction is `ffmpeg` with a fixed filter chain,
  the mapping is arithmetic, and inlining is a deterministic tree rewrite.
- No multi-track audio, no blending modes, no speed ramps (a constant
  `data-speed` only), no in-scene transitions. The boundary is **media is a
  time-mapped rectangle of pixels**; anything past that belongs somewhere else.

# Text capabilities: audit, findings, and the nanoframes answer

This doc is the result of a full audit of our text story against the reference
projects — **hyperframes** and (its ancestor) **remotion** — plus the actual
ThorVG runtime we render with. It answers three questions with evidence and
specifies the features we added (and how to extend further).

## The three questions

### 1. Can we measure a text bounding box exactly? — Yes, and it must be renderer-exact

Two ways, and one of them is misleading:

| approach | exact? | notes |
|---|---|---|
| **rasterize + read ink** (what we use) | ✅ exact by construction | Reuses the *same* SVG loader, so the measured box always matches the final render. Size = tiny isolated `<text>` raster; cached by `(text, family, weight, size)`. |
| ThorVG `Text.get_aabb` / `get_metrics` | ❌ no | Two gotchas found empirically: (a) `set_size` is in **points** (px = size × `96/72`, so you must pass `px × 0.75`); (b) in this `thorvg-python 1.1.1` build a hand-built `Text` **reports metrics but does not rasterize**, and per-glyph widths are unreliable — a lone `i` measured `0.86 px`. The *newer* source `../thorvg-python` adds `get_glyph_metrics` + `line_count`; upgrading would give fast per-glyph advances. |

Because the background-misalignment bug you hit is exactly the "my vet habit maths the text differently than my renderer" failure, the invariant we chose is: **measure by rendering.** Same fonts, same loader, same result. Add a `Measurer` and auto-size from ink — it cannot drift.

### 2. Multiline text? — Not natively, so we build it

Empirically, in the installed ThorVG SVG loader neither route works:

- `<tspan>` with `x`/`y`/`dy` **renders all spans on the same baseline** (confirmed: two tspans at `y=100`/`dy=40` both ink a single 20 px-tall line).
- a literal `&#10;` newline is **collapsed into horizontal advance** (two "lines" render side by side, one line tall).

So multiline must be baked by us. We measure each candidate line and emit **separate `<text>` per line** (each line is its own paint, which ThorVG positions reliably). Interface: `data-wrap="<maxWidth>"`.

### 3. Text along a shape / curve? — No `<textPath>`, so we sample the curve ourselves

ThorVG's SVG loader has **no `<textPath>`** (confirmed: it loads with error code 0 but rasterizes nothing — an 8 px sliver). We implement the standard offline approach remotion exposes in `@remotion/paths` (`getPointAtLength` / `getTangentAtLength`): flatten the path, build an arc-length table, place each character at `point(s)` rotated to `tangent(s)`. Uses per-character ink advances for spacing. Mirrors remotion's `warp-path`/`paths` suite but as pure Python.

## Features we added (v1 of the text story)

All three are bake-time passes over the already-animated tree, driven by a
renderer-exact `Measurer` (`nanoframes/measure.py`, `curve.py`, `textflow.py`):

- **Measured background chip** — `<text data-bg="#3b5998" data-bg-pad-x="10" data-bg-pad-y="6" data-bg-rx="12">行人入侵</text>`: bake injects a rounded `<rect>` sized to the ink + padding. Padding/radius optional.
- **Auto-wrap paragraph** — `<text data-wrap="300">…</text>` (optionally with `data-bg` for a block chip): bake splits into stacked lines that fit the width.
- **Along-curve text** — `<text data-curve-d="M 90 300 C 200 190 420 190 560 300">DRIVE SAFE</text>` or `<text data-curve-circle="cx,cy,r[,startDeg]">…</text>`: bake emits rotated per-character `<text>` elements.
- **`nanoframes measure <comp>`** — prints each text's renderer-exact width, so an author can sanity-check widths before trusting a layout.

Consistency invariant: measurement uses the same font list, loader, and raster as the final frame. If auto-layout runs without a `Measurer` it is a no-op, so plain compositions bake exactly as before (all existing tests pass).

## What else is absorbable from hyperframes / remotion (ranked)

| idea | source | nanoframes status |
|---|---|---|
| measure + auto-fit font size (`fitTextFontSize` shrink-down until it fits one line) | hyperframes `core/text`, remotion layout-utils | ⚠️ trivial to add on top of `Measurer` (binary/step search). |
| word-level wrapping / caption timing | remotion `@remotion/captions`, layout-utils; hyperframes caption blocks | wrap ✅ done; caption-timing needs duration→width math, straightforward. |
| shrinkwrap "rounded text box" | remotion `@remotion/rounded-text-box` | ✅ done as `data-bg`. |
| per-char / per-word highlight, kinetic captions (weight-shift, gradient-fill, clip-wipe…) | hyperframes `docs/catalog/components/caption-*` | examples to port later; core is just `tspan`-replacements + fills we already bake. |
| global transforms (e.g. `getBoundingRect` helpers, `@remotion/paths` point/tangent) | remotion paths | curve ✅; expose `getLength/point/tangent` as re-usable module (done in `curve.py`). |
| variable-font axis animation | hyperframes `registry/components/variable-font-flex` | ⚠️ needs font with variation axes + a shaper; stretch. |
| Google-fonts auto-download | hyperframes/remotion `fonts` | ⚠️ offline equivalent = a `fonts/` dir + exact-family registration; see font note below. |

## Findings / caveats to keep in mind

- **Font coverage decides width.** A CJK string measured under a font lacking the glyphs still "measures" (via fallback), so a chip sized for it matches the *fallback* glyphs — not a real Chinese face. Use a face that actually has the glyphs.
- **ThorVG's loader font-family resolution is unreliable in this build.** A loaded font is not always used (`Arial Unicode MS` loads but never matches, so Chinese falls back to a dim built-in face). Empirically only some faces render solidly, and some *crash the process at teardown* when loaded (`AppleGothic` → segfault exit 139). `.ttc` collections can't be loaded at all.
- **We therefore do NOT auto-register discovered fonts in the renderer.** Instead: `nanoframes fonts list` shows CJK faces + exact family names; `nanoframes fonts add <path>` copies a font into `~/.local/share/nanoframes/fonts`; `nanoframes fonts verify <path>` rasterizes it in an isolated subprocess to check it doesn't crash ThorVG; `nanoframes fonts install` best-effort fetches a CJK monospace (默认 Sarasa Mono SC, 等宽). Use `font-family="<exact family from list>"`.
- **等宽 recommendation.** A true CJK monospace (Sarasa Mono SC) makes every Han char exactly `font-size` px wide, so measured chips are perfectly predictable. Until a ThorVG version reliably resolves custom fonts, `fonts verify` is the gate.
- **`set_size` points-vs-px trap.** If you use the raw `Text` metric API directly, px = size × `96/72`. We avoid it for exact work.
- **Upgrade path.** The newer `thorvg-python` (see `../thorvg-python`) reworks text/font support and exposes `get_glyph_metrics` + `line_count`; upgrading is the enabling change for a truly bundled/等宽 CJK font.

## Contract (extended)

New optional `data-*` on `<text>`:

| attr | meaning | default |
|---|---|---|
| `data-bg` | fill color of an auto-sized rounded background chip | — |
| `data-bg-rx` | chip corner radius | 10 |
| `data-bg-pad-x` / `data-bg-pad-y` | ink→chip padding | 12 / 8 |
| `data-wrap` | max line width (px); wraps text into stacked `<text>` lines | — |
| `data-curve-d` | SVG path `d` to lay characters along | — |
| `data-curve-circle` | `cx,cy,r[,startDeg]` circular layout | — |

Rendering a frame/video with these is unchanged: `nanoframes render|preview|video`.
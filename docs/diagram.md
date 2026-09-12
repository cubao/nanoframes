# Diagram specs (`nanoframes diagram`)

`nanoframes diagram <spec.json>` builds an editorial diagram — architecture
map, operating loop, process flow — into an ordinary **`.nf.svg` composition**:
`check`, `render`, `video` and `debug` all apply to the result unchanged, so a
diagram is a still PNG, a draft, or a revealing clip with the same toolchain.

```bash
nanoframes diagram spec.json -o diagram.nf.svg      # build a composition
nanoframes diagram spec.json --check                # build, then lint the result
nanoframes render diagram.nf.svg --t 0 -o shot.png        # a still (1:1)
nanoframes render diagram.nf.svg --t 0 --dpi 2 -o shot@2x.png   # delivery resolution
nanoframes video  diagram.nf.svg -o out.mp4         # if the spec set "reveal"
```

The design system, layout grammars and rules come from
[diagram-design](https://github.com/cathrynlavery/diagram-design) (MIT,
(c) 2025 Cathryn Lavery) — a 40-type diagram skill whose output is
self-contained HTML. This module keeps the *knowledge* (tokens, type
treatments, connector rules, complexity budgets, ring math) and re-expresses it
for a headless renderer; the browser idioms it cannot adopt are listed under
[ThorVG gaps](#thorvg-gaps) below. The craft references ship with the agent
skill: `skills/nanoframes/references/diagram-*.md`.

## The spec

One JSON object; the two kinds share a header.

```json
{
  "diagram": "flow",
  "skin": "light",
  "preset": "doc-wide",
  "title": "Ingest path",
  "subtitle": "Edge to store, one hop per arrow",
  "reveal": false,
  "nodes": [ {"id": "edge", "label": "Edge", "sub": "cdn:443", "x": 80, "y": 220, "type": "external"} ],
  "zones": [ {"id": "priv", "label": "Private zone", "nodes": ["gw"]} ],
  "edges": [ {"from": "edge", "to": "gw", "label": "TLS"} ]
}
```

| key | values | notes |
|---|---|---|
| `diagram` | `flow`, `loop` | required |
| `skin` | `light` (default), `dark`, `sketchy`, `terminal` | token skins; `sketchy` draws hand-drawn strokes on warm paper |
| `preset` | `doc-inline`, `doc-wide`, `slide-16x9`, `slide-4x3`, `social-og`, `social-square`, `print-a4-landscape`, `print-letter-landscape`, `fit` | canvas floor + type ramp; `fit` means the canvas is derived from content |
| `canvas` | `{"width": 1280, "height": 720}` | explicit canvas; overrides the preset, still a *minimum* |
| `title` / `subtitle` | strings | serif title, sans subtitle, drawn last (nothing covers them) |
| `legend` | `true` / `false` | default: auto — shown when 2+ node types are used |
| `margin` | number, default `40` | page margin (source uses 64 for `social-og`) |
| `fps` | number, default `30` | the composition's fps |
| `dpi` | number | delivery resolution hint: the printed next-steps render at this `--dpi` (default 2) |
| `duration` | seconds | default: computed from the reveal |
| `reveal` | `true` / `false` | stagger every element in with the timeline |

### `flow` — explicit layout

Nodes carry `x`/`y`; the builder owns everything else.

| node key | meaning |
|---|---|
| `id` | unique; defaults to a slug of `label` |
| `label` / `sub` / `tag` | the three text slots (sans name, mono technical sublabel, mono type tag) |
| `x`, `y` | required; snapped to the 4px grid with a warning |
| `w`, `h` | optional; auto-sized from the measured text otherwise |
| `type` | `backend` (default), `focal`, `store`, `external`, `input`, `optional`, `security` |
| `zone` | a zone id; the zone rect is computed from its members |
| `focal` | shorthand for `type: "focal"` (max 2 per diagram) |

| edge key | meaning |
|---|---|
| `from` / `to` | node ids |
| `label` | arrow label (uppercased, masked, 6–10px clear of the stroke) |
| `style` | `default`, `accent`, `link`, `dashed`, `async`, `return` |
| `from_port` / `to_port` | `left` / `right` / `up` / `down` — override the auto port pick |
| `label_side` | `h` (above a horizontal run) or `v` (beside a vertical one) |

### `loop` — computed ring

```json
{
  "diagram": "loop",
  "title": "The self-improving loop",
  "loop": {
    "hub": {"label": "Shared memory", "sub": "one record"},
    "radius": 240,
    "stations": [
      {"id": "capture", "label": "Capture", "sub": "signals in"},
      {"id": "decide",  "label": "Decide",  "sub": "human approves", "focal": true}
    ]
  }
}
```

5–8 stations, clockwise from the top (`-90°`, equal `360/N` steps), exactly one
hub. Ring connectors are circular arcs (`A R R 0 0 1`) cut against the station
boxes so each arrowhead lands on a box edge; write-back spokes are dashed radii
that stop 6px short of the hub. The canvas is derived (or the preset's, centred
on the hub).

## What the builder guarantees

- **Auto-sized boxes.** Node width/height come from the *measured* ink of the
  label and sublabel (same ThorVG measurement the render uses), rounded up to
  the 4px grid — text cannot overflow its box.
- **Orthogonal connectors.** Two-bend elbows with 8px quarter-arc corners;
  multiple connectors on the same box edge fan onto distinct attach points
  (≥12px apart); arrowheads are explicit polygons.
- **Masked arrow labels** with a 6–10px visible gap from their stroke, never
  overlapping a node (the source's §6 rules 2 and 6, as unit tests).
- **Taste budgets, as warnings.** Above 9 nodes / 12 edges the build warns;
  above 24 nodes it refuses (the source rule is to split into overview +
  detail). More than 2 focal nodes warns — the accent is editorial.
- **Determinism.** Same spec, same bytes. Every coordinate is rounded to 2
  decimals; text measurement is cached per distinct string.

## ThorVG gaps

This renderer is an SVG Tiny 1.2 rasterizer, not a browser. Four source idioms
do not survive, and the builder works around each (probed, not assumed):

| source | ThorVG behavior | what the builder does instead |
|---|---|---|
| `<marker>` arrowheads | attribute accepted, **nothing drawn** | computes the head polygon from the path's end tangent (filled + open heads) |
| `rgba(...)` fills | parsed as **solid black** | hex fills with a separate `fill-opacity` / `stroke-opacity` |
| `letter-spacing` | ignored | tracked runs (zone eyebrows, tags) emitted one `<text>` per character at the CSS advance |
| `text-anchor` | ignored — everything left-aligned at `x` | centred runs emitted one `<text>` per glyph, placed by the calibrated advance |
| `<pattern>` dot grid | rasterizes to nothing | not emitted (the dotted-paper variant is unavailable) |
| `<filter>` (turbulence, the browser's sketchy effect) | not rasterized | the sketchy skin computes its wobble as geometry instead (`nanoframes.diagram.sketchy`) |

Consequences worth knowing:

- Fonts come from the host. The source's Instrument Serif / Geist / Geist Mono
  are web fonts; the stacks here resolve offline — `Arial` (or DejaVu on Linux)
  for names, the bundled `Sarasa Mono SC` for technical slots, a serif stack for
  titles. Register a brand face with `nanoframes fonts add` and set it in a
  custom stack.
- `font-weight` is not a reliable axis (the engine's faces are regular-only),
  so weights are not emitted: hierarchy comes from size, spacing and color.
- CJK labels work (the bundled mono face), and the width budget rules the
  source documents for Hangul/Han apply unchanged.

## Hand-drawn output (`"skin": "sketchy"`)

A rendering register, not a second layout system: the same spec, boxes, grid and
connector rules, drawn with hand-drawn strokes on the warm-white page of the
hand-drawn explainer convention (`#f8f6ef`). Every edge is drawn as its own
bowed stroke, twice, with a lighter re-trace; ring arcs are sampled and wobbled
perpendicular to the radius; the tag chips and the loop hub go rough with
everything else. Text is untouched.

The browser version of this look is an SVG turbulence filter, which ThorVG does
not rasterize — so the wobble is computed geometry instead
(`nanoframes.diagram.sketchy`, amplitude 2.6px, seeded from each shape's name).
That makes it deterministic: the same spec renders byte-identically on every
machine and in every process order. Craft rules:
`skills/nanoframes/references/diagram-sketchy.md`.

## Library API

```python
from nanoframes.diagram import compose, build_scene, parse_spec, load_spec

svg = compose(spec_dict)                       # spec -> .nf.svg text
scene = build_scene(parse_spec(spec_dict))     # spec -> scene IR (coordinates, parts, warnings)
scene.warnings                                 # budget / grid / clipping findings
```

The scene IR (`nanoframes.diagram.scene`) is the testable surface: geometry is
asserted against it, not against SVG strings. Pass `measurer=None` for a
deterministic width estimate (no ThorVG import) — that is how the layout tests
run without a renderer.

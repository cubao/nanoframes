# Diagram specs (`nanoframes diagram`)

`nanoframes diagram <spec.json>` builds an editorial diagram — architecture
map, operating loop, process flow — into an ordinary **`.nf.svg` composition**:
`check`, `render`, `video` and `debug` all apply to the result unchanged, so a
diagram is a still PNG, a draft, or a revealing clip with the same toolchain.

For a **hierarchy** — org chart, taxonomy, decomposition — use
[`nanoframes tree`](tree.md) instead: it takes a nested node list with no
coordinates in it and compiles the layout, while everything on this page (tokens,
grid, measured text, legend, reveal, ThorVG gaps) applies to it unchanged.

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

## Grammars

A **grammar** is one compiler: its own spec plus its own data→geometry
algorithm, producing the same scene. That is the whole extension point — a new
grammar is a new algorithm over the shared page, never a new renderer, and the
emitter stays single.

| grammar | command | the input it compiles |
|---|---|---|
| `flow` | `nanoframes diagram` | nodes with explicit `x`/`y`, plus edges (below) |
| `loop` | `nanoframes diagram` | stations on a computed ring, plus a hub (below) |
| `tree` | [`nanoframes tree`](tree.md) | a nested node list, no coordinates |
| `chart` | [`nanoframes chart`](chart.md) | a data table, no coordinates |

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
  "nodes": [
    {"id": "edge", "label": "Edge", "sub": "cdn:443", "x": 80, "y": 220, "type": "external"},
    {"id": "gw", "label": "API Gateway", "sub": "grpc:8443", "x": 320, "y": 220, "type": "focal"},
    {"id": "db", "label": "Postgres", "sub": "orders", "x": 640, "y": 220, "type": "store"}
  ],
  "zones": [ {"id": "priv", "label": "Private zone", "nodes": ["gw", "db"]} ],
  "edges": [ {"from": "edge", "to": "gw", "label": "TLS"},
             {"from": "gw", "to": "db", "label": "SQL"} ]
}
```

| key | values | notes |
|---|---|---|
| `diagram` | `flow`, `loop`, `tree`, `chart` | required; picks the grammar (`tree` builds by `nanoframes tree`, `chart` by `nanoframes chart`) |
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

| zone key | meaning |
|---|---|
| `id` | referenced by `nodes[].zone` and by `zones[].nodes` |
| `label` | uppercased eyebrow on the plate's top-left corner |
| `nodes` | the member node ids, in spec order |

**Membership can be declared either way round** and the two are equivalent, so a
zone may list its members (`zones[].nodes`) or each node may name its zone
(`nodes[].zone`) — or a mix. The plate is the bounding box of its members plus
the fixed padding, snapped to the 4px grid, with the label in a paper chip so
connectors pass behind it. Two things are refused rather than guessed at: a name
in `zones[].nodes` that is not a node in the spec, and a node that ends up in two
zones (one plate per node). A zone nobody joins is a build *warning*, not a
silence.

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
      {"id": "distil",  "label": "Distil",  "sub": "one record"},
      {"id": "decide",  "label": "Decide",  "sub": "human approves", "focal": true},
      {"id": "act",     "label": "Act",     "sub": "ship it"},
      {"id": "measure", "label": "Measure", "sub": "did it work"}
    ]
  }
}
```

5–8 stations, clockwise from the top (`-90°`, equal `360/N` steps), exactly one
hub. Ring connectors are circular arcs (`A R R 0 0 1`) cut against the station
boxes so each arrowhead lands on a box edge; write-back spokes are dashed radii
that stop 6px short of the hub. The canvas is derived (or the preset's, centred
on the hub).

### `tree` — computed hierarchy

A nested node list with no coordinates in it, compiled by Reingold–Tilford. It
is a grammar of its own with its own command and page:
[docs/tree.md](tree.md).

### `chart` — computed scales

A data table — categories, series, axis titles — with no coordinates in it,
scaled and ticked by the compiler. The only grammar that adds a *scale* (a
value → a position) and a *tick algorithm* (1/2/5 × 10^k bounds). It is a
grammar of its own with its own command and page: [docs/chart.md](chart.md).

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

This renderer is an SVG Tiny 1.2 rasterizer, not a browser. These source idioms
do not survive it, and each is either **named by `check`** (probed, not assumed —
[composition.md](composition.md#known-thorvg-behaviors) carries the ink counts
behind every row) or deliberately left unchecked with the reason written down:

| source | ThorVG behavior | `check` code | what the builder does instead |
|---|---|---|---|
| `<marker>` arrowheads | attribute accepted, **nothing drawn** | `render.degraded_paint` | computes the head polygon from the path's end tangent (filled + open heads) |
| `rgba(...)` fills, and every other alpha spelling (`#rrggbbaa`, `transparent`, `rgb(a b c / d)`) | parsed as **solid black**, not translucent | `render.degraded_paint` | hex fills with a separate `fill-opacity` / `stroke-opacity` |
| `<pattern>` paint | rasterizes to nothing — the element **disappears** (`fill="none"` looks the same) | `render.degraded_paint` | not emitted (the dotted-paper variant is unavailable) |
| `visibility="hidden"` | ignored — the element is drawn anyway | `render.inert_attribute` | never emitted; `display="none"` is what hides |
| `letter-spacing` | ignored | `render.inert_attribute` | tracked runs (zone eyebrows, tags) are one `<text>` whose *measured* width already carries the advance a browser would add |
| `text-anchor` | ignored — everything left-aligned at `x` | `render.inert_attribute` | a centred run is one `<text>` at `x - ink_w/2 + left_bearing`, measured through the same engine |
| timing or a fade on a `<tspan>` | dropped — a `<text>` is drawn as **one unit**, so every attribute on a span is inert | `render.inert_tspan` | timing goes on the `<text>`; multi-line text is one `<text>` per line, never spans |
| `font-family` stacks | the whole value is one name, matched exactly; no list, no fallback chain | `render.unresolved_font_family` | every run names the bundled face, which is where the stack landed anyway |
| `<filter>` (turbulence, the browser's sketchy effect) | **partial**: `feGaussianBlur` rasterizes, `feTurbulence`/`feOffset`/`feColorMatrix` do nothing | — (unchecked: the supported subset is undocumented and four probes are not a criterion) | the sketchy skin computes its wobble as geometry instead (`nanoframes.diagram.sketchy`) |

Consequences worth knowing:

- Fonts come from the host, and exactly one is always there: the bundled
  `Sarasa Mono SC`, which is also where an unresolved `font-family` lands (the
  rule and its measurements are in
  [composition.md](composition.md#known-thorvg-behaviors)). The source's
  Instrument Serif / Geist / Geist Mono are web fonts that cannot be loaded
  offline, so every role in the skin names that one face — which is what the
  frames were drawing anyway. Naming a host font instead would be worse than
  inert: `Arial` resolves on macOS and not on a bare Linux box, so one spec would
  draw two different pictures depending on the machine that renders it. Register
  a brand face with `nanoframes fonts add` and name it exactly in a custom stack.
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

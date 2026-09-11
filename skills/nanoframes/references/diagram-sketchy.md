# diagram-sketchy — the hand-drawn register

Read with `diagram-design.md`. This file is the *visual* grammar for the
hand-drawn skin: `"skin": "sketchy"` on any diagram spec.

Two upstream sources feed it, both absorbed as rules rather than as assets:

- [diagram-design](https://github.com/cathrynlavery/diagram-design)
  `primitive-sketchy.md` (MIT, © 2025 Cathryn Lavery) — the "sketchy variant
  applied to any diagram type" idea: wobbled strokes over the same layout.
- [hi-nikola/hand-drawn-explainer-video-nikola](https://github.com/hi-nikola/hand-drawn-explainer-video-nikola)
  (Apache-2.0) — the explainer-video conventions behind the register: thick
  imperfect marker outlines, flat blocks, a warm-white page, and a *small*
  accent set. See also [yang0/handraw-style](https://github.com/yang0/handraw-style)
  for its numbered gallery of 261 hand-drawn art directions — useful when
  *choosing* a style for an image-generation prompt, but it is a prompt catalog
  for image models, not something this renderer can draw; do not promise a
  numbered style as an SVG output.

## What the skin actually changes

| | clean skins | `sketchy` |
|---|---|---|
| canvas | `#f5f5f5` / `#2d3142` | warm white `#f8f6ef` (the register's exact base color) |
| outlines | crisp `<rect>` / orthogonal paths | every edge drawn as its own bowed stroke, twice, with a lighter re-trace |
| connectors | rounded orthogonal elbows | the same routing, each leg bowed |
| ring arcs (loop) | SVG `A` arcs | the same arc sampled and wobbled perpendicular to the radius |
| type | measured, centred, unchanged | **unchanged** — text stays exact |
| fills | `node_style` washes | same roles, on warm paper |

Everything structural is untouched: the 4px grid, the box sizing, the budgets,
the connector rules, the arrow labels' clearance. Sketchy is a *rendering
register*, not a second layout system — a spec can switch skins and stay the
same diagram.

**Nothing in the browser version transfers.** diagram-design's sketchy variant
is an SVG turbulence filter, and ThorVG does not rasterize filters. The wobble
here is computed geometry (`nanoframes.diagram.sketchy`), which also makes it
deterministic: the same spec renders the same wobble, byte for byte, on every
machine and in every process order — no RNG state, no clock.

## When to use it

Good for: essays, explainers, teaching material, a diagram that should read as
"someone drew this while talking", content where the polish of the clean skin
would feel corporate.

Not for: technical reference diagrams, anything a reader will measure values
off, dense architecture maps (the wobble fights the routing), or a deck that
must match other clean slides. The clean skins are the default for a reason.

## Rules

1. **One register per diagram.** Never mix hand-drawn boxes with clean ones.
2. **Text stays exact.** The skin touches strokes only; if you want a
   handwritten *face*, add one with `nanoframes fonts add` and set it as the
   family — do not fake it with rotation.
3. **The accent stays restrained.** The register's palette is one strong red
   plus neutrals: 1–2 focal elements, same as every other skin.
4. **Wobble amplitude is fixed** (`JITTER = 2.6px`). A reader should see a
   drawn line, not a shaky one; do not scale it with the canvas.
5. **The mechanics still hold**: budgets, grid, connector clearance, and the
   arrow labels' 6–10px gap are unchanged — none of them relax because the
   strokes are rough.

## Checklist

- [ ] Was the register the *right* choice for this content (not just "looks fun")?
- [ ] One skin for the whole figure?
- [ ] Strokes are visibly drawn, not merely thicker?
- [ ] No clean rectangles left behind (boxes, zones, chips, hub all rough)?
- [ ] Accent on ≤2 elements?
- [ ] Would the clean skin communicate better? If yes, use it.

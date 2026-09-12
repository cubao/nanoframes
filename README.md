# nanoframes

**SVG-first, browserless, deterministic frame rendering on ThorVG.**

nanoframes is an offline counterpart to [hyperframes](https://github.com/heygen-com/hyperframes): the same
idea — *write a frame, render a video, built for agents* — but without a browser. Compositions are
authored as **SVG** documents plus a small declarative animation timeline, and every frame is
rasterized deterministically by **ThorVG** (`thorvg-python`) to PNG, then muxed to MP4 with FFmpeg.

Because nothing depends on a browser, an AI agent can render a frame or a whole clip locally in
milliseconds and iterate fast: `check` → `preview` → `render`.

When a frame comes out empty or an element is missing, `nanoframes debug <comp>` says why: it
prints where each element's transformed geometry lands, whether that is on the canvas, how many
frames the element is actually visible in, and how far a loop's two seam frames are apart.

## Status

**v1 complete.** Full offline pipeline works end-to-end: `init` → `check` →
`render`/`preview` → `video`. SVG compositions + declarative keyframe timeline are
rendered deterministically by ThorVG; MP4 export via ffmpeg; visual snapshots guard
regressions. Text auto-layout (measured chips, wrap, curve, fit) + a bundled
**monospace CJK** font (`Sarasa Mono SC`, ligatures stripped) for solid Chinese.
`nanoframes lottie` additionally renders Lottie/Bodymovin JSON scenes (the
text-to-lottie deliverable format) to MP4 offline through ThorVG's native
Lottie loader. The agent skill ships a motion/design craft reference library
(`skills/nanoframes/references/`, adapted from text-to-lottie, MIT).

`nanoframes diagram <spec.json>` builds an **editorial diagram** — an
architecture map, a process flow, an operating loop — into a composition from a
small JSON spec: you place the nodes and write the words, the builder sizes the
boxes from measured text, routes orthogonal connectors with rounded corners,
fans attach points, masks arrow labels, draws arrowheads as polygons, and holds
the design system's 4px grid and complexity budgets. The design system and
layout grammars come from [diagram-design](https://github.com/cathrynlavery/diagram-design)
(MIT); two grammars ship — explicit `flow` layout and the parametric `loop`
ring (stations on a circle, circular-arc flow, dashed radial write-backs). With
`"reveal": true` the diagram assembles itself along the timeline. See
[docs/diagram.md](docs/diagram.md) and the runnable `examples/*.nf.json`.

`--scale F` renders a **draft** at a fraction of the composition size. The
canvas *and* every embedded `<image>` shrink together — ThorVG re-resamples each
image source on every frame, so on a board-heavy clip the assets, not the canvas,
are what has to shrink for a draft to be fast. Measured on a 47.5s 1600x1200 clip
over a 1560x991 board: 2m47s at full quality, 49s at `--scale 0.5`, 17s at `0.25`.
Draft frames are for judging timing and composition; re-export at the default
scale for delivery.

## Media

`<image>` can embed a picture, a video, or another composition, and all three are
placed by the same time model. `data-aspect="contain"|"cover"` gives a picture an
aspect-correct box (ThorVG stretches one to its declared size and ignores
`preserveAspectRatio`). A video source (`.mp4`, `.mov`, `.webm`, …) is extracted
once into a frame-sequence cache and drawn frame by frame, mapped by `data-in` /
`data-speed` / `data-loop` (ffmpeg required; embedded audio is not mixed — a
composition's audio is `video --audio`). And an `<image>` pointing at another
`.nf.svg` **inlines that composition** — reuse a badge, a lower third, a compiled
diagram — with the child's own timeline running on the mapped clock, so one child
can appear at speed 1 in one place and looping from its middle in another.
`check` follows nested compositions, so a defect inside a child surfaces through
the parent. See [docs/media.md](docs/media.md) and `examples/nested-card.nf.svg`.

Diagnostics are machine-readable: every finding carries a stable `code`, and
`nanoframes check --json` / `debug --json` emit the structured form an agent
branches on instead of parsing prose.

## Layout

```
docs/             architecture + composition + lottie-import + diagram + media contracts
examples/         `.nf.svg` compositions, diagram specs + their built diagrams, lottie scenes
skills/nanoframes/ SKILL.md + references/ — agent production loop + craft library
nanoframes/       package (model, parser, timeline, bake, render, lint, cli, video, lottie, diagram, media)
tests/            unit + render + snapshot + CLI tests
```

## Docs

- [Architecture](docs/architecture.md) — why SVG + ThorVG, the pipeline, scope decisions.
- [Composition](docs/composition.md) — the `.nf.svg` contract (timing attributes + animation timeline).
- [Media](docs/media.md) — pictures (`data-aspect`), video, nested compositions, the extraction cache.
- [Text capabilities](docs/text-capabilities.md) — measured chips/wrap/curve/fit, bundled CJK font, `text_handler` escape hatch.
- [Lottie import](docs/lottie.md) — render Lottie JSON scenes to MP4 (`nanoframes lottie`).
- [Diagram specs](docs/diagram.md) — build editorial diagrams from JSON (`nanoframes diagram`).

`docs/` and `skills/` also ship inside the pip wheel (`nanoframes/docs`,
`nanoframes/skills`); running `nanoframes` with no arguments — or
`nanoframes --help` — prints where the docs and the agent skill live, repo
checkout or installed package alike.

## Diagrams

```bash
nanoframes diagram examples/architecture.nf.json -o architecture.nf.svg --check
nanoframes render architecture.nf.svg --t 0 -o architecture.png
nanoframes video  architecture.nf.svg -o architecture.mp4     # with "reveal": true
```

Two shipped specs to copy from: `examples/architecture.nf.json` (a zoned flow
with a dashed async edge) and `examples/loop.nf.json` (a six-station operating
loop with one focal station). Both build warning-free — the repo holds them to
that with tests, so the examples and their `.nf.svg` outputs cannot drift.
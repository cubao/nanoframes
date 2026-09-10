# nanoframes

**SVG-first, browserless, deterministic frame rendering on ThorVG.**

nanoframes is an offline counterpart to [hyperframes](https://github.com/heygen-com/hyperframes): the same
idea — *write a frame, render a video, built for agents* — but without a browser. Compositions are
authored as **SVG** documents plus a small declarative animation timeline, and every frame is
rasterized deterministically by **ThorVG** (`thorvg-python`) to PNG, then muxed to MP4 with FFmpeg.

Because nothing depends on a browser, an AI agent can render a frame or a whole clip locally in
milliseconds and iterate fast: `check` → `preview` → `render`.

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

`--scale F` renders a **draft** at a fraction of the composition size. The
canvas *and* every embedded `<image>` shrink together — ThorVG re-resamples each
image source on every frame, so on a board-heavy clip the assets, not the canvas,
are what has to shrink for a draft to be fast. Measured on a 47.5s 1600x1200 clip
over a 1560x991 board: 2m47s at full quality, 49s at `--scale 0.5`, 17s at `0.25`.
Draft frames are for judging timing and composition; re-export at the default
scale for delivery.

## Layout

```
docs/             architecture + composition + lottie-import contracts
examples/         `.nf.svg` compositions + lottie scenes
skills/nanoframes/ SKILL.md + references/ — agent production loop + craft library
nanoframes/       package (model, parser, timeline, bake, render, lint, cli, video, lottie)
tests/            unit + render + snapshot + CLI tests
```

## Docs

- [Architecture](docs/architecture.md) — why SVG + ThorVG, the pipeline, scope decisions.
- [Composition](docs/composition.md) — the `.nf.svg` contract (timing attributes + animation timeline).
- [Text capabilities](docs/text-capabilities.md) — measured chips/wrap/curve/fit, bundled CJK font, `text_handler` escape hatch.
- [Lottie import](docs/lottie.md) — render Lottie JSON scenes to MP4 (`nanoframes lottie`).

`docs/` and `skills/` also ship inside the pip wheel (`nanoframes/docs`,
`nanoframes/skills`); running `nanoframes` with no arguments — or
`nanoframes --help` — prints where the docs and the agent skill live, repo
checkout or installed package alike.
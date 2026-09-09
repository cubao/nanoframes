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

## Layout

```
docs/             architecture + composition contract
examples/         `.nf.svg` compositions
skills/nanoframes/ SKILL.md — the agent production loop
nanoframes/       package (model, parser, timeline, bake, render, lint, cli, video)
tests/            unit + render + snapshot + CLI tests
```

## Docs

- [Architecture](docs/architecture.md) — why SVG + ThorVG, the pipeline, scope decisions.
- [Composition](docs/composition.md) — the `.nf.svg` contract (timing attributes + animation timeline).
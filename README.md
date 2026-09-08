# nanoframes

**SVG-first, browserless, deterministic frame rendering on ThorVG.**

nanoframes is an offline counterpart to [hyperframes](https://github.com/heygen-com/hyperframes): the same
idea — *write a frame, render a video, built for agents* — but without a browser. Compositions are
authored as **SVG** documents plus a small declarative animation timeline, and every frame is
rasterized deterministically by **ThorVG** (`thorvg-python`) to PNG, then muxed to MP4 with FFmpeg.

Because nothing depends on a browser, an AI agent can render a frame or a whole clip locally in
milliseconds and iterate fast: `check` → `preview` → `render`.

## Status

Early scaffold. The composition contract and renderer are being built incrementally — see
`docs/architecture.md` and `docs/composition.md`.

## Layout

```
nanoframes/       package (model, parser, timeline, bake, render, cli)
docs/             architecture + composition contract
examples/         `.nf.svg` compositions
tests/            unit + render tests
```

## Docs

- [Architecture](docs/architecture.md) — why SVG + ThorVG, the pipeline, scope decisions.
- [Composition](docs/composition.md) — the `.nf.svg` contract (timing attributes + animation timeline).
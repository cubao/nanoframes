# Lottie import-render (`nanoframes lottie`)

ThorVG ships a native **Lottie (Bodymovin) loader** alongside its SVG loader,
and `thorvg-python` exposes it. `nanoframes lottie` renders a Lottie JSON
scene to a deterministic MP4 **offline** — no browser, no Skottie — with the
same engine and the same ffmpeg mux as `.nf.svg` compositions.

```bash
nanoframes lottie scene.json -o out.mp4
nanoframes lottie scene.json -o out.mp4 --keep-frames frames/   # keep the PNGs
nanoframes lottie scene.json -o out.mp4 --audio track.mp3       # mux audio (aac)
nanoframes lottie scene.json -o out.mp4 --scale 0.5             # draft at half size
```

Library API (`nanoframes.lottie`): `load_scene(path)` validates a scene,
`render_lottie_frames(path, dir)` renders every frame to
`<dir>/<name>.NNNNN.png`, `render_lottie_video(path, out)` muxes the MP4.
Raising `LottieError` on unreadable/blank scenes.

## Where scenes come from

The intended source is the **text-to-lottie** ecosystem
([diffusionstudio/lottie](https://github.com/diffusionstudio/lottie)): agents
author `lottie.json` scenes for the Skottie player; this command turns the
same deliverable into a video deterministically. Any Bodymovin-format JSON
works, subject to ThorVG's loader coverage.

## Rendering contract

- **Canvas**: the scene's own `w`/`h`, times `--scale` for a draft render.
- **Timing**: fps = scene `fr` (fallback 30); frame count = the loader's
  total (`op - ip`); every integer frame `[0, total)` is rasterized once.
- **Determinism**: same file + same library = byte-identical frames and MP4
  (same property the `.nf.svg` suite relies on). There is no frame cache —
  a Lottie render is a single full pass; hash the source to skip re-renders.
- **Scene-relative assets**: ThorVG resolves local image/font paths against
  the process CWD, so the CLI changes to the scene's directory before
  rendering (`-o`/`--keep-frames` are absolutized first). A
  text-to-lottie scene folder (lottie.json + sibling images/fonts) renders
  as-is.
- **Markers** (`get_marker`) and scene metadata load fine; named markers are
  not yet surfaced by the CLI.

## Coverage & limits

The loader is ThorVG's Lottie implementation — the support matrix in
[`thorvg.wiki/Lottie-Support.md`](../../../thorvg.wiki/Lottie-Support.md)
(trim paths, masks/mattes, layer effects, text, repeaters, ~75% expressions
via JerryScript) is the reference. Practical caveats:

- Audio assets are not processed (nanoframes never touches scene audio;
  add a soundtrack with `--audio` if needed).
- The rendered frame is the contract: when a scene's feature looks wrong in
  ThorVG but right in the browser/Skottie player, trust ThorVG for this
  output — and prefer authoring the scene within loader coverage.
- `nanoframes check` (the `.nf.svg` linter) does not apply; `nanoframes
  lottie` validates only that the file parses, has `w`/`h`/`layers`, and
  loads in ThorVG.

## Determinism note

Frames are rendered with a fresh `Engine` per call
(`LottieAnimation` + `picture.load` + `canvas.add` — the binding's documented
`canvas.push` does not exist on `SwCanvas` and must not be used). Nothing in
the loop touches wall-clock time, random state, or the network.

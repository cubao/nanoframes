# references — motion & design craft library

One-level reference files for the nanoframes agent skill. Read **only** the
files the SKILL.md routing table points at for the current task — never the
whole library.

These files adapt the craft knowledge from
[diffusionstudio/lottie](https://github.com/diffusionstudio/lottie)
(`skills/text-to-lottie/references/`, MIT license, © Diffusion Studio / the
text-to-lottie contributors) from the Lottie/Skottie world into the nanoframes
declarative SVG timeline. Anything renderer-specific was re-expressed in
nanoframes mechanics; the timing/taste/quality rules are shared.

## Translation conventions (Lottie → nanoframes)

| Lottie world | nanoframes world |
|---|---|
| frames @ 60 fps | seconds (canvas `data-fps`, default 30; divide frame counts by 60) |
| layer in/out `ip`/`op` | `data-start` / `data-duration` / `data-fade` (seconds) |
| keyframed property + bezier ease | keyframe JSON: `{ "t": sec, prop: value, "ease": ... }` — `linear`/`ease-in`/`ease-out`/`ease-in-out` only |
| overshoot / anticipation bezier | author explicit settle-back / anticipate keyframes |
| trim-path draw-on, mask wipes | **not animatable** — use opacity/transform choreography, per-line `data-start` reveals, or chip reveals |
| native text layer (`ty:5`) + slots | `<text>` with a real font (bundled `Sarasa Mono SC` for CJK, mono-deterministic); `data-wrap`/`data-bg`/`data-fit`/`data-curve-*` auto-layout |
| camera (parented group transforms) | animate a wrapper `<g>` transform — zoom **out** only or translate within margin (scaling content past the canvas edge paints black in ThorVG) |
| player verification (`?frame=N`, `/__context`) | `nanoframes check` → `preview --t SEC` → `render`/`video`, then inspect PNG frames |

## Mechanical rules every recipe inherits

1. **Stay on-canvas.** An element whose transformed extent leaves the frame
   paints a **black band** over the off-screen extent in ThorVG. Fade/grow in
   place, translate inside bounds; never slide content in from outside the
   canvas or scale a full-bleed group beyond `1.0`.
2. **Only these animate**: `opacity` (0..1), `transform`
   (`translate`/`scale`/`rotate`), `fill`/`stroke` color. Nothing else
   interpolates; text *content* is not a keyframeable property.
3. **Every animation target must exist** — the linter enforces it; keep
   keyframes inside `[0, data-duration]`.
4. **Monospace CJK is free**: `font-family="Sarasa Mono SC"` gives
   deterministic-width Chinese; use it for any columnar/digit layout so
   nothing jitters.

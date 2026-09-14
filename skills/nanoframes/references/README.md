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

`diagram-sketchy.md` additionally adapts the hand-drawn explainer conventions of
[hi-nikola/hand-drawn-explainer-video-nikola](https://github.com/hi-nikola/hand-drawn-explainer-video-nikola)
(Apache-2.0) — its warm-paper palette and marker-outline register — while noting
[yang0/handraw-style](https://github.com/yang0/handraw-style)'s numbered style
gallery as an image-generation prompt catalog this renderer cannot draw.

`diagram-design.md`, `diagram-flow.md` and `diagram-loop.md` adapt
[cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design)
(MIT license, © 2025 Cathryn Lavery) instead: the editorial design system and
two layout grammars, re-expressed as specs for the `nanoframes diagram`
generator rather than as browser HTML.

`motion-taste.md`'s easing vocabulary and its personality/overshoot budgets
also absorb
[LottieFiles/motion-design-skill](https://github.com/LottieFiles/motion-design-skill)
(MIT license) — its industry curve table (Material 3, Apple HIG, the overshoot
pair) and direction rules. That skill targets UI animation in a browser; the
parts that describe a live DOM (hover/press latency budgets, `prefers-reduced-motion`,
layout-triggering properties) do not apply to an offline SVG timeline and were
left behind. The curves themselves are implemented in `nanoframes/ease.py`.

## Translation conventions (Lottie → nanoframes)

| Lottie world | nanoframes world |
|---|---|
| frames @ 60 fps | seconds (canvas `data-fps`, default 30; divide frame counts by 60) |
| layer in/out `ip`/`op` | `data-start` / `data-duration` / `data-fade` (seconds) |
| keyframed property + bezier ease | keyframe JSON: `{ "t": sec, prop: value, "ease": ... }` — the ease belongs to the keyframe the motion *arrives at*, and is one of the four originals, a named curve (`standard`, `emphasized`, `ease-out-back`, `gentle`…), or a `cubic-bezier(x1,y1,x2,y2)` literal |
| overshoot / anticipation bezier | `"ease": "ease-out-back"` (passes the target, settles back) or `"ease": "ease-in-back"` (winds up first) — or hand-author explicit settle-back / anticipate keyframes when you want a shape of your own |
| trim-path draw-on, mask wipes | **not animatable** — use opacity/transform choreography, per-line `data-start` reveals, or chip reveals |
| native text layer (`ty:5`) + slots | `<text>` with a real font (bundled `Sarasa Mono SC` for CJK, mono-deterministic); `data-wrap`/`data-bg`/`data-fit`/`data-curve-*` auto-layout |
| camera (parented group transforms) | animate a wrapper `<g>` transform — a zoom-in past the canvas edge simply clips, and a pan can start off-screen; keep the *intent* readable |
| player verification (`?frame=N`, `/__context`) | `nanoframes check` → `preview --t SEC` → `render`/`video`, then inspect PNG frames |

## Mechanical rules every recipe inherits

1. **The canvas is the frame.** Geometry that leaves the canvas is clipped at
   the edge — a slide-in from off-screen is fine now, and nothing needs to be
   animated "inside bounds" for the renderer's sake. What is *not* fine is
   geometry that never lands on the canvas at all: it draws nothing, in every
   frame, silently. `nanoframes check` warns about it and
   `nanoframes debug <comp>` reports each element's box.
2. **`rotate` and `scale` act on `(0,0)` unless anchored.** `"rotate": 45`
   turns the element around the canvas origin, which throws anything authored
   elsewhere off its mark (and usually off-canvas); `"scale"` collapses a bar
   toward the canvas corner instead of growing in place. Add `"center": "auto"`
   next to the op (or `"center": [cx, cy]`, or an inline `[deg, cx, cy]` for
   rotate) and keep one shape across the animation's keyframes.
3. **An animated `transform` layers inside the element's static one** — put a
   positioned element's position in its own `transform` and animate the
   rotation/scale on the same element; no wrapper group is needed.
4. **Only these animate**: `opacity` (0..1), `transform`
   (`translate`/`scale`/`rotate`), `fill`/`stroke` color. Nothing else
   interpolates; text *content* is not a keyframeable property. Keep alphas
   inside `0..1`: the renderer **wraps** an out-of-range one rather than
   clamping it (`opacity="1.087"` paints at ≈0.08, nearly transparent), so
   `bake` saturates what the timeline computes and `check` names a literal
   out-of-range `opacity`/`fill-opacity`/`stroke-opacity`/`stop-opacity`
   (`render.out_of_range_alpha`).
5. **Every animation target must exist** — the linter enforces it; keep
   keyframes inside `[0, data-duration]`.
6. **An `ease` belongs to the keyframe the motion arrives at.** So the
   *landing* keyframe is the one to mark (`{"t": 0.7, …, "ease": "ease-out"}`),
   and an ease on the first keyframe can never apply — `check` names both that
   (`animation.inert_ease`) and a name that resolves to no curve
   (`animation.unknown_ease`). Omitting `ease` means linear, which is a
   legitimate declaration for rotation and progress, not a mistake.
7. **Monospace CJK is free**: `font-family="Sarasa Mono SC"` gives
   deterministic-width Chinese; use it for any columnar/digit layout so
   nothing jitters.
8. **A loop closes at `duration - 1/fps`** (the last rendered frame), not at
   `duration` — finish the cycle by then, hold it, and check the seam with
   `nanoframes debug <comp> --loop`.

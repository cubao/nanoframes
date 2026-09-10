# Recipe: loaders, icons & state feedback

Adapted from text-to-lottie `references/recipe-loaders-icons.md` (MIT).
Applies to: spinners/loaders, icon animations, success/error/warning states,
badges, empty-state nudges, progress indicators.

## Defaults

- Transparent canvas unless a full component card is requested.
- **Loops must be seamless** (see `motion-taste.md`): the state at
  `data-duration` equals the state at `t = 0`. A visible seam is a hard
  failure.
- One-shot state feedback (success/error) must **settle into a stable pose**
  and hold it — the user needs to read the outcome.
- One repeating primitive with phase offsets beats unrelated parts moving at
  the same period.
- **One charm gesture max** per icon (one bounce/overshoot); everything else
  calm. Errors are never playful.

## Presets (behavior briefs)

1. **spinner-rotate** — a ring (circle with `stroke`) rotating `linear`
   (the sanctioned mechanical case). Optional: a fading trail dot opposite
   the rotation for character.
2. **pulse-badge** — a dot/ring scales `1.0 → 1.15 → 1.0` with `ease-in-out`
   on a period; two rings phase-offset ~0.35–0.5 s.
3. **stroke-trace** — a check/arrow icon reveals via a *masked* wipe if the
   icon is a `<path>` (no trim-path animation in ThorVG SVG: approximate with
   a per-segment cascade — hand-split the path into segments, each with a
   `data-start` ~0.06 s apart, fading in with a tiny translate).
4. **check-complete** — success: circle scales in (settle-back), check
   segments cascade, then the whole state holds ≥ 0.5 s. Calm `ease-out`.
5. **error-shake** — error: icon fades in, a short horizontal translate
   shake (2–3 cycles of ±4 px, damped, ~0.5 s total), then hold; no bounce
   on the way in.
6. **warning-pulse** — triangle icon + slow pulse of an accent glow (soft
   radial gradient blob behind, opacity 0.15–0.35).
7. **progress-fill** — a bar fills via scale-x anchored left; percent value
   in mono font updates at beat points (staggered `<text>` windows); linear
   or calm ease.

## Timing (seconds)

| piece | duration |
|---|---|
| state feedback (success/error) | 0.5 – 1.25 s to the settled pose |
| loader cycle | 1 – 2 s, seamless |
| press / micro-feedback | 0.15 – 0.3 s |
| shake | ~0.5 s, amplitude decaying |

## Construction notes (nanoframes mechanics)

- Rotating ring: `<circle fill="none" stroke="…" stroke-width="…">` + rotate
  keyframes (`linear`). Stroke caps/joins: use `stroke-linecap="round"` when
  the design calls for round caps — verify ThorVG renders it as expected.
- Phase offsets: same timeline shape, `data-start` shifted by the phase
  duration, same period.
- Seamless check: finish the cycle by `data-duration - 1/fps` (the last
  rendered frame); frame `0` and that frame must match. `nanoframes debug
  <comp> --loop` diffs them for you.
- Keep animated icons on-canvas with margin — geometry past the edge is
  clipped, which silently eats a rotating icon's corners; and give a spinner a
  self-centered pivot (`{"deg": deg, "center": "auto"}`) or it orbits the
  canvas origin instead of spinning where it sits.
- Mono digits (`Sarasa Mono SC`) for any counter/percent so nothing jitters.

## Failure modes & acceptance

- Visible loop seam.
- Lockstep repetition (all parts same phase) where phase offsets would read
  better.
- Icon unreadable mid-motion (deformed mid-scale or mid-rotate).
- Over-playful errors (bounce on failure states).
- The settled pose is not held long enough to register.
- Check frames: `0`, mid-cycle, seam, and the settled hold.

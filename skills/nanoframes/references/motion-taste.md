# Motion taste — timing, easing, and staging that reads as intentional

Adapted from text-to-lottie `references/motion-taste.md` (MIT). A valid render
is not enough: motion must have **staging** (anticipate → action → settle), a
clear **primary subject**, and **purposeful easing**. Avoid linear motion
unless the intent is mechanical (progress bars, rotation, camera-less
monotony).

## Easing — behavior language over curve names

nanoframes keyframes carry one of `linear | ease-in | ease-out | ease-in-out`.
Pick by the *behavior* you want, not by habit:

| behavior you want | keyframe ease | notes |
|---|---|---|
| entrance that starts fast and lands (elements arriving) | `ease-out` | the default for entrances; motion is fastest at the start, settles as it arrives |
| exit / dismissal | `ease-in` | accelerates away — pair with a preceding settle so it doesn't feel cut |
| continuous travel, camera-like glide | `ease-in-out` | symmetric; used when an element moves between two held states |
| mechanical (rotation, progress, loop cycle) | `linear` | only when motion is truly constant-speed |
| **pop / overshoot** (a springy settle, a "snap") | `ease-out` + **author a settle-back keyframe** | e.g. scale `0.6 → 1.0` (ease-out) → `0.94` → `1.0`; overshoot reads as energy, never as default |
| **anticipation** (wind-up before action) | author an explicit reverse keyframe | e.g. translate `y 0 → 12` over ~0.08 s, then the real move |

No uniform ease for every layer: derive per-element ease from the element's
role. Only the focal element gets the strongest personality; supporting
elements use calmer variants of the same behavior.

## Timing defaults (seconds)

Frame counts below are the text-to-lottie norms at 60 fps, converted to
seconds; they read well at nanoframes' default 30 fps too (round to the
frame grid: multiples of `1/fps`).

| deliverable | duration |
|---|---|
| UI micro-motion (press, hover, toggle) | 0.15 – 0.5 s |
| state feedback (success/error/warning) | 0.5 – 1.25 s (settled pose at the end) |
| logo mark entrance | 0.75 – 2 s |
| lower-third / name tag: in / out | 0.75–1.5 s in, 0.5–1 s out |
| typography reveal (title, quote) | 0.75–2.5 s (longer for more words) |
| promo / product reveal | 1.5–3 s (multi-beat up to 4 s) |
| loader / icon loop cycle | 1–2 s per cycle, seamless |

Staging rule: **enter fast-ish, settle slower, hold.** The hold is where the
message registers — after the last element settles, keep a clean still for at
least ~0.4–0.8 s before the clip ends or the next beat starts.

## Choreography

- **Stagger, don't sync.** Supporting elements enter 2–8 frames apart
  (~0.07–0.27 s, compact UI) or 4–14 frames (~0.13–0.47 s, expressive).
  Reveal in reading/importance order, one origin (from the focal point
  outward).
- **One main flourish per beat.** If everything pops, nothing pops.
- **The focal element moves last or strongest**, and every other element's
  motion points at it (translate toward it, scale from it).
- **Per-property orchestration**: opacity can land while transform still
  settles; a late opacity settle over an eased transform reads premium.
  Locked elements (a persistent header) stay still while the stage changes.
- A staggered *exit* mirrors the entrance or reverses order — do not cut
  everything at once unless the cut is the point.

## Loops (loaders, icons, ambient)

- A loop must be **seamless**: the state at the loop end must equal the state
  at the start. Author the last keyframe as the first state (values at
  `t = data-duration` == values at `t = 0`), or the seam jumps.
- One repeating primitive with **phase offsets** between copies reads better
  than unrelated parts moving at the same period.
- Continuous rotation/progress is the sanctioned `linear` use; everything
  else in a loop keeps its ease character per cycle.
- Check the seam frame (`data-duration - 1/fps`) and frame 0 side by side.

## Data motion

- Bars grow from a baseline (scale `[1, 0] → [1, 1]` from the baseline edge —
  anchor via translate so the baseline doesn't move), lines draw left to
  right (reveal via a moving mask is unavailable — approximate by animating a
  per-segment `data-start` cascade or a covering chip that translates away).
- Count-up numbers: pre-render the changing digits as a monospace face —
  every digit occupies `font-size` px in `Sarasa Mono SC`, so staggering
  `<text>` elements (each a `data-start` window) can simulate a counter
  without jitter. Labels/units appear **after** the number resolves.
- **Serious data = calm ease-out, no bounce.** Reserve pops for brand/UI
  moments.

## Render-risk rules (ThorVG-specific)

- **Never move geometry off-canvas** — transformed extents that leave the
  frame paint a black band (see `references/README.md`). All choreography
  above is written to stay inside the canvas.
- Fade/scale in place instead of slides-from-off-canvas; use translate only
  within bounds.
- No motion blur, glow, blur, or particles: fake velocity with a streak shape
  that fades; fake glow with a soft-edged radial gradient blob behind the
  object; bake repeated elements by hand (they are cheap in SVG).
- Effects that need a *job*: reveal, emphasis, transition, state, or
  material. If the composition reads with the effect deleted, the effect is
  decoration — delete it.
- The "camera" is a wrapper `<g>` transform, and it can only zoom **out**
  (scale < 1 reveals canvas edge) or pan within content margin — a zoom-in
  past the canvas edge is impossible without black bands. Prefer element
  choreography over fake camera moves; if a move is needed, make it one
  dominant, smooth (`ease-in-out`), slow translate of a wrapper group that
  has margin slack.

## Final motion review

Scrub the beats by rendering frames at: `0`, first motion peak (~first
quarter), midpoint, settle (~last 20%), `data-duration - 1/fps`, and any
semantic beat (a number resolving, a word landing, a loop seam). Check beat
order, stagger origin, timing, settle/hold, loop seam, and readability
*during* motion — still-frame checks are not a substitute. If the motion
feels busy or accidental, simplify: fewer moving things, longer holds,
calmer eases.

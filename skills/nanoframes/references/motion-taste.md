# Motion taste — timing, easing, and staging that reads as intentional

Adapted from text-to-lottie `references/motion-taste.md` (MIT). A valid render
is not enough: motion must have **staging** (anticipate → action → settle), a
clear **primary subject**, and **purposeful easing**. Avoid linear motion
unless the intent is mechanical (progress bars, rotation, camera-less
monotony).

## Easing — behavior language over curve names

An `ease` belongs to the keyframe the motion **arrives at** (the CSS/Lottie
convention), so the *landing* keyframe is the one you mark. An ease on the first
keyframe shapes nothing — `check` reports it as `animation.inert_ease` — and a
name resolving to no curve falls back to linear, reported as
`animation.unknown_ease`.

Pick by the *behavior* you want, not by habit:

| behavior you want | keyframe ease | notes |
|---|---|---|
| entrance that starts fast and lands (elements arriving) | `ease-out` (or `ease-out-cubic`) | the default for entrances; motion is fastest at the start, settles as it arrives |
| exit / dismissal | `ease-in` | accelerates away — pair with a preceding settle so it doesn't feel cut |
| continuous travel, camera-like glide | `ease-in-out` | symmetric; used when an element moves between two held states |
| mechanical (rotation, progress, loop cycle) | `linear` | only when motion is truly constant-speed |
| **pop / overshoot** (a springy settle, a "snap") | `ease-out-back` | the curve passes the target and comes back — scale `0.6 → 1.0` overshoots to ~1.08 around the 60 % mark |
| **anticipation** (wind-up before action) | `ease-in-back` | dips below the start value, then leaves |
| a decisive on-screen move | `standard` | Material 3's `(0.2, 0, 0, 1)` — most of the distance is covered early |
| attention, emphasis, a hero entrance | `emphasized` | Material 3's entrance curve |
| ambient / background / "premium" | `gentle` | `(0.4, 0, 0.2, 1)` — slow and even, never demands attention |
| a sharp energetic deceleration | `ease-out-expo` | the "energetic" register |

Anything a reference table gives you goes in as its numbers:
`"ease": "cubic-bezier(0.175, 0.885, 0.32, 1.275)"`. `x1`/`x2` must lie in
`0..1` — that is what keeps the curve a function of time — while `y` is free,
and that freedom is what lets a curve overshoot. The names above live in
`nanoframes/ease.py`.

**"Settle-back" means this curve.** The recipe library names the *shape* — a pop
that overshoots its target and settles — in a lot of places. Build it with
`ease-out-back` on the landing keyframe: one attribute, with the overshoot inside
the curve. Reach for explicit keyframes only when you want a *damped
multi-bounce* (`0.5 → 1.05 → 0.98 → 1.0`), which a single bezier cannot express;
the second rebound costs two more keyframes to keep in sync, so want it on
purpose.

**Overshoot is budgeted.** It reads as energy, so spend it where energy is the
point: celebration 15–25 %, success 5–10 %, press/hover feedback 2–5 %, and
**0 % for errors** (an error that bounces feels unserious) as well as for a
premium or corporate register.

No uniform ease for every layer: derive per-element ease from the element's
role. Only the focal element gets the strongest personality; supporting
elements use calmer variants of the same behavior.

## One register, held

Consistency is most of what makes motion read as *designed* rather than
assembled, so pick one register for the piece and let its curves and overshoot
budget stay put. A compact palette:

| register | signature ease | overshoot | also |
|---|---|---|---|
| playful | `ease-out-back` | 10–20 % | arcs, a squash on impact, varied stagger |
| premium | `gentle` | 0 % | slow fades, subtle scale (98 % → 100 %), generous holds |
| corporate | `standard` | 0–3 % | straight paths, uniform stagger, clear state changes |
| energetic | `ease-out-expo` | 15–30 % | large displacement, fast colour, accelerating stagger |

Borrow a second register for *one* moment at most — a corporate dashboard's
success pop — and ease into the shift rather than snapping to it. If everything
is exaggerated, nothing is.

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
least ~0.4–0.8 s before the clip ends or the next beat starts. Over a longer
clip that reads as roughly a fifth of the time setting up, a third on the
action, and the rest resolving and holding.

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
- **Keep the total stagger under ~0.5 s.** Past that the last element lands
  after the viewer has stopped watching: tighten the step rather than dropping
  elements.
- **Follow-through and overlap.** A supporting element — a shadow, a label, an
  icon reaction — trails the thing it belongs to by 50–150 ms and uses a calmer
  curve, so the parts of one object do not all stop on the same frame.
- **The 1/3 rules.** No motion travels more than a third of the canvas without
  an intermediate keyframe (break the trip with a change of curve or speed), and
  with three or more animated elements no more than a third should be in active
  motion at once — stagger so the first has settled as the third starts.

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
- Count-up numbers: write the number with `data-frame-text` on the `<text>`
  that holds it (`"{value:03d}"`, `"second: {second:.2f}"`) — this *is* the
  counter, it is one element, and `check` fails on a field the frame does not
  offer rather than drawing braces. Use a monospace face (`Sarasa Mono SC`,
  every digit exactly `font-size` px) so the digits do not jitter as the value
  changes width, and let labels/units appear **after** the number resolves.
- **Serious data = calm ease-out, no bounce.** Reserve pops for brand/UI
  moments.

## Render-risk rules (nanoframes-specific)

- **Keep the subject on-canvas — but for the right reason.** Leaving the frame
  only clips it. The failure worth avoiding is an element that never lands on
  the canvas at all: it draws nothing, silently. `nanoframes check` warns about
  that case and `nanoframes debug <comp>` names it per frame. Motion *into*
  frame from off-canvas is allowed and often beats fading in place.
- **Anchor before you rotate or scale.** `"rotate": deg` turns around the
  canvas origin and `"scale": [sx, sy]` grows from it, so anything authored away
  from `(0,0)` sweeps the wrong part of the frame (and usually leaves it).
  `"center": "auto"` follows the element, `"center": [cx, cy]` pins an explicit
  point, and a wipe/grow-from-one-end is a *choice* made with an explicit pivot
  rather than an accident of the origin.
- No motion blur, glow, blur, or particles: fake velocity with a streak shape
  that fades; fake glow with a soft-edged radial gradient blob behind the
  object; bake repeated elements by hand (they are cheap in SVG).
- Effects that need a *job*: reveal, emphasis, transition, state, or
  material. If the composition reads with the effect deleted, the effect is
  decoration — delete it.
- The "camera" is a wrapper `<g>` transform: zoom and pan are both available —
  the canvas clips the overflow — so choose the move the story wants instead of
  one the renderer permits. Prefer element choreography; when a camera move is
  right, make it one dominant, smooth (`ease-in-out`), slow transform.

A loop that must not jump closes at `duration - 1/fps` — the last rendered
frame — and holds the seam state; `nanoframes debug <comp> --loop` reports how
far the two seam frames are apart.

## Final motion review

Scrub the beats by rendering frames at: `0`, first motion peak (~first
quarter), midpoint, settle (~last 20%), `data-duration - 1/fps`, and any
semantic beat (a number resolving, a word landing, a loop seam). Check beat
order, stagger origin, timing, settle/hold, loop seam, and readability
*during* motion — still-frame checks are not a substitute. If the motion
feels busy or accidental, simplify: fewer moving things, longer holds,
calmer eases.

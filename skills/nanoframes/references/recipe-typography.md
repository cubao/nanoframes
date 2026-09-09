# Recipe: typography & title cards

Adapted from text-to-lottie `references/recipe-typography.md` (MIT). Applies
to: title cards, quotes, editorial reveals, kinetic typography, wordmark
entrances, CJK headlines. Route here for any prompt whose main deliverable is
**words moving**.

## Defaults

- **One type idea per composition** (see `design-taste.md`). Mono CJK
  headlines are a nanoframes signature: `font-family="Sarasa Mono SC"` for
  deterministic-width Chinese or technical Latin; use it when exact width
  matters (chips, centering, columns).
- Static copy (paragraphs, labels) → a single `<text data-wrap="W">` or
  `<text data-bg="…">` (chip); it is baked into stacked lines that fit.
- Choreographed words (kinetic type) → **one `<text>` element per word**,
  each with its own `id`, so the timeline can move them independently.
- A title card is full-frame with a background; overlays/captions keep the
  background transparent unless asked.
- Text must stay fully readable in every animated frame — no clipping at the
  canvas edge (black-band rule), no overlap between stacked lines mid-motion.

## Roles (before keyframing)

- **anchor** — persistent text that stays still while the stage moves;
- **support** — subline/labels that enter after the anchor settles;
- **active** — words whose motion is tied to their meaning. Kinetic
  typography needs ≥ 1 active word; uniform entrance motion applied to every
  word is not enough.

Meaning-driven word motion (semantic rule): *fall* drops, *rise* lifts,
*snap* hits (overshoot), *heavy* lands with a settle-back, *loud* scales up,
*quiet* fades small, *fast* compresses its timing, *slow* holds.

## Presets (behavior briefs)

1. **title-clean** — headline fades/rises in place (`ease-out`, 0.3–0.5 s),
   then a hairline or accent chip draws, then the subline; final frame is a
   clean poster. Transparent or full-frame per ask.
2. **editorial-reveal** — stacked `data-wrap` lines enter one line at a time,
   each `data-start` staggered ~0.15 s, slight translate up + fade.
3. **quote-lift** — a quote block fades up; attribution fades in 0.4 s after
   the last quote line settles.
4. **kinetic-word-choreography** — per-word `<text>` elements; 1–2 active
   words get semantic motion, the rest enter with a calm stagger; ≥1 word
   uses overshoot settle.
5. **wordmark-cascade** — letters/words assemble into the lockup, then the
   whole lockup settles (used by the logo recipe too).
6. **numeric-pop** — the number is the focal: big mono value scales
   `0.85 → 1.0` with a settle-back; label and unit enter after it resolves
   (see `recipe-data-stats.md`).

## Timing (seconds)

| piece | entrance |
|---|---|
| short title (≤ 6 words) | 0.75 – 2 s total reveal |
| long quote | 1.5 – 4 s total, line stagger ≈ 0.15 – 0.35 s |
| subline / attribution | 0.3 – 0.6 s after the headline settles |
| settle-back pop | main move ~0.35 s + settle-back keyframes ~0.15 s |

## Construction notes (nanoframes mechanics)

- Entrance idiom that stays on-canvas: `opacity 0 → 1` + `translate [0, +N] →
  [0, 0]` (rises up into place) or `scale` from the text anchor. Never slide
  text in from outside the canvas edge.
- Chip text: `<text data-bg="#18324f" data-bg-pad-x="16" data-bg-pad-y="10">`
  — the chip is measured from the same renderer, so it cannot drift; animate
  the `<text>` element (chip travels with it).
- Fades across a beat: `data-fade="0.3"` on a text whose clip ends mid-scene
  gives a mirror fade-out for free.
- Curved text (`data-curve-d` / `data-curve-circle`) is for decorative single
  lines; do not animate the per-character baked elements.
- Keep the last 10–20% of the clip a clean hold: the final frame is a poster.

## Failure modes & acceptance

- **Unsafe-edge text** — words clipped by canvas or ThorVG black bands → all
  text fully inside bounds at every checked frame.
- **Mixed-baseline rows** — label + value sharing one baseline sinks the
  label (cap-center per run, see `design-taste.md`).
- **Uniform-everything motion** — no active word, no stagger → re-choreograph.
- **Readability during motion** — motion too fast to read (test at the peak
  frame), overlapping stacked lines mid-flight.
- Check frames: `0`, first word landing, midpoint, settle, `op - 1`.

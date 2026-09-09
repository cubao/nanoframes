# Recipe: lower thirds & caption bars

Adapted from text-to-lottie `references/recipe-lower-thirds.md` (MIT).
Applies to: name tags, title bars, captions, key-value straps, speaker
labels, broadcast-style overlays. nanoframes renders standalone frames, so a
"lower third" here is a **self-contained card on a canvas of its own** —
design it as an overlay asset (transparent background, safe margins) or a
full-frame card per the ask.

## Defaults

- **Legibility first**: name/subtitle sizes large enough to read at a glance;
  keep text away from the lower 10 % / edges (safe margins).
- Transparent canvas unless a full-frame card is requested.
- If the user has not supplied the copy, ask for the exact name/title/role
  strings before authoring — placeholder copy is acceptable only as an
  explicit stand-in.
- Structure: name (focal), subtitle/role (support), one accent (bar/dot/
  chip) in the brand color. Group them under one wrapper `<g id="lower">` so
  the whole card can be positioned as one unit.
- Held state must be stable: the card sits still from settle to clip end
  (usable as a reusable overlay).

## Presets (behavior briefs)

1. **clean-slide** — name fades/rises in place, accent bar scales in from
   left (`scale [0,1] → [1,1]` anchored at its left edge), subtitle follows.
2. **minimal-line** — a single hairline + name; the line draws via scale-x,
   name fades up over it.
3. **pill-reveal** — `<text data-bg>` chip; the chip scales in around the
   name from the text center, subtitle fades beneath.
4. **caption-strap** — `data-wrap` text over a full-width translucent bar
   (`rect` + `<text>`); bar fades in first, caption lines stagger in.
5. **social-tag** — small chip + handle; pops with a mild settle-back (UI
   energy, not broadcast calm).

## Timing (seconds)

| phase | duration |
|---|---|
| entry | 0.75 – 1.5 s (bars `ease-out` and snappy, text slightly softer) |
| exit | 0.5 – 1 s (mirror of entry, `ease-in` on the way out) |
| hold | ≥ 1 s stable before exit — the on-screen message needs reading time |

## Construction notes (nanoframes mechanics)

- Entrance idiom: fade + translate up a few px into place; bars grow via
  scale-x anchored with a compensating translate (`scale` in nanoframes
  scales around the origin — position the rect so its anchor is at the
  growth point, or pair `scale` with `translate`).
- All motion inside the canvas: the card enters from its own settled
  position, never from off-screen (black-band rule).
- Exit via clip window `data-duration` + `data-fade` gives a mirrored fade
  out; for a slide-out, keyframe the translate back toward center, not off
  canvas.
- Name + role stacking: two separate `<text>` elements with a consistent
  gap; cap-center math only matters when runs share a row (e.g. "NAME —
  ROLE" on one line — then align by cap height, see `design-taste.md`).

## Failure modes & acceptance

- Text too small / too much copy for the canvas (overlay must read at a
  glance) → trim copy.
- Accidental opaque background where a transparent overlay was asked.
- Card motion that clips the canvas edge at any frame.
- Hold too short: the card must sit still long enough to read before exit.
- Check frames: entry settle, full hold, exit start, `data-duration -
  1/fps`.

# Recipe: logo animation

Adapted from text-to-lottie `references/recipe-logo.md` (MIT). Applies to:
logo draw-on/build, mark + wordmark reveals, brand lockups, avatar/icon
marks. The deliverable is the **final lockup** — a held, clean brand shape.

## Defaults

- **Preserve the brand.** Keep the source geometry, colors, spacing, and the
  final lockup arrangement unless the user explicitly asks for a redesign.
  Start from the real logo SVG (trace it into shapes if needed), never a
  re-drawn approximation.
- Transparent background by default; add a background only when asked (a
  full-frame brand card).
- Lockup builds → settles → **holds**: the held lockup is where the brand
  registers. Keep the last ~10–20% of the clip a still.
- Do not distort brand geometry for effect (no random rotation/scale of the
  whole mark); animate *modules*, keep the mark's proportions intact.

## Structure

Separate the logo into pieces that can move independently — but animate only
structural modules:

- the **mark** (symbol/icon),
- the **wordmark** (name in type — real `<text>` with the brand font when
  available, otherwise the bundled mono as a stand-in with a note),
- one **accent** module (a dot, a bar, a color plane) if the logo has one.

## Presets (behavior briefs)

1. **mark-draw** — the mark assembles/fades in first, then the wordmark;
   the accent is last and smallest.
2. **assemble-settle** — modules translate/scale into lockup positions from a
   shared origin (the mark center), staggered ~0.1–0.2 s; whole lockup settles
   with one `ease-out`.
3. **premium-fade** — quiet: wordmark fades in, mark fades in slightly after,
   accent sweeps across the lockup once (a chip rect translating over it is
   not possible without masks — approximate with a short opacity/scale pulse
   of the accent).
4. **wordmark-cascade** — wordmark letters/words cascade in (per-word
   `<text>` elements, stagger ≈ 0.12 s), mark pops with a settle-back as the
   last word lands.
5. **splash-pop** — playful: mark scales from `0.5 → 1.05 → 0.98 → 1.0` over
   ~0.6 s (`ease-out` + authored settle-backs); wordmark slides up under it.

## Timing (seconds)

| piece | duration |
|---|---|
| mark only | 0.75 – 1.25 s |
| mark + wordmark | 1.25 – 2 s |
| premium settle | 0.3 – 0.5 s main move; settle-back ≤ 0.15 s; **no bounce** for premium |
| final hold | ≥ 0.3 s still before clip end |

**Do not show the full answer too early**: the mark should be readable before
the wordmark reveals, but the lockup should not be complete until ~60–70 %
into the clip unless the brief is a static reveal.

## Construction notes (nanoframes mechanics)

- Animate each module with its own `id`; common entrance: `opacity` + small
  `translate` toward the final position, `ease-out`, staggered by module.
- Lockup "pop" uses scale **from the lockup's visual center** — translate so
  the center stays fixed while scaling, or scale changes position.
- Everything stays inside the canvas: a full-lockup scale-up must leave
  margin; when scaling a lockup that fills the frame, scale from `0.96`-ish
  values only.
- When the source is a single-path logo and only whole-shape motion is
  possible, use fade + scale-in + a final still rather than fake
  "draw-on" (no trim-path animation in ThorVG SVG).

## Failure modes & acceptance

- Wordmark reveals before the mark is readable ("full answer too early").
- Geometry distortion from animating the whole lockup with non-uniform
  scale.
- Final frame ≠ clean lockup (element still mid-motion at clip end).
- Check the last frame is a **still** lockup; check the mark reads at frame
  ~0.5 s even before the wordmark lands.

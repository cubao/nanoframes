# Design taste — defaults that make agent output look intentional

Adapted from text-to-lottie `references/design-taste.md` (MIT). These rules are
renderer-agnostic: they apply to every `.nf.svg` you produce, whatever the
recipe. The most common agent failure is not bad rendering — it is *correct
rendering that looks generic*. These defaults exist to stop that.

## Decide the message before authoring

Before writing SVG, settle four things in one or two sentences:

1. **The single message** the composition states (one headline insight).
2. **The focal subject** — one object/word/number the eye lands on; it gets the
   strongest scale/weight/brightness and the strongest motion.
3. **One support layer** and **one accent system** (a color, a chip style, a
   stagger pattern) — repeated consistently.
4. **The final frame** — the composition must work as a static poster:
   remove one element and the message still reads; add nothing "to fill
   space".

## Premium means subtract, not add

When a prompt says *premium, clean, minimal, modern, sleek, sophisticated*,
default to restraint: **remove chrome before adding it**. Premium is carried by
scale, weight, brightness, spacing, and timing — never by cards, borders,
dividers, shadows, glow, or stacked tints.

- **Chrome/container budget is 0 by default.** Do not add a framing card,
  container, border, or divider unless it does a job whitespace and alignment
  cannot. Separate regions with negative space and alignment first, a single
  hairline second, a filled or bordered card last and only when explicitly
  warranted.
- **One surface tone.** Do not stack two near-black or two near-white tints to
  fake a "surface"; it reads muddy. If a card surface must differ from the
  background, make it one deliberate step with a clear purpose.
- **One divider treatment, one color.** If dividers are truly needed, use one
  weight and one color for all of them — title rules and column rules alike.
  Never use slightly different colors or weights per divider.
- **One type idea per composition.** Serif = human/editorial, grotesque =
  product, monospace = technical labels. Do not mix three voice families for
  decoration; `Sarasa Mono SC` reads as technical/mono — use it for labels,
  values, code, CJK headlines, not for body warmth.
- **Color**: black `#000` / white `#fff` are the premium default neutrals.
  One neutral + one primary + one accent at most. Quarantine saturation — one
  loud accent per frame; tonal steps (lighter/darker of the same hue) before
  shadows/glow.

## The anti-generic checklist

Technical/product work fails in predictable generic ways. Replace:

| generic habit | instead |
|---|---|
| dark grid + blue arrows + empty rounded cards + mono labels + decorative circles | meaningful node detail (labels inside nodes, real numbers), connections that mean something, no empty card outlines |
| arbitrary accent circles/dots scattered around | one accent system doing a job: ports, badges, state indicators, data points |
| gradient blobs / glow as fill | semantic fills: solid colors with tonal steps, a single deliberate gradient when a surface needs depth |
| decorative grid background | nothing, or a real measurement/axis the content sits on |
| 3D-ish tilted cards | flat composition with one focal depth cue (scale + shadow-less layering) |

## Typography alignment (the recurring visual tell)

Vertical misalignment is invisible in a quick glance and obvious on the final
frame. SVG text sits on a **baseline**, so optical centering must be computed,
not eyeballed:

- To vertically center a run in a container whose center is `cy`: use the
  cap-height math — `cap ≈ 0.7 × font-size` as a fallback; center so the
  caps sit centered (`baseline ≈ cy + cap/2`). nanoframes' own exact tool:
  render a frame and look — or use the raster ink path
  (`data-bg` chips align to the ink automatically).
- Mixed-size runs on one row (a small label and a large value) center each on
  the shared center line by its **own** cap height. A shared baseline sinks
  the smaller run — the classic label-under-value mistake.
- Stacked blocks (headline + subline) follow an intentional vertical rhythm:
  gap ≈ 0.5–0.8 × headline cap height, one consistent spacing step for all
  stacked text groups.
- **Zero-width digits jitter**: any number column uses the monospace face
  (`Sarasa Mono SC`) or fixed positions, never proportional spacing.

## Final-frame & spacing review before calling it done

- First and final frames must read as clean stills (no half-entered
  elements, no element still moving at `data-duration` unless looping).
- Focal point: largest, brightest, highest-contrast element is the message.
- Object budget: every element earns its place; when in doubt, delete.
- The 5-point restraint scan: (1) chrome removed? (2) one surface tone?
  (3) one accent system? (4) one type idea? (5) final frame works as a
  poster?

**Design quality is a completion blocker.** A composition that renders
correctly but is generic, crowded, or chrome-heavy fails the review.

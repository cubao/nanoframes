# Chapter transitions — long-form structure & seams

Adapted from text-to-lottie `references/chapterization-transition-grammar.md`
(MIT). Applies to: explainers, multi-point promos, feature lists, timelines,
before/after, problem→solution, multi-stat sequences — any composition with
**more than one idea**. One idea (a logo lockup, one CTA, one stat, a calm
hero) does **not** need chapterization; leave it as a single beat.

## When to chapter

Chapter when the content has > 1 idea that needs its own reading time:
long text, a feature list, several stats, a timeline, before/after,
problem/solution, quote + proof, a walkthrough, multi-language variants, a
recap. Give each chapter **its own visual armature** (its own layout beat) or
reuse one armature with evolving content; a "chapter" is a change of subject
plus a seam, not just a pause.

Chapter roles (pick per chapter): hook, setup, claim, proof, contrast,
detail, payoff, CTA/final lockup.

## Seam grammar (what a transition is made of)

A transition is **chapter role + timing + direction + cut point + easing** —
not easing alone. nanoframes can express five of the classic seams:

| seam | nanoframes mechanics | when |
|---|---|---|
| **hard cut** | the outgoing chapter's elements end at `t_cut` (`data-duration`), the incoming chapter's start exactly at `t_cut` | beats that contrast; fastest rhythm; pairs with a sound/visual accent |
| **crossfade** | outgoing fades out over the seam (`data-fade` mirrored, or keyframed opacity), incoming fades in over the same window | soft, editorial, calm; the default premium seam |
| **continuous carry** | one element (a headline word, a number, a logo) persists across the seam while everything around it changes; it moves/settles into the new chapter's layout | the through-line chapter (same subject evolving) |
| **cut on motion** | outgoing chapter is still moving **through** the seam: its last keyframe resolves past the cut (velocity rising or steady), and the incoming chapter starts moving immediately | energetic promos; hides the seam entirely |
| **hold → cut** | outgoing settles, holds ≥ 0.4 s, then cuts | calm/institutional/legal material; let the statement land |

(Classic *motion-masked wipes* and *occlusion wipes* need moving masks or
off-canvas travel — both violate ThorVG/on-canvas rules — so express them as
crossfades or hard cuts instead.)

**Cut-on-motion rule**: for a seam to feel continuous, the outgoing frame
must be moving with active continuation — e.g. its motion would resolve
0.3–0.6 s after the cut. A settled frame that then cuts reads as a jump, not
a transition.

**Readability**: every chapter's main message gets a coast/hold before any
seam — at least ~0.4–0.8 s with nothing entering.

## Seam plan (fill this in before keyframing)

Per seam between chapters, decide in advance:

1. seam time `t_cut` (absolute, seconds);
2. seam type (table above);
3. outgoing chapter's last action (settle or carry-motion through `t_cut`);
4. incoming chapter's first action (what the eye lands on first);
5. direction of travel (which side content feels like it comes from — stay
   on-canvas);
6. what persists (if continuous carry);
7. ease of both sides (entrance `ease-out`, exit `ease-in`, carry
   `ease-in-out`);
8. the two boundary frames to verify: `t_cut` and `t_cut - 1/fps`.

## Guardrails

- An isolated interrupted move looks broken: keep a rhythm of ≥ 3–4 beats
  before high-energy cuts; don't cut *into* the middle of one element's
  motion with nothing carrying.
- No high-energy cuts for calm/institutional/legal/read-critical content —
  hold → cut.
- Verify both boundary frames of every seam (render them), not just the
  seam's midpoint.
- Total duration sanity: chapter reading time (hold) dominates transition
  time; if seams feel rushed, lengthen holds, not transitions.
- Final chapter ends like any composition: settle and hold; last frame is a
  poster (a CTA/final lockup where the brief calls for one).

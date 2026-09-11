# diagram-loop — the parametric ring for `"diagram": "loop"`

Read with `diagram-design.md`. Use when the last step feeds the first **and** a
shared centre accumulates state — flywheels, operating loops, self-improving
systems, feedback cycles.

Do **not** use it for: a path that ends or branches (→ `flow`), or a cycle with
no shared state (draw it as a `flow` ring only if truly nothing accumulates —
otherwise it is a flowchart wearing a circle).

## The contract (it is the whole spec)

```json
{
  "diagram": "loop",
  "title": "The self-improving loop",
  "subtitle": "Every pass writes back to the shared record",
  "loop": {
    "hub": {"label": "Shared memory", "sub": "one record"},
    "radius": 240,
    "station_w": 160, "station_h": 64, "hub_w": 200, "hub_h": 104,
    "stations": [
      {"label": "Capture",  "sub": "signals in"},
      {"label": "Research", "sub": "evidence pulled"},
      {"label": "Decide",   "sub": "human approves", "focal": true},
      {"label": "Act",      "sub": "work ships"},
      {"label": "Measure",  "sub": "outcomes logged"},
      {"label": "Learn",    "sub": "playbook updated"}
    ]
  }
}
```

**Nothing here is a coordinate.** Station count, ring radius and box sizes are
the inputs; every angle, arc endpoint, spoke and canvas bound is computed. Two
builds from the same spec are visually identical.

## What the builder computes

- Station `k` (zero-indexed) sits at `-90° + k·360/N` on the ring, so station 0
  is at the top and the order proceeds clockwise. Order is semantic: the last
  station always feeds the first.
- **Ring arrows** are circular arcs on the station circle itself — they leave
  the source box where the circle crosses its edge and land on the destination
  box's edge, with a 1.2px marker overhang so the head touches the stroke.
- **Write-back spokes** are dashed radii from each station's inner edge toward
  the hub, stopping 6px short of the hub stroke so the lighter head never
  collides with it. The dashed inward spoke is the defining signal of this type
  — remove it and the figure is only a circular process.
- The hub is drawn in ink (paper text) and is the only dark element; at most
  one station may be `focal` (accent).
- The canvas is derived from the ring, or centred on the hub when `canvas` /
  `preset` is given.

## Rules

1. **5–8 stations, exactly one hub.** More stations crowd the hub: split into an
   overview loop plus detail diagrams. Two hubs are two systems — draw two
   diagrams.
2. **The hub is accumulated state**, not a process step: memory, standards,
   evidence, policy, the shared record. Keep its copy to a name plus one short
   sublabel.
3. **Equal angular spacing** unless a documented phase grouping requires a gap;
   uneven angles stop reading as one operating cadence.
4. **One focal station at most** — usually the editorial gate (a human
   approval, a decision, a checkpoint).
5. **Ring arcs stay outside the hub.** If the ring would cross it, increase
   `radius`; never route flow through the shared state.
6. **Station labels are short.** The ring gives each box ~2 words before the
   sublabel has to carry the rest (e.g. label `Measure`, sublabel
   `outcomes logged`).
7. **A loop that never actually returns is a flowchart** arranged in a circle.
   Show the real endpoint instead.

## Sizing guidance

- 6 stations is the canonical, most legible count; 5 and 8 both work.
- `radius` 240 with 160×64 stations and a 200×104 hub is the tuned default; a
  larger ring wants either bigger boxes or fewer stations, never both.
- Station boxes auto-size from their text (like `flow` nodes); give them enough
  room that the ring's gaps between boxes stay even.
- Long titles: the ring is vertically placed below the title band, so a title
  plus subtitle costs canvas height, not overlap.

## Rendering it

A loop with `"reveal": true` reads remarkably well as motion: rings and spokes
first, then the hub, then stations clockwise — the cycle assembles in the order
it operates. Render a draft first (`nanoframes video out.mp4 --scale 0.5`) and
check the seam if the clip loops.

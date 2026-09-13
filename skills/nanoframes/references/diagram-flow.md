# diagram-flow — layout grammar for `"diagram": "flow"`

Read with `diagram-design.md`. Applies to: architecture, system overview,
flowchart, process, data flow, deployment, dependency graph, swimlane-ish
layouts — anything where you place nodes and the builder routes the connectors.
A **strict hierarchy** — each child has exactly one parent — is the `tree`
grammar instead (`diagram-tree.md`): its layout is computed, so there is nothing
to place.

## The division of labor

**You** choose the layout: where each node sits, its type, its words, which
edges exist, what is focal. **The builder** owns boxes, sizes, port selection,
routing, masking, arrowheads, zones, the legend and the 4px grid. Do not
compute coordinates for anything except node positions — and place those on
multiples of 4 so nothing gets snapped.

## Placement recipe (what good layouts look like)

1. **Pick a direction** (left→right for pipelines, top→down for layered
   stacks) and hold it for the whole diagram.
2. **One row per tier**, one column per stage. Rows ~120–160px apart,
   columns ~200–240px apart. Content that flows across tiers uses the ports
   the builder picks; force them with `from_port`/`to_port` only when the
   auto pick reads wrong.
3. **Reserve the start of the canvas** for the title block (~120px); the
   builder translates content up onto the margin, so an approximate y is fine.
4. **Keep edges short and non-crossing.** If two edges must cross, accept the
   straight crossing the builder draws — in a `flow` diagram, crossings are
   cheaper than contrived detours. (The source's bridge/hop primitive exists
   for hand-drawn figures; it is not implemented here.)
5. **Zones** wrap 2+ nodes that share a boundary. Declare the zone, tag each
   member with `"zone": "<id>"`; the rect is computed. Max 3 zones — more is a
   swimlane.

## Connector rules the builder holds

- Exit/entry ports are chosen from the node centres' dominant axis.
- Several edges leaving one box edge fan onto distinct attach points ≥12px
  apart — never one shared point.
- Paths are orthogonal with 8px quarter-arc corners; the last segment's tangent
  decides the arrowhead, which is drawn as a polygon (ThorVG ignores
  `<marker>`).
- Arrow labels are uppercased, masked with a paper plate, and placed 6–10px
  clear of the stroke — above a horizontal run, beside a vertical one. Use
  `label_side` to force the orientation when the auto pick reads awkwardly.
- Edge styles: `default` (muted solid), `accent` (the headline path, ≤1),
  `link` (HTTP/API crossings), `dashed` (optional/return), `async` (dashed with
  an open head), `return` (dashed, lighter).

## Worked shape (an ingest path)

```json
{
  "diagram": "flow", "preset": "doc-wide",
  "title": "Ingest path", "subtitle": "Edge to store, one hop per arrow",
  "nodes": [
    {"id": "edge",   "label": "Edge",        "sub": "cdn:443",   "tag": "EXT",  "x": 80,  "y": 220, "type": "external"},
    {"id": "gw",     "label": "API Gateway", "sub": "grpc:8443",                "x": 320, "y": 220},
    {"id": "orders", "label": "Orders",      "sub": "orders-v2",                "x": 560, "y": 220, "type": "focal"},
    {"id": "db",     "label": "Postgres",    "sub": "orders",                   "x": 840, "y": 220, "type": "store"},
    {"id": "lake",   "label": "Object store","sub": "s3://raw",                 "x": 560, "y": 400, "type": "store"}
  ],
  "zones": [{"id": "priv", "label": "Private zone", "nodes": ["gw", "orders", "db"]}],
  "edges": [
    {"from": "edge",   "to": "gw",     "label": "TLS"},
    {"from": "gw",     "to": "orders", "label": "gRPC"},
    {"from": "orders", "to": "db",     "label": "SQL"},
    {"from": "orders", "to": "lake",   "label": "async", "style": "dashed"}
  ]
}
```

What the builder decides here: box sizes from the labels, the four elbow-free
horizontal runs and the one vertical drop (`orders` → `lake`, ports picked from
the y-delta), the zone rect around the three private nodes with its eyebrow,
an auto legend (4+ distinct kinds), and the canvas.

## Type-specific notes

- **Architecture / deployment**: zones are trust boundaries; `external` for
  anything outside them; one `focal` on the integration point that matters.
- **Flowchart / process**: top→down; keep branch labels short (`YES`, `NO`);
  a decision node is a `backend` box, not a diamond — this system does not use
  diamond shapes.
- **Data flow / medallion**: left→right through `store` nodes; use `sub` for
  the table or bucket (`orders`, `s3://raw`).
- **Org chart**: use the `tree` grammar (`diagram-tree.md`). In `flow` a
  strict hierarchy means hand-placing coordinates the builder could compute.
- **Dependency graph**: keep ≤9 nodes and ≤12 edges; if a cycle matters, prefer
  `loop` — it states the cycle far more legibly than a tangled graph.

## Budgets (warned by the builder, hold them yourself anyway)

≤9 nodes, ≤12 edges, ≤2 focal nodes, ≤3 zones, 0–2 arrow labels per diagram
(labels are for relationships that are *not* obvious from layout). If you are
over, split into overview + detail rather than shrinking type.

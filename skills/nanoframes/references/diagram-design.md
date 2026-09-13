# diagram craft — the editorial design system (spec-driven)

Read this when a task is a **diagram** (architecture map, system overview,
operating loop, process flow) rather than motion. The deliverable is a spec JSON
built by `nanoframes diagram` — **never** hand-author boxes and connectors in a
`.nf.svg`.

Adapted from [diagram-design](https://github.com/cathrynlavery/diagram-design)
(MIT, (c) 2025 Cathryn Lavery). The full source library covers 40 visual types;
this repo implements the three layout grammars that carry most of them, `flow`,
`loop` and `tree`. Contracts: [docs/diagram.md](../../docs/diagram.md) for
`flow`/`loop`, [docs/tree.md](../../docs/tree.md) for `tree`. Route by shape:

| the task | read |
|---|---|
| architecture, system map, flowchart, process, pipeline, deployment | `diagram-flow.md` |
| loop, flywheel, cycle, self-improving system | `diagram-loop.md` |
| org chart, hierarchy, reporting line, taxonomy, decomposition | `diagram-tree.md` |

## The one rule that matters

**The highest-quality move is usually deletion.** Every node is a distinct idea;
two nodes that always travel together are one node. A line whose relationship is
obvious from layout is noise. The accent (coral) is *editorial, not a flag*:
1–2 focal nodes per diagram, and using it on five erases the signal.

Target density 4/10 — enough to be complete, not so dense it needs a guide.
Above 9 nodes it is probably two diagrams.

## When not to draw

Before writing a spec, ask: *would the reader learn more from this than from a
well-written paragraph or a table?* If not, don't draw. A list is a list; a
before/after is a table; a one-shape "diagram" is a sentence.

## Skin tokens (hex, offline)

The builder emits the tokens; you pick roles, not colors. Light skin: paper
`#f5f5f5`, ink `#2d3142`, muted `#4f5d75`, soft `#7a8399`, accent `#eb6c36`,
link `#2e5aa8`. Dark skin inverts paper/ink and brightens the accent; `terminal`
is the CLI-chrome register. Node types map to treatments:

| type | reads as |
|---|---|
| `focal` | the 1–2 things the reader should notice (accent tint + accent stroke) |
| `backend` | a service / API / step (white fill, ink stroke) |
| `store` | a state store, database, buffer |
| `external` | outside the boundary (cloud, third party, user) |
| `input` | a person or an entry point |
| `optional` | async, passive, best-effort (dashed) |
| `security` | boundary / control (accent wash, dashed) |

Type ramp: node name 12px sans, sublabel 9px mono, tag/eyebrow/arrow-label 8px
mono uppercase. Titles are serif. Mono is for *technical* content (ports,
commands, URLs); names are never mono.

## Layout rules the builder enforces for you

- Everything lands on the **4px grid** (positions you supply are snapped, with a
  warning). Font sizes, box sizes, gaps and radii all come from the grid.
- Boxes are **sized from measured text**; don't hand-tune widths.
- Connectors are **orthogonal with rounded corners**, never diagonal.
- Arrow labels are masked and stay 6–10px clear of their stroke.
- An explicit canvas is a *minimum*: content that would spill past it grows the
  canvas and says so rather than clipping silently.

## The conventions you must hold

1. **State the plan before the spec**: type, size preset, and what the budget
   forces out. One short message; then build.
2. **One dominant direction per diagram** — left→right or top→down, held.
3. **Group by tier or trust boundary**, not by "looks balanced": zones are for
   VPC / public-private / department boundaries (max 3 before it wants swimlane).
4. **Remove test before shipping**: can any node go? any arrow? any label?
5. **Report what you cut.** If the source material had more than the diagram
   shows, say what was merged, collapsed, or dropped — the reader cannot see
   what is missing.

## Anti-patterns (any of these is an automatic redo)

| anti-pattern | why it fails |
|---|---|
| identical boxes for every node | erases hierarchy |
| coral on every important node | there is no focal point any more |
| a legend floating inside the diagram | it collides with nodes; it is a bottom strip |
| an arrow label sitting on its line | the connection stops being traceable |
| two connectors sharing a stroke path | the reader cannot tell them apart |
| dark mode + glow to look "technical" | decoration instead of decisions |
| shadows, big corner radii, card chrome | this system is borders + whitespace |
| 3 equal-width summary cards | vary the widths or drop them |
| reproducing another renderer's automatic layout (Mermaid, draw.io) | you are making an editorial figure, not a dump |

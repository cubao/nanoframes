# diagram-tree — layout grammar for `"diagram": "tree"`

Read with `diagram-design.md`. Applies to: org chart, reporting line, taxonomy,
category tree, decomposition, folder/permission hierarchy, decision tree —
anything where **the hierarchy is the argument** and hand-placing the boxes
would add nothing.

Contract and spec keys: [docs/tree.md](../../docs/tree.md).

## The division of labor

**You** choose the hierarchy: which box reports to which, the words, the node
types, what is focal, and when to stop. **The builder** owns every coordinate:
box sizes from measured text, the tidy layout (Reingold–Tilford), the 4px grid,
the connectors and their arrowheads, the row pitch, the canvas and the legend.
There is nowhere to write an `x` or a `y` — a spec that has one is refused.

## When a tree, and when a flow

| the shape | grammar |
|---|---|
| one box owns the boxes below it, strictly (each child has one parent) | `nanoframes tree` |
| boxes relate many-to-many, or the arrangement *is* the argument | `nanoframes diagram` (`flow`) |
| the same set of boxes comes back around | `nanoframes diagram` (`loop`) |

A dependency graph is not a tree: if a node has two parents, or an edge means
"uses" rather than "owns", draw it as `flow` and place it yourself. The tree
grammar will not tidy a general graph, and pretending otherwise produces a
confident-looking lie.

```bash
nanoframes tree org.json -o org.nf.svg --check
nanoframes render org.nf.svg --t 0 -o shot.png
```

## Authoring recipe

1. **One root.** The tree's root is its title's subject ("Platform team"), not a
   decorative apex box. If you need two roots, you need two charts.
2. **Depth ≤ 4, and 3 is usually best.** Every level below the root costs the
   reader a hop; a level that exists only to hold one box is a `sub` line on its
   parent, not a level.
3. **Siblings are peers, and their order is the message.** Left to right is
   reading order — put the branch you want noticed first (or the biggest) on the
   left. Nothing sorts them for you.
4. **`sub` carries the qualifier** (headcount, region, the system it owns); the
   `label` is a name. Do not put a sentence in either.
5. **Type the boxes by role**, not by decoration: `focal` for the one box the
   figure is about (1–2 per chart), `store`/`external`/`optional` where they
   apply. 2+ types pull in the legend automatically.
6. **15 boxes is the budget**, warned above. Past that it reads as a table:
   split by level (one chart per tier) or show one branch in full.
7. **No zones.** A tree's grouping is its levels and its branches; a box around
   a subtree fights the layout. If a division boundary is the point, that is a
   `flow` diagram.

## What the builder decides for you

- Boxes sized from the measured label/sublabel; every corner on the 4px grid.
- A parent centred over the extremes of its children; siblings packed left to
  right with `h_gap` (default 48) of air between subtrees.
- One row pitch for the whole chart (`v_gap`, default 64, below the tallest box)
  — set `h_gap`/`v_gap` only when a dense or sparse chart calls for it.
- Elbows from the parent's bottom centre, down–across–down, arrowheads as
  polygons (ThorVG draws no `<marker>`), landing on the child's top edge.
- The canvas: preset as a floor, centred on the **root**, clamped to the margins.
- `"reveal": true` staggers connectors then boxes in reading order.

Siblings share the horizontal run of their connector. That is deliberate (it is
what makes "these report to one parent" legible) and it is the one `flow` craft
rule a tree does not hold — see the anti-pattern note in `diagram-design.md`.

## Anti-patterns (any of these is an automatic redo)

| anti-pattern | why it fails |
|---|---|
| a 5-level org chart of 30 boxes | it is a table, or two charts; split by level |
| every box on one level, no children | that is a list, not a hierarchy — set it as text |
| boxes typed by colour for decoration | type describes a role; `focal` is editorial, 1–2 per chart |
| a "root" box invented to hold two unrelated trees | the figure now has two subjects |
| a `flow` diagram with a strict one-parent hierarchy, hand-placed | you paid for coordinates the tree grammar would have computed |
| zone rectangles around subtrees | fights the layout; use `flow` if a boundary is the point |

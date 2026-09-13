# Tree specs (`nanoframes tree`)

`nanoframes tree <spec.json>` lays out a **hierarchy** — org chart, taxonomy,
reporting line, decomposition — into an ordinary **`.nf.svg` composition**. The
spec carries no coordinates at all: you write the boxes and who reports to whom,
and the compiler computes the geometry.

```bash
nanoframes tree org.json -o org.nf.svg          # build a composition
nanoframes tree org.json --check                # build, then lint the result
nanoframes render org.nf.svg --t 0 -o shot.png  # a still
nanoframes video  org.nf.svg -o out.mp4         # with "reveal": true
```

## One of the grammars

`nanoframes diagram` and `nanoframes tree` are two front doors onto one contract.
A **grammar** is its own spec plus its own data→geometry algorithm, and every
grammar emits the same scene — so tokens, the 4px grid, measured text, the
legend, the reveal timeline, the canvas rules and every ThorVG workaround
([docs/diagram.md](diagram.md#thorvg-gaps)) are shared, not re-implemented.

| grammar | command | the input it compiles |
|---|---|---|
| `flow` | `nanoframes diagram` | nodes with explicit `x`/`y`, plus edges |
| `loop` | `nanoframes diagram` | stations on a computed ring, plus a hub |
| `tree` | `nanoframes tree` | a nested node list (this page) |

Reach for `flow` when the *arrangement is the argument* — a hand-placed pipeline
reads as a decision — and for `tree` when the *hierarchy is the argument* and
placement adds nothing. This is not a general auto-layout, on purpose: no box
model, no crossing minimisation, no arbitrary graph input. A hierarchy is the
one shape with an exact, deterministic algorithm, so it is compiled rather than
drawn; anything else is still a `flow` spec you place yourself.

## The spec

```json
{
  "diagram": "tree",
  "preset": "doc-wide",
  "title": "Platform team",
  "subtitle": "Three groups, one on-call rotation",
  "skin": "light",
  "reveal": false,
  "h_gap": 48,
  "v_gap": 64,
  "tree": {
    "id": "platform", "label": "Platform", "sub": "one team", "type": "focal",
    "children": [
      {"id": "runtime", "label": "Runtime", "sub": "bake + cache", "children": [
        {"label": "Frames", "sub": "bake"},
        {"label": "Cache", "sub": "diskcache"}
      ]}
    ]
  }
}
```

The header keys are the ones in [docs/diagram.md](diagram.md#the-spec)
(`diagram`, `skin`, `preset`, `canvas`, `title`, `subtitle`, `legend`, `margin`,
`fps`, `dpi`, `duration`, `reveal`). `tree` holds the root node; two keys are
tree-only:

| key | values | notes |
|---|---|---|
| `h_gap` | number, default `48` | air between two neighbouring subtrees, on the 4px grid |
| `v_gap` | number, default `64` | air below a row of boxes |

| node key | meaning |
|---|---|
| `id` | unique across the whole tree; defaults to a slug of `label` |
| `label` / `sub` / `tag` | the three text slots (sans name, mono technical sublabel, mono type tag) |
| `type` | `backend` (default), `focal`, `store`, `external`, `input`, `optional`, `security` |
| `w`, `h` | optional; auto-sized from the measured text otherwise |
| `children` | the boxes this one reports to, left to right |

`x` and `y` are **refused** — a position in a computed layout is a bug in the
input, not a nudge, and a silently ignored one would be worse.

## What the compiler guarantees

- **A tidy chart.** The layout is Reingold–Tilford in Buchheim et al.'s
  linear-time form (*Improving Walker's Algorithm to Run in Linear Time*, 2002):
  leaves pack left to right, a parent is centred over the extremes of its
  children, and neighbouring subtrees are threaded against each other's contours
  so a deep branch and a shallow one interleave instead of each reserving its
  full width. Same spec, same bytes.
- **Grid-aligned boxes.** Widths and heights come from the *measured* text — the
  same ThorVG measurement the render uses — and every box corner lands on the
  shared 4px grid. (The page may then move the whole figure by the title band's
  ink overhang — 6.2px on the shipped type ramp, exactly as it does for `flow` —
  which shifts the figure, not the layout.)
- **One row pitch.** Everything at the same depth shares a row; the pitch is the
  tallest box plus `v_gap`, snapped to the grid, so a shorter box simply gets
  more air around it.
- **The canvas centres on the root.** The root is the figure's visual anchor (a
  loop centres on its hub for the same reason), so the canvas centre goes on it —
  clamped, so a chart too wide for its frame pins to the margins instead of
  sliding off the page. An explicit `canvas` is still a *minimum*.
- **The legend and reveal are the page's.** 2+ node types get the bottom legend
  strip; `"reveal": true` staggers the same clock `flow` uses, in paint order
  (background → connectors → nodes → header → legend), so a tree builds
  top-down in reading order.

## Connectors, and one deliberate divergence from `flow`

Each child gets an orthogonal elbow from its parent's bottom centre — down,
across, down — ending on the child's top edge with the computed polygon
arrowhead ThorVG needs instead of `<marker>`. Siblings share that horizontal
run, which is the org-chart convention and the visual encoding of "these report
to one parent".

`flow`'s rule *no two connectors share a stroke path* exists to keep unrelated
relations apart. In a tree the shared trunk **is** the relation, so the rule is
relaxed here deliberately — and noted, because it is the one craft rule this
grammar does not hold. Everything else does: orthogonal routes, 8px quarter-arc
corners, no diagonal slants, no diamonds or card chrome.

## Budgets

Above 15 boxes the build warns: the source's "above 9 nodes it is probably two
diagrams", restated for a hierarchy, where the failure mode is width rather than
density. A chart that wide reads as a table — split it by level, or show one
branch. Nothing is refused: the canvas grows rather than clipping.

## Library API

```python
from nanoframes.diagram import GRAMMARS, build_scene, parse_spec, render

scene = build_scene(parse_spec(spec_dict))   # spec -> scene IR
scene.warnings                               # budget findings

GRAMMARS                                     # {"flow", "loop", "tree"} -> compiler
```

The scene IR is the testable surface here too: `tests/test_tree.py` asserts the
layout invariants — centring, gaps, grid, determinism, one line per child —
against the IR rather than against SVG text.

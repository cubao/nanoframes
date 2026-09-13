"""Editorial diagrams as nanoframes compositions.

A *diagram* is authored as a small JSON spec and emitted as an ordinary
``.nf.svg`` composition — so a diagram renders to PNG or MP4 with the same
deterministic, browserless pipeline as any other composition, and can reveal
itself with the same timeline.

**A grammar is one compiler**: its own spec plus its own data→geometry
algorithm, producing the same :class:`~nanoframes.diagram.scene.Scene`. The
grammar table below is the package's whole extension point — a new grammar is a
new algorithm over the shared page machinery
(``nanoframes.diagram.canvas``), never a new renderer and never a new emitter:

* ``flow`` — you place every node; the builder routes the connectors.
* ``loop`` — a cycle: stations on a ring, spokes writing back to a hub.
* ``tree`` — a hierarchy: a nested node list, laid out by Reingold–Tilford.

The design system, layout grammars and taste rules are adapted from
[diagram-design](https://github.com/cathrynlavery/diagram-design) (MIT,
(c) 2025 Cathryn Lavery). The browserisms are re-expressed for ThorVG:
arrowheads are computed polygons (``<marker>`` is not rendered), shapes use
``fill-opacity`` instead of ``rgba()`` (which paints solid black), and tracked
text is emitted with the advance a browser would give it
(``letter-spacing`` is ignored).

```python
from nanoframes.diagram import compose

svg = compose({"diagram": "flow", "nodes": [...], "edges": [...]})
svg = compose({"diagram": "tree", "tree": {"label": "Platform", "children": [...]}})
```
"""

from __future__ import annotations

from nanoframes.diagram.build import build_flow, build_loop
from nanoframes.diagram.emit import render
from nanoframes.diagram.spec import Spec, SpecError, load_spec, parse_spec
from nanoframes.diagram.tree import build_tree

#: Grammar name -> compiler. Every compiler takes ``(spec, tokens, measurer)``
#: and returns a ``Scene``; nothing else about a grammar is fixed.
GRAMMARS = {"flow": build_flow, "loop": build_loop, "tree": build_tree}

__all__ = ["compose", "build_scene", "GRAMMARS", "render", "parse_spec", "load_spec",
           "SpecError"]


def build_scene(spec: Spec, measurer=None):
    """Build the scene for any spec kind, through the grammar table."""
    from nanoframes.diagram.tokens import resolve

    try:
        build = GRAMMARS[spec.kind]
    except KeyError:
        raise ValueError(f"unknown diagram kind {spec.kind!r}") from None
    return build(spec, resolve(spec.skin, spec.preset), measurer)


def compose(data: dict, measurer=None, composition_id: str | None = None) -> str:
    """Spec dict → ``.nf.svg`` text (one call, for tests and tooling)."""
    spec = parse_spec(data)
    scene = build_scene(spec, measurer=measurer)
    return render(scene, composition_id=composition_id, measurer=measurer)


def warnings_for(data: dict, measurer=None) -> list:
    """Spec warnings without rendering (budget, grid snap, clipping)."""
    spec = parse_spec(data)
    return build_scene(spec, measurer=measurer).warnings

"""Editorial diagrams as nanoframes compositions.

A *diagram* is authored as a small JSON spec (nodes, labels, edges, focal
points) and emitted as an ordinary ``.nf.svg`` composition by
``nanoframes diagram`` — so a diagram renders to PNG or MP4 with the same
deterministic, browserless pipeline as any other composition, and can reveal
itself with the same timeline.

The design system, layout grammars and taste rules are adapted from
[diagram-design](https://github.com/cathrynlavery/diagram-design) (MIT,
(c) 2025 Cathryn Lavery). The browserisms are re-expressed for ThorVG:
arrowheads are computed polygons (``<marker>`` is not rendered), shapes use
``fill-opacity`` instead of ``rgba()`` (which paints solid black), and tracked
text is emitted per character (``letter-spacing`` is ignored).

```python
from nanoframes.diagram import compose

svg = compose({"diagram": "flow", "nodes": [...], "edges": [...]})
```
"""

from __future__ import annotations

from nanoframes.diagram.build import build_scene
from nanoframes.diagram.emit import render
from nanoframes.diagram.spec import SpecError, load_spec, parse_spec

__all__ = ["compose", "build_scene", "render", "parse_spec", "load_spec", "SpecError"]


def compose(data: dict, measurer=None, composition_id: str | None = None) -> str:
    """Spec dict → ``.nf.svg`` text (one call, for tests and tooling)."""
    spec = parse_spec(data)
    scene = build_scene(spec, measurer=measurer)
    return render(scene, composition_id=composition_id, measurer=measurer)


def warnings_for(data: dict, measurer=None) -> list:
    """Spec warnings without rendering (budget, grid snap, clipping)."""
    spec = parse_spec(data)
    return build_scene(spec, measurer=measurer).warnings

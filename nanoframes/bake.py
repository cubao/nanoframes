"""Bake a per-frame SVG document from a composition + time.

Given a parsed `Document` and a time ``t``, produce a standalone SVG string in
which every element's visibility (clip + fade), animated opacity, transform and
color are materialized. The `<script>` timeline is stripped so ThorVG only ever
rasters pure geometry.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from nanoframes.model import Composition, Element
from nanoframes.parse import Document
from nanoframes.refs import IMAGE_REF_ATTRS, REMOTE_SCHEMES
from nanoframes.timeline import effective_opacity, evaluate
from nanoframes.xmlutil import SVG_NAMESPACE, find_parent, float_attr, local_name

if TYPE_CHECKING:
    from nanoframes.measure import Measurer

# Serialize the SVG namespace unprefixed (`xmlns="..."`), which ThorVG's XML
# parser requires to resolve tag names correctly.
ET.register_namespace("", SVG_NAMESPACE)

_FILL_STROKE_TAGS = {
    "path", "rect", "circle", "ellipse", "polygon", "polyline",
    "line", "text", "tspan", "g", "use",
}


def _node_element(node: ET.Element, comp: Composition) -> Element:
    """Rebuild a lightweight Element from tree attrs (bake keeps nodes separate)."""
    fade = float_attr(node, "data-fade", 0.0)
    return Element(
        element_id=node.get("id"),
        tag=local_name(node.tag),
        classes=node.get("class", "").split(),
        clip_start=float_attr(node, "data-start", 0.0),
        clip_duration=float_attr(node, "data-duration", comp.duration),
        fade_in=fade,
        fade_out=fade,  # data-fade mirrors at the clip end
    )


def _pivot(op: str, pivot: "tuple[float, float] | None") -> str:
    """Wrap one transform operation so it happens about ``pivot`` instead of (0,0)."""
    if pivot is None or pivot == (0.0, 0.0):
        return op
    cx, cy = pivot
    return f"translate({cx:g},{cy:g}) {op} translate({-cx:g},{-cy:g})"


def _resolve_center(tf: dict, auto_center) -> "tuple[float, float] | None":
    """The transform's pivot: ``"auto"`` (the element's own box) or explicit ``[cx,cy]``.

    Returns None when no pivot was asked for (SVG's origin) or when a requested
    ``"auto"`` has no geometry to resolve against.
    """
    center = tf.get("center")
    if center is None:
        return None
    if isinstance(center, str):
        if center != "auto":
            raise ValueError(f"transform 'center' must be \"auto\" or [cx,cy], got {center!r}")
        return auto_center() if auto_center is not None else None
    if isinstance(center, (list, tuple)) and len(center) == 2:
        return (float(center[0]), float(center[1]))
    raise ValueError(f"transform 'center' must be \"auto\" or [cx,cy], got {center!r}")


def _rotate_string(r: object, pivot: "tuple[float, float] | None" = None) -> str:
    """One ``rotate`` from the timeline: bare degrees, or [deg,cx,cy] for an inline pivot."""
    if isinstance(r, dict):
        raise ValueError(
            "rotate takes degrees or [deg, cx, cy]; put a reusable pivot in the"
            ' transform\'s "center" (e.g. {"rotate": 45, "center": "auto"})'
        )
    if isinstance(r, (list, tuple)):
        if len(r) == 3:
            return f"rotate({r[0]:g} {r[1]:g} {r[2]:g})"  # inline pivot wins over 'center'
        raise ValueError(f"rotate needs [deg, cx, cy], got {list(r)!r}")
    return _pivot(f"rotate({float(r):g})", pivot)


def _scale_string(s: object, pivot: "tuple[float, float] | None" = None) -> str:
    """One ``scale``: ``[sx, sy]``, ``[s]`` (uniform), or a bare number."""
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return _pivot(f"scale({float(s):g})", pivot)
    if isinstance(s, (list, tuple)) and 1 <= len(s) <= 2:
        sx = float(s[0])
        sy = float(s[1]) if len(s) == 2 else sx
        return _pivot(f"scale({sx:g},{sy:g})", pivot)
    raise ValueError(f"scale needs [sx, sy] or a number, got {s!r}")


def transform_string(tf: object, auto_center=None) -> str | None:
    """Serialize a timeline ``transform`` value to an SVG transform string.

    Order is translate -> rotate -> scale. ``center`` (``"auto"`` or ``[cx,cy]``)
    is the pivot for *both* ``rotate`` and ``scale``, since SVG's own defaults
    turn them around the canvas origin — which moves an element that was not
    authored there. ``auto_center`` is the callable that resolves ``"auto"`` to
    the element's own geometry box center; without it (or without measurable
    geometry) ``"auto"`` falls back to the origin. ``rotate``'s inline
    ``[deg, cx, cy]`` keeps working and takes precedence over ``center``.
    """
    if not isinstance(tf, dict):
        return str(tf) if tf else None
    pivot = _resolve_center(tf, auto_center)
    parts: list[str] = []
    if "translate" in tf:
        t = tf["translate"]
        if not isinstance(t, (list, tuple)) or len(t) not in (1, 2):
            raise ValueError(f"translate needs [x, y], got {t!r}")
        tx = float(t[0])
        ty = float(t[1]) if len(t) == 2 else 0.0
        parts.append(f"translate({tx:g},{ty:g})")
    if "rotate" in tf:
        parts.append(_rotate_string(tf["rotate"], pivot))
    if "scale" in tf:
        parts.append(_scale_string(tf["scale"], pivot))
    return " ".join(parts) if parts else None


def compose_transforms(static: str | None, animated: str | None) -> str | None:
    """Layer an animated transform inside the element's own static transform.

    A keyframed ``transform`` describes motion *in addition to* where the
    author put the element, so the static transform stays outermost: the result
    is ``static ∘ animated`` (SVG list order), exactly what nesting a wrapper
    group would have produced.
    """
    if not animated:
        return static or None
    return f"{static} {animated}" if static else animated


def element_transform(node: ET.Element, animated: object,
                      measurer: "Measurer | None" = None) -> str | None:
    """The ``transform`` a baked node carries for this frame's animated value."""
    def auto_center():
        from nanoframes.bounds import local_bounds

        box = local_bounds(node, measurer).box
        return box.center if box is not None else None

    resolver = auto_center if _wants_auto_center(animated) else None
    return compose_transforms(node.get("transform"), transform_string(animated, resolver))


def _wants_auto_center(tf: object) -> bool:
    return isinstance(tf, dict) and tf.get("center") == "auto"


def pin_viewport(root: ET.Element, width: float, height: float) -> None:
    """Give a baked frame an explicit canvas viewport.

    ThorVG sizes a picture with no ``width``/``height``/``viewBox`` from its
    **content bounding box**. Any element the author lets leave the canvas then
    enlarges that box, the loader scales the whole drawing down to fit it, and
    the frame silently comes out shifted, shrunk, or (when the excursion is
    large) entirely empty. Pinning the viewport to the composition's canvas
    makes off-canvas geometry what it should be: clipped, nothing more.

    An author-declared ``viewBox`` is kept, so a composition that deliberately
    renders a larger coordinate system into the canvas still does.
    """
    if root.get("viewBox") is None:
        root.set("viewBox", f"0 0 {width:g} {height:g}")
    if root.get("width") is None:
        root.set("width", f"{width:g}")
    if root.get("height") is None:
        root.set("height", f"{height:g}")


def bake_tree(doc: Document, t: float, measurer: "Measurer | None" = None,
              text_handler=None) -> ET.Element:
    """The per-frame XML tree: every element's visibility, opacity, transform,
    color and text layout materialized for time ``t``, timeline stripped."""
    comp = doc.composition
    root = copy.deepcopy(doc.root)
    pin_viewport(root, comp.width, comp.height)

    # Rebuild the per-selector animation values and a selector->node index.
    targeted = evaluate(comp, t)
    final_props: dict[ET.Element, dict[str, object]] = {}
    for node in root.iter():
        node_el = _node_element(node, comp)
        visible, clip_op = effective_opacity(node_el, t)
        by_selector = {}
        for tp in targeted:
            if node_el.matches(tp.target):
                by_selector.update(tp.props)
        final_props[node] = {
            "visible": visible,
            "opacity": clip_op * float(by_selector.get("opacity", 1.0)),
            "transform": by_selector.get("transform"),
            "fill": by_selector.get("fill"),
            "stroke": by_selector.get("stroke"),
        }

    # Apply computed values back onto the tree (skip timeline <script> nodes).
    for node in list(root.iter("*")):
        props = final_props[node]
        tag = local_name(node.tag)
        if tag == "script":
            continue
        if not props["visible"]:
            node.set("display", "none")
            continue
        opacity = props["opacity"]
        if opacity < 1.0:
            node.set("opacity", f"{opacity:.4f}")
        tf = element_transform(node, props["transform"], measurer)
        if tf:
            node.set("transform", tf)
        if tag in _FILL_STROKE_TAGS:
            if props["fill"] is not None:
                node.set("fill", str(props["fill"]))
            if props["stroke"] is not None:
                node.set("stroke", str(props["stroke"]))

    # Strip all timeline scripts so ThorVG only rasters pure geometry.
    for node in [n for n in root.iter() if local_name(n.tag) == "script"]:
        if node is root:
            continue
        parent = find_parent(root, node)
        if parent is not None:
            parent.remove(node)

    # Dereference relative <image> hrefs to absolute paths so ThorVG (which loads
    # the baked SVG from a temp file) can resolve assets against the source dir.
    if doc.base_dir:
        _dereference_images(root, doc.base_dir)

    # External text rendering: each <text data-raster> is offered to the
    # callback; PNG bytes replace the node by an <image>, None keeps the
    # normal ThorVG font path (runs before autoflow, so handled texts never
    # get chip/wrap/curve treatment).
    if text_handler is not None:
        from nanoframes.rastertext import apply_text_raster
        apply_text_raster(root, text_handler)

    # Renderer-exact text auto-layout (backgrounds / wrap / along-curve).
    if measurer is not None:
        from nanoframes.textflow import apply_text_autoflow
        apply_text_autoflow(root, measurer)

    return root


def bake_svg(doc: Document, t: float, measurer: "Measurer | None" = None,
             text_handler=None) -> str:
    """``bake_tree`` serialized as a standalone SVG document string."""
    return ET.tostring(bake_tree(doc, t, measurer=measurer, text_handler=text_handler),
                       encoding="unicode")


def _dereference_images(root: ET.Element, base_dir: str) -> None:
    import os

    for node in root.iter():
        if local_name(node.tag) != "image":
            continue
        for attr in IMAGE_REF_ATTRS:
            ref = node.get(attr)
            if not ref or ref.startswith((*REMOTE_SCHEMES, "/")):
                continue
            joined = os.path.normpath(os.path.join(base_dir, ref))
            node.set(attr, joined)

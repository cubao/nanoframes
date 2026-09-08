"""Bake a per-frame SVG document from a composition + time.

Given a parsed `Document` and a time ``t``, produce a standalone SVG string in
which every element's visibility (clip + fade), animated opacity, transform and
color are materialized. The `<script>` timeline is stripped so ThorVG only ever
rasters pure geometry.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from nanoframes.model import Composition, Element
from nanoframes.parse import Document, _local, _to_float
from nanoframes.timeline import TargetedProps, effective_opacity, evaluate

# Serialize the SVG namespace unprefixed (`xmlns="..."`), which ThorVG's XML
# parser requires to resolve tag names correctly.
ET.register_namespace("", "http://www.w3.org/2000/svg")

_FILL_STROKE_TAGS = {
    "path", "rect", "circle", "ellipse", "polygon", "polyline",
    "line", "text", "tspan", "g", "use",
}


def _node_element(node: ET.Element, comp: Composition) -> Element:
    """Rebuild a lightweight Element from tree attrs (bake keeps nodes separate)."""
    d = node.get("data-duration")
    dur = _to_float(d, "data-duration") if d is not None else comp.duration
    return Element(
        element_id=node.get("id"),
        tag=_local(node.tag),
        classes=node.get("class", "").split(),
        track=_to_int(node.get("data-track-index", "0")),
        clip_start=_to_float(node.get("data-start", "0.0"), "data-start"),
        clip_duration=dur,
        fade_in=_to_float(node.get("data-fade", "0.0"), "data-fade"),
    )


def _to_int(value: str) -> int:
    return int(float(value))


def _transform_string(tf: object) -> str | None:
    if not isinstance(tf, dict):
        return str(tf) if tf else None
    parts: list[str] = []
    if "translate" in tf:
        t = tf["translate"]
        parts.append(f"translate({t[0]:g},{t[1]:g})")
    if "rotate" in tf:
        # SVG rotates around (0,0); a rotate pivot can be given as [deg,cx,cy]
        r = tf["rotate"]
        if isinstance(r, (list, tuple)) and len(r) >= 3:
            parts.append(f"rotate({r[0]:g} {r[1]:g} {r[2]:g})")
        else:
            parts.append(f"rotate({float(r):g})")
    if "scale" in tf:
        s = tf["scale"]
        parts.append(f"scale({s[0]:g},{s[1]:g})")
    return " ".join(parts) if parts else None


def bake_svg(doc: Document, t: float, measurer: "Measurer | None" = None) -> str:
    comp = doc.composition
    root = copy.deepcopy(doc.root)

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
        tag = _local(node.tag)
        if tag == "script":
            continue
        if not props["visible"]:
            node.set("display", "none")
            continue
        opacity = props["opacity"]
        if opacity < 1.0:
            node.set("opacity", f"{opacity:.4f}")
        tf = _transform_string(props["transform"])
        if tf:
            node.set("transform", tf)
        if tag in _FILL_STROKE_TAGS:
            if props["fill"] is not None:
                node.set("fill", str(props["fill"]))
            if props["stroke"] is not None:
                node.set("stroke", str(props["stroke"]))

    # Strip all timeline scripts so ThorVG only rasters pure geometry.
    for node in [n for n in root.iter() if _local(n.tag) == "script"]:
        if node is root:
            continue
        parent = _find_parent(root, node)
        if parent is not None:
            parent.remove(node)

    # Dereference relative <image> hrefs to absolute paths so ThorVG (which loads
    # the baked SVG from a temp file) can resolve assets against the source dir.
    if doc.base_dir:
        _dereference_images(root, doc.base_dir)

    # Renderer-exact text auto-layout (backgrounds / wrap / along-curve).
    if measurer is not None:
        from nanoframes.textflow import apply_text_autoflow
        apply_text_autoflow(root, measurer)

    return ET.tostring(root, encoding="unicode")


def _dereference_images(root: ET.Element, base_dir: str) -> None:
    import os

    for node in root.iter():
        if _local(node.tag) != "image":
            continue
        for attr in ("href", "{http://www.w3.org/1999/xlink}href", "src"):
            ref = node.get(attr)
            if not ref or ref.startswith(("http:", "https:", "data:", "/")):
                continue
            joined = os.path.normpath(os.path.join(base_dir, ref))
            node.set(attr, joined)


def _find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for node in root.iter():
        if child in list(node):
            return node
    return None

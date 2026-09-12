"""Shared ElementTree helpers for bake-time tree passes.

Every pass over the per-frame XML tree (animation baking, text autoflow,
external-text raster, image dereferencing) needs the same small toolkit:
namespace-qualified tags, tag-name stripping, parent lookup for tree surgery,
and strict numeric attribute reads. Keeping them here means a pass never has
to reach into another module's private helpers.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"


def qname(local: str) -> str:
    """Qualified ElementTree tag for an SVG element name."""
    return f"{{{SVG_NAMESPACE}}}{local}"


def local_name(tag: str) -> str:
    """Strip the XML namespace from a tag, e.g. '{...}rect' -> 'rect'."""
    return tag.rsplit("}", 1)[-1]


def find_parent(root: ET.Element, node: ET.Element) -> ET.Element | None:
    """Return the parent of ``node`` within ``root``'s tree, or None at the root."""
    for parent in root.iter():
        if node in list(parent):
            return parent
    return None


def float_attr(node: ET.Element, name: str, default: float = 0.0) -> float:
    """Read a numeric attribute; missing/empty -> ``default``, garbage raises."""
    raw = node.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"invalid numeric attribute {name!r}: {raw!r}") from None

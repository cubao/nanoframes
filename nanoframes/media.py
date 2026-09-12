"""Embedded media: aspect-correct placement for ``<image>`` nodes.

ThorVG ignores ``preserveAspectRatio`` and always stretches a picture to its
declared ``width``/``height`` (probed — see docs/diagram.md's gap list for the
same class of finding), so a non-square source in a square box comes out
distorted. ``data-fit`` asks for the geometry a browser would have computed, and
this module computes it: ``contain`` letterboxes inside the box, ``cover`` fills
it and clips the overflow.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from functools import lru_cache

from nanoframes import refs
from nanoframes.xmlutil import find_parent, qname

# Accepted ``data-fit`` values. ``stretch`` is ThorVG's own behaviour, so it is
# the default and a no-op.
FIT_MODES = ("stretch", "contain", "cover")

_CLIP_PREFIX = "nf-fit-"


def _file_stat(path: str):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=256)
def _intrinsic_cached(path: str, _stat):
    """Read a picture's pixel size. ``_stat`` is part of the key, not an input."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 - an unreadable source just means "no fit"
        return None


def intrinsic_size(path: str):
    """``(width, height)`` of an image file, or ``None`` when unreadable.

    Keyed on the file's size and mtime as well as its path, so an edited source
    is re-read instead of serving a stale dimension for the process's lifetime.
    """
    stat = _file_stat(path)
    if stat is None:
        return None
    return _intrinsic_cached(path, stat)


def resolve_source(node, base_dir: str | None) -> str | None:
    """The local file an ``<image>`` points at, or ``None`` for remote ones."""
    ref = refs.image_ref(node)
    if not refs.is_local(ref):
        return None
    if os.path.isabs(ref):
        return os.path.normpath(ref)
    if base_dir:
        return os.path.normpath(os.path.join(base_dir, ref))
    return None


def _declared_box(node) -> tuple | None:
    """The element's authored box ``(x, y, w, h)``, or ``None`` without one.

    ``data-fit`` needs a box to fit into: an ``<image>`` with no declared
    ``width``/``height`` is drawn at its intrinsic size and has nothing to fit.
    """
    try:
        width = float(node.get("width"))
        height = float(node.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    try:
        x = float(node.get("x")) if node.get("x") is not None else 0.0
        y = float(node.get("y")) if node.get("y") is not None else 0.0
    except (TypeError, ValueError):
        x = y = 0.0
    return x, y, width, height


def _defs(root) -> ET.Element:
    """The root's ``<defs>``, created (and placed first) when absent."""
    for child in root:
        if child.tag == qname("defs"):
            return child
    defs = ET.Element(qname("defs"))
    root.insert(0, defs)
    return defs


def _clip_to_box(root, node, clip_id: str, box) -> None:
    """Wrap ``node`` in a group clipped to ``box`` (ThorVG honors ``clip-path``)."""
    parent = find_parent(root, node)
    if parent is None:
        return
    clip = ET.Element(qname("clipPath"), {"id": clip_id})
    x, y, width, height = box
    ET.SubElement(clip, qname("rect"), {
        "x": f"{x:g}", "y": f"{y:g}", "width": f"{width:g}", "height": f"{height:g}",
    })
    _defs(root).append(clip)

    group = ET.Element(qname("g"), {"clip-path": f"url(#{clip_id})"})
    index = list(parent).index(node)
    parent.remove(node)
    group.append(node)
    parent.insert(index, group)


def apply_fit(root, base_dir: str | None) -> None:
    """Rewrite every ``<image data-fit>`` to an aspect-correct box, in place.

    ``contain`` shrinks the picture to fit inside the authored box (letterbox);
    ``cover`` grows it to fill the box and clips the overflow to the box.
    ``stretch`` (and an absent attribute) leaves the geometry exactly as
    authored, so a composition that does not opt in renders unchanged.
    """
    ordinal = 0
    for node in list(refs.iter_images(root)):
        mode = (node.get("data-fit") or "").strip().lower()
        if mode not in FIT_MODES or mode == "stretch":
            continue
        box = _declared_box(node)
        source = resolve_source(node, base_dir)
        if box is None or source is None:
            continue
        size = intrinsic_size(source)
        if size is None:
            continue
        intrinsic_w, intrinsic_h = size
        if intrinsic_w <= 0 or intrinsic_h <= 0:
            continue

        x, y, width, height = box
        fit = min if mode == "contain" else max
        scale = fit(width / intrinsic_w, height / intrinsic_h)
        drawn_w, drawn_h = intrinsic_w * scale, intrinsic_h * scale
        node.set("x", f"{x + (width - drawn_w) / 2.0:g}")
        node.set("y", f"{y + (height - drawn_h) / 2.0:g}")
        node.set("width", f"{drawn_w:g}")
        node.set("height", f"{drawn_h:g}")

        if mode == "cover":
            ordinal += 1
            clip_id = f"{_CLIP_PREFIX}{node.get('id') or 'img'}-{ordinal}"
            _clip_to_box(root, node, clip_id, box)

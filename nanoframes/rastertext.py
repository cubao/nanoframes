"""Bake-time external text rendering: swap an opted-in ``<text>`` for a PNG.

ThorVG's font story is deliberately conservative (a few load-safe faces; some
fonts crash the build), so anything exotic — LaTeX math, a brand face ThorVG
cannot load, emoji art — belongs *outside* the framework. This module gives
library callers a single hook: provide ``text_handler`` to ``bake_svg`` /
``render_frame`` and every ``<text data-raster="...">`` node is offered to it.

Contract
--------
* The handler is called once per opted-in ``<text>`` per bake with a
  ``TextRequest`` and must be a deterministic pure function of it.
* It returns PNG ``bytes`` -> the text node is replaced by an ``<image>``
  placed at an anchor-driven bbox; ``None`` (or empty) -> the node keeps the
  normal ThorVG font path untouched, including any ``data-*`` autoflow.
* Returned bytes must decode as PNG; anything else raises at bake time so a
  broken handler fails loudly in tests, never silently on screen.
* The framework holds no result cache: with a handler present,
  ``render_frame`` also bypasses ``FrameCache`` (its key knows nothing about
  the handler), so rendering N frames calls the handler N times per node —
  expensive backends should memoize internally on the request fields.

Placement
---------
``x``/``y`` become the *anchor point* of a bbox (not an SVG baseline) when the
node is rasterized. ``data-anchor`` picks which corner/edge/center of the bbox
sits at ``(x, y)``; ``data-width``/``data-height`` set a target box the PNG is
uniformly contained in (absent -> natural pixel size); ``data-yaw`` rotates
the placed image around the anchor point, degrees clockwise.
"""

from __future__ import annotations

import base64
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

from nanoframes.xmlutil import find_parent, float_attr, local_name, qname

# (vertical fraction, horizontal fraction) of the bbox that sits at (x, y).
_ANCHORS = {
    "top-left": (0.0, 0.0),
    "top-center": (0.0, 0.5),
    "top-right": (0.0, 1.0),
    "middle-left": (0.5, 0.0),
    "center": (0.5, 0.5),
    "middle-right": (0.5, 1.0),
    "bottom-left": (1.0, 0.0),
    "bottom-center": (1.0, 0.5),
    "bottom-right": (1.0, 1.0),
}


@dataclass(frozen=True)
class TextRequest:
    """Everything a custom text renderer may need to produce one PNG.

    ``attrs`` is a copy of the node's raw attributes (including all ``data-*``)
    so handlers can read their own extension attributes without a protocol bump.
    """

    text: str
    kind: str | None  # value of data-raster, for handler dispatch
    x: float
    y: float
    anchor: str
    width: float | None  # target box width in px, or None for natural size
    height: float | None
    yaw: float
    font_size: float
    family: str
    weight: str
    fill: str | None
    letter_spacing: float
    attrs: dict[str, str] = field(default_factory=dict)


TextHandler = Callable[[TextRequest], "bytes | None"]


def apply_text_raster(root: ET.Element, text_handler: TextHandler) -> None:
    """Replace every ``<text data-raster>`` the handler rasterizes with an image."""
    for node in [n for n in root.iter() if local_name(n.tag) == "text"]:
        kind = node.get("data-raster")
        if kind is None or node.get("display") == "none":
            continue
        req = _request(node, kind)
        data = text_handler(req)
        if not data:  # None / empty -> fall back to the normal font path
            continue
        _replace_with_image(root, node, req, data)


# ---------------------------------------------------------------------------
# request
# ---------------------------------------------------------------------------


def _request(node: ET.Element, kind: str) -> TextRequest:
    anchor = node.get("data-anchor", "center")
    if anchor not in _ANCHORS:
        raise ValueError(
            f"data-raster text has invalid data-anchor {anchor!r}; "
            f"expected one of {', '.join(sorted(_ANCHORS))}"
        )
    return TextRequest(
        text=node.text or "",
        kind=kind,
        x=float_attr(node, "x", 0.0),
        y=float_attr(node, "y", 0.0),
        anchor=anchor,
        width=_opt_num(node, "data-width"),
        height=_opt_num(node, "data-height"),
        yaw=float_attr(node, "data-yaw", 0.0),
        font_size=float_attr(node, "font-size", 16.0),
        family=node.get("font-family") or "Arial",
        weight=node.get("font-weight") or "normal",
        fill=node.get("fill"),
        letter_spacing=float_attr(node, "letter-spacing", 0.0),
        attrs=dict(node.attrib),
    )


def _opt_num(node: ET.Element, name: str) -> float | None:
    raw = node.get(name)
    if raw is None or raw == "":
        return None
    value = float_attr(node, name, 0.0)
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {raw!r}")
    return value


# ---------------------------------------------------------------------------
# replacement
# ---------------------------------------------------------------------------


def _replace_with_image(root: ET.Element, node: ET.Element, req: TextRequest,
                        data: bytes) -> None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as png:
            pw, ph = png.size
    except Exception as exc:
        raise ValueError(
            f"text_handler for data-raster={req.kind!r} returned non-PNG bytes"
        ) from exc
    if pw <= 0 or ph <= 0:
        raise ValueError("text_handler returned an empty PNG")

    ix, iy, iw, ih = _layout(req, pw, ph)

    parent = find_parent(root, node)
    if parent is None:
        raise RuntimeError("orphan text node during raster pass")
    g = ET.Element(qname("g"))
    for attr in ("id", "class", "opacity", "transform"):
        value = node.get(attr)
        if value:
            g.set(attr, value)

    image = ET.Element(qname("image"))
    image.set("x", f"{ix:g}")
    image.set("y", f"{iy:g}")
    image.set("width", f"{iw:g}")
    image.set("height", f"{ih:g}")
    image.set("href", "data:image/png;base64,"
                      + base64.b64encode(data).decode("ascii"))
    if req.yaw:
        image.set("transform", f"rotate({req.yaw:g} {req.x:g} {req.y:g})")
    g.append(image)

    idx = list(parent).index(node)
    parent.remove(node)
    parent.insert(idx, g)


def _layout(req: TextRequest, pw: int, ph: int) -> tuple[float, float, float, float]:
    """Image top-left + size in the bbox space.

    The bbox (target ``data-width``/``data-height``, else the image's natural
    size) is anchored at (``x``, ``y``); the contained image is aligned inside
    it by the same anchor, so both coincide whenever there is no slack.
    """
    vf, hf = _ANCHORS[req.anchor]
    if req.width is not None and req.height is not None:
        box_w, box_h = req.width, req.height
        scale = min(box_w / pw, box_h / ph)
    elif req.width is not None:
        box_w = req.width
        scale = box_w / pw
        box_h = ph * scale
    elif req.height is not None:
        box_h = req.height
        scale = box_h / ph
        box_w = pw * scale
    else:
        box_w, box_h = float(pw), float(ph)
        scale = 1.0
    iw, ih = pw * scale, ph * scale
    bx = req.x - box_w * hf
    by = req.y - box_h * vf
    return bx + (box_w - iw) * hf, by + (box_h - ih) * vf, iw, ih

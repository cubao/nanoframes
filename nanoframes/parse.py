"""Parse a `.nf.svg` composition into a `Composition` + the underlying XML tree.

Only the standard library is used; baking later reuses the retained ElementTree
root to emit per-frame SVG without re-parsing.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from nanoframes.model import (
    SVG_NAMESPACE,
    SCRIPT_TYPE,
    Animation,
    Composition,
    Element,
    Keyframe,
    qname,
)


class ParseError(ValueError):
    """Raised when a `.nf.svg` file does not satisfy the composition contract."""


@dataclass
class Document:
    """A parsed composition plus its retained XML root (for baking)."""

    composition: Composition
    root: ET.Element = field(repr=False)
    base_dir: str | None = field(default=None, repr=False)  # dir of source, for relative assets


def _to_float(value: str, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ParseError(f"invalid numeric attribute {name!r}: {value!r}")


def _to_int(value: str, name: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise ParseError(f"invalid integer attribute {name!r}: {value!r}")


def _attr(el: ET.Element, name: str, default: str | None = None) -> str | None:
    return el.get(name, default)


def _local(tag: str) -> str:
    """Strip the XML namespace from a tag, e.g. '{...}rect' -> 'rect'."""
    return tag.rsplit("}", 1)[-1]


def _collect_elements(root: ET.Element, comp_duration: float) -> list[Element]:
    """Walk the tree and gather pieces that carry rendering-relevant metadata."""
    result: list[Element] = []
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "svg":
            continue
        has_style_info = any(
            key.startswith("data-") for key in el.attrib
        )
        # Still track every element so declaration order & selectors are stable for lint,
        # but only attach timing when data-start/-duration present.
        clip_duration: float | None = None
        d = el.get("data-duration")
        if d is not None:
            clip_duration = _to_float(d, "data-duration")

        fade_in = _to_float(el.get("data-fade", "0.0"), "data-fade")
        result.append(
            Element(
                element_id=el.get("id"),
                tag=tag,
                classes=el.get("class", "").split(),
                track=_to_int(el.get("data-track-index", "0"), "data-track-index"),
                clip_start=_to_float(el.get("data-start", "0.0"), "data-start"),
                clip_duration=clip_duration,
                fade_in=fade_in,
                fade_out=0.0,
            )
        )
    return result


def _parse_animations(root: ET.Element) -> list[Animation]:
    animations: list[Animation] = []
    for el in root.iter():
        if _local(el.tag) != "script":
            continue
        if (el.get("type") or "") != SCRIPT_TYPE:
            continue
        if not el.text:
            continue
        try:
            payload = json.loads(el.text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid nanoframes timeline JSON: {exc}") from exc

        for raw in payload.get("animations", []):
            if not isinstance(raw, dict):
                raise ParseError("each animation entry must be an object")
            raw_keyframes = raw.get("keyframes") or []
            keyframes = []
            for kf in raw_keyframes:
                if not isinstance(kf, dict) or "t" not in kf:
                    raise ParseError("each keyframe must be an object with a 't' field")
                props = {k: v for k, v in kf.items() if k not in ("t", "ease")}
                keyframes.append(
                    Keyframe(t=_to_float(str(kf["t"]), "keyframe.t"), props=props,
                             ease=str(kf.get("ease", "linear")))
                )
            animations.append(
                Animation(target=str(raw.get("target", "")), keyframes=keyframes)
            )
    return animations


def _parse_root(root: ET.Element) -> tuple[int, int, int, float, str | None]:
    if _local(root.tag) != "svg":
        raise ParseError("composition root must be an <svg> element")
    width = _to_int(root.get("data-width", root.get("width", "0")), "width")
    height = _to_int(root.get("data-height", root.get("height", "0")), "height")
    if width <= 0 or height <= 0:
        raise ParseError(f"composition must define positive width/height, got {width}x{height}")
    fps = _to_int(root.get("data-fps", "30"), "data-fps")
    duration = _to_float(root.get("data-duration", "1.0"), "data-duration")
    if duration <= 0:
        raise ParseError("composition duration must be positive")
    return width, height, fps, duration, root.get("data-composition-id")


def parse_file(path: str) -> Document:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ParseError(f"could not parse XML in {path!r}: {exc}") from exc
    doc = _parse_tree(tree.getroot())
    doc.base_dir = os.path.dirname(os.path.abspath(path))
    return doc


def parse_string(text: str) -> Document:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ParseError(f"could not parse XML: {exc}") from exc
    return _parse_tree(root)


def _parse_tree(root: ET.Element) -> Document:
    width, height, fps, duration, cid = _parse_root(root)
    comp = Composition(
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        composition_id=cid,
        elements=_collect_elements(root, duration),
        animations=_parse_animations(root),
    )
    # Resolve clip_duration=None -> composition duration at the model level.
    for el in comp.elements:
        if el.clip_duration is None:
            el.clip_duration = comp.duration
    return Document(composition=comp, root=root)
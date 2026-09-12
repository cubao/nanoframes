"""Parse a `.nf.svg` composition into a `Composition` + the underlying XML tree.

Only the standard library is used; baking later reuses the retained ElementTree
root to emit per-frame SVG without re-parsing.
"""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from nanoframes.model import SCRIPT_TYPE, Animation, Composition, Element, Keyframe
from nanoframes.xmlutil import local_name


class ParseError(ValueError):
    """Raised when a `.nf.svg` file does not satisfy the composition contract."""


@dataclass
class Document:
    """A parsed composition plus its retained XML root (for baking)."""

    composition: Composition
    root: ET.Element = field(repr=False)
    base_dir: str | None = field(default=None, repr=False)  # dir of source, for relative assets
    source_key: str = field(default="", repr=False)

    @property
    def identity(self) -> str:
        """A stable identifier unique to this composition's source content."""
        if self.source_key:
            return self.source_key
        return _hash_text(ET.tostring(self.root, encoding="unicode"))


def _to_float(value: str, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ParseError(f"invalid numeric attribute {name!r}: {value!r}") from exc


def _to_int(value: str, name: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ParseError(f"invalid integer attribute {name!r}: {value!r}") from exc


def _collect_elements(root: ET.Element) -> list[Element]:
    """Walk the tree and gather pieces that carry rendering-relevant metadata.

    Every element is tracked so declaration order & selectors are stable for
    lint, but timing is only attached from the ``data-*`` attributes present.
    """
    result: list[Element] = []
    for el in root.iter():
        tag = local_name(el.tag)
        if tag == "svg":
            continue
        clip_duration: float | None = None
        d = el.get("data-duration")
        if d is not None:
            clip_duration = _to_float(d, "data-duration")

        fade = _to_float(el.get("data-fade", "0.0"), "data-fade")
        result.append(
            Element(
                element_id=el.get("id"),
                tag=tag,
                classes=el.get("class", "").split(),
                clip_start=_to_float(el.get("data-start", "0.0"), "data-start"),
                clip_duration=clip_duration,
                fade_in=fade,
                fade_out=fade,  # data-fade mirrors at the clip end
            )
        )
    return result


def _parse_animations(root: ET.Element) -> list[Animation]:
    animations: list[Animation] = []
    for el in root.iter():
        if local_name(el.tag) != "script":
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
    if local_name(root.tag) != "svg":
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


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_file(path: str) -> Document:
    raw = open(path, "rb").read().decode("utf-8")
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParseError(f"could not parse XML in {path!r}: {exc}") from exc
    doc = _parse_tree(tree)
    doc.base_dir = os.path.dirname(os.path.abspath(path))
    doc.source_key = _hash_text(raw)
    return doc


def parse_string(text: str) -> Document:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ParseError(f"could not parse XML: {exc}") from exc
    doc = _parse_tree(root)
    doc.source_key = _hash_text(text)
    return doc


def _parse_tree(root: ET.Element) -> Document:
    width, height, fps, duration, cid = _parse_root(root)
    comp = Composition(
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        composition_id=cid,
        elements=_collect_elements(root),
        animations=_parse_animations(root),
    )
    # Resolve clip_duration=None -> composition duration at the model level.
    for el in comp.elements:
        if el.clip_duration is None:
            el.clip_duration = comp.duration
    return Document(composition=comp, root=root)

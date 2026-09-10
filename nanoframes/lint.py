"""Lint the nanoframes composition contract.

`lint` returns findings (errors/warnings) about a parsed composition: canvas
metadata sanity, animation targets resolving, keyframe timing in range, clip
windows within the composition duration, and referenced image assets existing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from nanoframes.model import Composition
from nanoframes.parse import Document, ParseError, parse_file, parse_string
from nanoframes.xmlutil import local_name

_IMAGE_REFS = ("href", "{http://www.w3.org/1999/xlink}href", "src")
_NON_LOCAL = ("http:", "https:", "data:")


@dataclass
class Finding:
    severity: str  # "error" | "warning"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.message}"


def _check_canvas(comp: Composition, findings: list[Finding]) -> None:
    if not comp.width > 0 or not comp.height > 0:
        findings.append(Finding("error", "canvas must have positive width and height"))
    if comp.fps <= 0:
        findings.append(Finding("error", "fps must be positive"))
    if comp.duration <= 0:
        findings.append(Finding("error", "duration must be positive"))


def _check_animations(comp: Composition, findings: list[Finding]) -> None:
    for anim in comp.animations:
        if not anim.target:
            findings.append(Finding("error", "animation has an empty target selector"))
            continue
        if not any(el.matches(anim.target) for el in comp.elements):
            findings.append(
                Finding("error", f"animation target {anim.target!r} matches no elements")
            )
        for kf in anim.keyframes:
            if kf.t < 0 or kf.t > comp.duration + 1e-9:
                findings.append(
                    Finding(
                        "warning",
                        f"{anim.target}: keyframe t={kf.t} outside duration {comp.duration}",
                    )
                )


def _check_clips(comp: Composition, findings: list[Finding]) -> None:
    for el in comp.elements:
        clip_end = el.clip_start + (el.clip_duration or comp.duration)
        if el.clip_start < -1e-9 or clip_end > comp.duration + 1e-9:
            findings.append(
                Finding(
                    "warning",
                    f"element {el.element_id or el.tag!r}: clip [{el.clip_start}, {clip_end}]"
                    f" exceeds composition duration {comp.duration}",
                )
            )
        if el.fade_in + el.fade_out > (el.clip_duration or comp.duration):
            findings.append(
                Finding(
                    "warning",
                    f"element {el.element_id or el.tag!r}: fade in+out exceeds clip duration",
                )
            )


def _check_assets(doc: Document, findings: list[Finding]) -> None:
    """Warn when an ``<image>`` points at a file that is not there.

    ThorVG loads the SVG happily and simply draws nothing, so a moved asset
    silently renders an empty layer in every frame. Only file-backed
    compositions are checked: a string-parsed document has no directory to
    resolve relative paths against.
    """
    if doc.base_dir is None:
        return
    seen: set[str] = set()
    for node in doc.root.iter():
        if local_name(node.tag) != "image":
            continue
        for attr in _IMAGE_REFS:
            ref = node.get(attr)
            if not ref or ref.startswith(_NON_LOCAL) or ref in seen:
                continue
            seen.add(ref)
            path = ref if os.path.isabs(ref) else os.path.join(doc.base_dir, ref)
            if not os.path.exists(os.path.normpath(path)):
                findings.append(
                    Finding(
                        "warning",
                        f"element {node.get('id') or '<image>'}: asset not found: {ref}"
                        " (renders as an empty layer)",
                    )
                )


def lint_document(doc: Document) -> list[Finding]:
    findings: list[Finding] = []
    _check_canvas(doc.composition, findings)
    _check_animations(doc.composition, findings)
    _check_clips(doc.composition, findings)
    _check_assets(doc, findings)
    return findings


def lint_path(path: str) -> list[Finding]:
    try:
        doc = parse_file(path)
    except ParseError as exc:
        return [Finding("error", f"parse failed: {exc}")]
    return lint_document(doc)


def lint_string(text: str) -> list[Finding]:
    try:
        doc = parse_string(text)
    except ParseError as exc:
        return [Finding("error", f"parse failed: {exc}")]
    return lint_document(doc)


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == "error" for f in findings)
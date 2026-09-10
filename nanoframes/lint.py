"""Lint the nanoframes composition contract.

`lint` returns findings (errors/warnings) about a parsed composition: canvas
metadata sanity, animation targets resolving, keyframe timing in range, clip
windows within the composition duration, referenced image assets existing, and
the geometry traps that render as *nothing* — an element that never lands on
the canvas, and a ``rotate`` whose missing pivot swings it away from where it
was authored (SVG rotates around ``(0,0)``).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from nanoframes import bake, bounds, timeline
from nanoframes.model import Composition, Element
from nanoframes.parse import Document, ParseError, parse_file, parse_string
from nanoframes.xmlutil import local_name

_IMAGE_REFS = ("href", "{http://www.w3.org/1999/xlink}href", "src")
_NON_LOCAL = ("http:", "https:", "data:")

# Cap on the frames a geometry sample walks: a long composition is sampled
# evenly rather than visited frame by frame (the traps being hunted persist
# across frames, so even sampling finds them).
_MAX_SAMPLES = 24

# Sentinel for "measure text if this composition has any" (see lint_document).
AUTO = object()


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
        forms = {_transform_shape(kf.props.get("transform")) for kf in anim.keyframes}
        forms.discard(None)
        if len(forms) > 1:
            findings.append(Finding(
                "warning",
                f"{anim.target}: transform is written in more than one shape across keyframes"
                f" ({', '.join(sorted(forms))}); the interpolator can only blend matching"
                " shapes and holds the earlier value otherwise",
            ))


def _transform_shape(tf: object) -> str | None:
    """How a keyframe writes ``rotate``/``scale``: degrees, [deg,cx,cy], pair, scalar…"""
    if not isinstance(tf, dict):
        return None
    shapes = []
    if "rotate" in tf:
        rotate = tf["rotate"]
        if isinstance(rotate, dict):
            shapes.append("rotate-object")
        elif isinstance(rotate, (list, tuple)):
            shapes.append("rotate-pivot-list" if len(rotate) >= 3 else "rotate-list")
        else:
            shapes.append("rotate-degrees")
    scale = tf.get("scale")
    if scale is not None:
        if isinstance(scale, (list, tuple)):
            shapes.append(f"scale-{len(scale)}-list")
        else:
            shapes.append("scale-scalar")
    return "+".join(shapes) if shapes else None


def _check_transform_values(comp: Composition, findings: list[Finding]) -> None:
    """Reject transform values bake cannot express, before a render fails on them."""
    for anim in comp.animations:
        for kf in anim.sorted:
            tf = kf.props.get("transform")
            if not isinstance(tf, dict):
                continue
            for problem in _transform_problems(tf):
                findings.append(Finding("error", f"{anim.target} (t={kf.t:g}): {problem}"))


def _transform_problems(tf: dict) -> list[str]:
    problems: list[str] = []
    rotate = tf.get("rotate")
    if isinstance(rotate, dict) or (isinstance(rotate, (list, tuple)) and len(rotate) != 3):
        problems.append(
            "rotate takes degrees or [deg, cx, cy] — for a pivot that follows the element"
            ' put "center": "auto" next to it'
        )
    translate = tf.get("translate")
    if translate is not None and not (
        isinstance(translate, (list, tuple)) and len(translate) in (1, 2)
    ):
        problems.append(f"translate takes [x, y], got {translate!r}")
    if "scale" in tf:
        scale = tf["scale"]
        if isinstance(scale, bool) or not isinstance(scale, (int, float, list, tuple)) \
                or (isinstance(scale, (list, tuple)) and not 1 <= len(scale) <= 2):
            problems.append(f"scale takes [sx, sy] or a number, got {scale!r}")
    center = tf.get("center")
    if center is not None and not (
        (isinstance(center, str) and center == "auto")
        or (isinstance(center, (list, tuple)) and len(center) == 2)
    ):
        problems.append(f'center takes "auto" or [cx, cy], got {center!r}')
    return problems


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


def lint_document(doc: Document, measurer=AUTO) -> list[Finding]:
    """All findings for a parsed composition.

    ``measurer`` defaults to ``AUTO``: text is measured (which loads ThorVG)
    only when the composition actually has ``<text>`` to measure. Pass ``None``
    to skip text measurement entirely, or a ``Measurer`` to share one.
    """
    if measurer is AUTO:
        measurer = default_measurer() if _has_text(doc) else None
    findings: list[Finding] = []
    _check_canvas(doc.composition, findings)
    _check_animations(doc.composition, findings)
    _check_transform_values(doc.composition, findings)
    _check_clips(doc.composition, findings)
    _check_assets(doc, findings)
    if has_errors(findings):
        # Bake would raise on the transform values just reported: stop before the
        # geometry checks rather than crashing the whole lint pass.
        return findings
    _check_rotate_pivots(doc, measurer, findings)
    _check_visibility(doc, measurer, findings)
    return findings


def lint_path(path: str, measurer=AUTO) -> list[Finding]:
    try:
        doc = parse_file(path)
    except ParseError as exc:
        return [Finding("error", f"parse failed: {exc}")]
    return lint_document(doc, measurer)


def lint_string(text: str, measurer=AUTO) -> list[Finding]:
    try:
        doc = parse_string(text)
    except ParseError as exc:
        return [Finding("error", f"parse failed: {exc}")]
    return lint_document(doc, measurer)


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == "error" for f in findings)


# ---------------------------------------------------------------------------
# Geometry traps: the failures that render as *nothing*
# ---------------------------------------------------------------------------

# Sub-pixel slack so geometry authored exactly at the canvas edge is not
# reported as leaving it.
_EDGE_SLACK = 0.5

# One process-wide measurer: text boxes are cached by content, so a lint pass
# over a composition with many text nodes pays for each distinct string once.
_MEASURER: list = [None]


def default_measurer():
    """A ThorVG-backed measurer for text boxes, or None if unavailable.

    ``lint`` reaches for it lazily: measuring text is the only reason `check`
    needs the engine, and a composition without text should not pay for the
    import. Any failure (no engine, unloadable font) degrades to unmeasured
    text, which is skipped rather than guessed at.
    """
    try:
        from nanoframes.measure import Measurer

        _MEASURER[0] = _MEASURER[0] or Measurer()
        return _MEASURER[0]
    except Exception:  # noqa: BLE001 - measurement is optional for linting
        return None


def _renderable(node) -> bool:
    return local_name(node.tag) not in bounds.NON_RENDERING_TAGS


def _has_text(doc: Document) -> bool:
    """Whether a composition has text to measure (the only reason lint loads ThorVG)."""
    return any(local_name(node.tag) == "text" for node in doc.root.iter())


def _check_rotate_pivots(doc: Document, measurer, findings: list[Finding]) -> None:
    """Warn where a pivotless ``rotate``/``scale`` swings the element away.

    ``rotate(deg)`` and ``scale(sx,sy)`` are SVG's own shorthands for turning and
    growing around ``(0,0)`` — fine for geometry authored around the origin,
    wrong for anything else, and the result usually ends up off-canvas (where it
    renders as nothing). An element already pivoting on its own origin is left
    alone, and so is a keyframe that says ``"center"``.
    """
    for anim in doc.composition.animations:
        reported: set = set()
        for kf in anim.sorted:
            tf = kf.props.get("transform")
            if not isinstance(tf, dict) or "center" in tf:
                continue
            rotate = tf.get("rotate")
            if isinstance(rotate, (list, tuple)) and len(rotate) >= 3:
                continue  # inline pivot
            operation = "rotate" if "rotate" in tf else ("scale" if "scale" in tf else None)
            if operation is None:
                continue
            for node in _matching_nodes(doc, anim.target):
                key = (operation, node.get("id"), bounds.label(node))
                if key in reported:
                    continue  # one finding per animation per element
                box = bounds.local_bounds(node, measurer).box
                if box is None or box.contains_point(0.0, 0.0):
                    continue
                cx, cy = box.center
                distance = math.hypot(cx, cy)
                if distance <= box.diagonal / 2.0:
                    continue  # origin is inside the element's own footprint
                reported.add(key)
                findings.append(Finding(
                    "warning",
                    f"{bounds.label(node)}: {operation} has no pivot, so it happens around"
                    f" the origin (0,0) — {distance:.0f}px from this element's center"
                    f' at ({cx:.0f},{cy:.0f}); add "center": "auto" to follow the element'
                    f" (or \"center\": [cx, cy] / an inline [deg, cx, cy] for rotate).",
                ))
                break


def _matching_nodes(doc: Document, selector: str) -> list:
    """Nodes a timeline selector hits (same match rules as the timeline)."""
    out = []
    for node in doc.root.iter():
        if local_name(node.tag) == "svg":
            continue
        if _as_element(node).matches(selector):
            out.append(node)
    return out


def _as_element(node) -> Element:
    return Element(element_id=node.get("id"), tag=local_name(node.tag),
                   classes=node.get("class", "").split())


def _check_visibility(doc: Document, measurer, findings: list[Finding]) -> None:
    """Warn about elements whose geometry never lands on the canvas.

    The frame pins its viewport, so geometry that leaves the canvas is clipped
    and harmless — but geometry that *never* lands on it draws nothing at all,
    in every frame, with no other symptom. Only a complete measurement can
    prove that, so partially-measured subtrees (arc paths, unresolved text) are
    skipped rather than guessed at.
    """
    comp = doc.composition
    canvas = _slack(bounds.canvas_box(comp.width, comp.height))
    samples: dict[tuple, list] = {}
    labels: dict[tuple, str] = {}
    for t in timeline.sample_times(comp, cap=_MAX_SAMPLES):
        for path, node, ancestors in bounds.iter_renderable(bake.bake_tree(doc, t, measurer=measurer)):
            measured = bounds.painted_bounds(node, measurer)
            box = measured.box.transform(ancestors) if measured.box is not None else None
            samples.setdefault(path, []).append((box, measured.complete))
            # Label from the baked node: auto-layout can insert nodes, so a
            # source-tree path is not guaranteed to name the same element.
            labels.setdefault(path, bounds.label(node))

    offenders: dict[tuple, bounds.Box] = {}
    for path, seen in samples.items():
        painted = [box for box, _ in seen if box is not None]
        if not painted:
            continue  # hidden by its clip window in every sampled frame
        if not all(complete for _, complete in seen):
            continue  # unmeasurable geometry: say nothing rather than guess
        if any(box.intersects(canvas) for box in painted):
            continue  # lands on the canvas at least once
        offenders[path] = painted[0]

    # Report the deepest offender in each chain: when a group never lands, its
    # children never do either, and one finding is enough.
    for path, box in offenders.items():
        if any(other != path and path[:len(other)] == other for other in offenders):
            continue
        findings.append(Finding(
            "warning",
            f"{labels[path]}: geometry never lands on the {comp.width}x{comp.height}"
            f" canvas (box [{box.x0:.0f},{box.y0:.0f},{box.x1:.0f},{box.y1:.0f}] in"
            f" root coordinates) — it draws nothing in any frame;"
            f" run `nanoframes debug` to see per-frame boxes.",
        ))


def _slack(canvas: bounds.Box) -> bounds.Box:
    return bounds.Box(canvas.x0 - _EDGE_SLACK, canvas.y0 - _EDGE_SLACK,
                      canvas.x1 + _EDGE_SLACK, canvas.y1 + _EDGE_SLACK)
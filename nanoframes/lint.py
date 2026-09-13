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

from nanoframes import bake, bounds, media, refs, timeline
from nanoframes.model import Composition, Element
from nanoframes.parse import Document, ParseError, parse_file, parse_string
from nanoframes.xmlutil import local_name

# Cap on the frames a geometry sample walks: a long composition is sampled
# evenly rather than visited frame by frame (the traps being hunted persist
# across frames, so even sampling finds them).
_MAX_SAMPLES = 24

# How deep `check` follows nested compositions before it stops (and says so) —
# also the recursion guard for a composition that embeds itself.
_MAX_NESTED_DEPTH = 4

# Sentinel for "measure text if this composition has any" (see lint_document).
AUTO = object()


@dataclass
class Finding:
    severity: str  # "error" | "warning"
    message: str
    code: str = ""  # stable machine identifier, e.g. "geometry.never_on_canvas"
    element: str | None = None  # what the finding is about, when it names one
    t: float | None = None  # the time it applies to, when it is time-specific

    def __str__(self) -> str:
        return f"[{self.severity}] {self.message}"

    def to_dict(self) -> dict:
        """Machine-readable form (``check --json``).

        ``code`` is the stable field: an agent branches on it, never on the
        prose of ``message``, which is free to change.
        """
        out: dict = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.element:
            out["element"] = self.element
        if self.t is not None:
            out["t"] = self.t
        return out


def _check_canvas(comp: Composition, findings: list[Finding]) -> None:
    if not comp.width > 0 or not comp.height > 0:
        findings.append(Finding("error", "canvas must have positive width and height",
                                code="canvas.invalid"))
    if comp.fps <= 0:
        findings.append(Finding("error", "fps must be positive", code="canvas.fps"))
    if comp.duration <= 0:
        findings.append(Finding("error", "duration must be positive", code="canvas.duration"))


def _check_animations(comp: Composition, findings: list[Finding]) -> None:
    for anim in comp.animations:
        if not anim.target:
            findings.append(Finding("error", "animation has an empty target selector",
                                    code="animation.empty_target"))
            continue
        if not any(el.matches(anim.target) for el in comp.elements):
            findings.append(
                Finding("error", f"animation target {anim.target!r} matches no elements",
                        code="animation.target_unmatched", element=anim.target)
            )
        for kf in anim.keyframes:
            if kf.t < 0 or kf.t > comp.duration + 1e-9:
                findings.append(
                    Finding(
                        "warning",
                        f"{anim.target}: keyframe t={kf.t} outside duration {comp.duration}",
                        code="animation.keyframe_out_of_range", element=anim.target, t=kf.t,
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
                code="animation.transform_shape_mixed", element=anim.target,
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
                findings.append(Finding("error", f"{anim.target} (t={kf.t:g}): {problem}",
                                        code="transform.value_invalid", element=anim.target,
                                        t=kf.t))


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
                    code="clip.exceeds_duration", element=el.element_id or el.tag,
                )
            )
        if el.fade_in + el.fade_out > (el.clip_duration or comp.duration):
            findings.append(
                Finding(
                    "warning",
                    f"element {el.element_id or el.tag!r}: fade in+out exceeds clip duration",
                    code="clip.fade_exceeds", element=el.element_id or el.tag,
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
    for node in refs.iter_images(doc.root):
        ref = refs.image_ref(node)
        if not refs.is_local(ref) or ref in seen:
            continue
        seen.add(ref)
        path = ref if os.path.isabs(ref) else os.path.join(doc.base_dir, ref)
        if not os.path.exists(os.path.normpath(path)):
            findings.append(
                Finding(
                    "warning",
                    f"element {node.get('id') or '<image>'}: asset not found: {ref}"
                    " (renders as an empty layer)",
                    code="asset.missing", element=node.get("id") or "<image>",
                )
            )


def lint_document(doc: Document, measurer=AUTO, _depth: int = 0) -> list[Finding]:
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
    _check_animation_windows(doc, findings)
    _check_transform_values(doc.composition, findings)
    _check_clips(doc.composition, findings)
    _check_assets(doc, findings)
    _check_image_aspect(doc, findings)
    _check_inert_attributes(doc, findings)
    _check_inert_tspan(doc, findings)
    _check_font_family(doc, findings)
    _check_media(doc, findings)
    _check_palette(doc, findings)
    _check_nested(doc, measurer, findings, _depth)
    if has_errors(findings):
        # Bake would raise on the transform values just reported: stop before the
        # geometry checks rather than crashing the whole lint pass.
        return findings
    _check_rotate_pivots(doc, measurer, findings)
    _check_visibility(doc, measurer, findings)
    _check_safe_margin(doc, measurer, findings)
    return findings


def payload(findings: list[Finding]) -> dict:
    """The ``check --json`` object: one ``ok`` and the findings behind it.

    Also the ``check`` section of ``verify``, embedded verbatim — which is why
    it lives here rather than in the CLI. A section re-shaped for an envelope
    would be a second implementation of the same verdict, and the second one is
    the one nobody tests.
    """
    errors = sum(1 for f in findings if f.severity == "error")
    return {
        "ok": errors == 0,
        "errors": errors,
        "warnings": len(findings) - errors,
        "findings": [f.to_dict() for f in findings],
    }


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
                    code="transform.no_pivot", element=bounds.label(node),
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


def _sampled_boxes(doc: Document, measurer) -> dict:
    """Every element's placed geometry across the sampled frames.

    Returns ``{path: {"label", "tag", "samples": [(box_or_None, complete)]}}`` —
    one sample per sampled frame, the box ``None`` where the element is not
    painted. One shared walk serves the visibility, safe-margin and any future
    geometry check, so none of them pays for a second bake pass.
    """
    comp = doc.composition
    entries: dict[tuple, dict] = {}
    for t in timeline.sample_times(comp, cap=_MAX_SAMPLES):
        for path, node, ancestors in bounds.iter_renderable(bake.bake_tree(doc, t, measurer=measurer)):
            painted, box, complete = bounds.placed(node, ancestors, measurer)
            entry = entries.get(path)
            if entry is None:
                # Label from the baked node: auto-layout can insert nodes, so a
                # source-tree path is not guaranteed to name the same element.
                entry = entries[path] = {
                    "label": bounds.label(node),
                    "tag": local_name(node.tag),
                    "samples": [],
                }
            entry["samples"].append((box if painted else None, complete))
    return entries


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
    entries = _sampled_boxes(doc, measurer)

    offenders: dict[tuple, bounds.Box] = {}
    for path, entry in entries.items():
        seen = entry["samples"]
        placed_boxes = [box for box, _ in seen if box is not None]
        if not placed_boxes:
            continue  # hidden by its clip window in every sampled frame
        if not all(complete for _, complete in seen):
            continue  # unmeasurable geometry: say nothing rather than guess
        if any(box.intersects(canvas) for box in placed_boxes):
            continue  # lands on the canvas at least once
        offenders[path] = placed_boxes[0]

    # Report the deepest offender in each chain: when a group never lands, its
    # children never do either, and one finding is enough.
    for path, box in offenders.items():
        if any(other != path and path[:len(other)] == other for other in offenders):
            continue
        findings.append(Finding(
            "warning",
            f"{entries[path]['label']}: geometry never lands on the {comp.width}x{comp.height}"
            f" canvas (box [{box.x0:.0f},{box.y0:.0f},{box.x1:.0f},{box.y1:.0f}] in"
            f" root coordinates) — it draws nothing in any frame;"
            f" run `nanoframes debug` to see per-frame boxes.",
            code="geometry.never_on_canvas", element=entries[path]["label"],
        ))


def _check_animation_windows(doc: Document, findings: list[Finding]) -> None:
    """Warn when an animation runs entirely outside its element's visible window.

    An element that appears after its animation finished — or is already gone
    before it starts — renders the held keyframe value and never shows the
    motion the author wrote. Pure model arithmetic: no bake, no render.
    """
    comp = doc.composition
    for anim in comp.animations:
        if not anim.keyframes:
            continue
        matched = [el for el in comp.elements if el.matches(anim.target)]
        if not matched:
            continue  # an unmatched target is already reported
        times = [kf.t for kf in anim.keyframes]
        first, last = min(times), max(times)
        for el in matched:
            start = el.clip_start
            end = el.clip_start + (el.clip_duration or comp.duration)
            if last < start - 1e-9 or first > end + 1e-9:
                findings.append(Finding(
                    "warning",
                    f"{anim.target}: the animation runs over [{first:g}, {last:g}]s but"
                    f" {el.element_id or el.tag!r} is only visible over [{start:g}, {end:g}]s"
                    f" — the motion is never seen",
                    code="animation.outside_visibility", element=anim.target,
                ))
                break


def _check_image_aspect(doc: Document, findings: list[Finding]) -> None:
    """Warn about a ``data-aspect`` value the renderer does not implement.

    An unknown mode is silently ignored by ``media.apply_aspect`` (the geometry is
    left exactly as authored), which is the right runtime behaviour and a
    confusing authoring experience — so `check` names the typo.
    """
    for node in refs.iter_images(doc.root):
        raw = node.get("data-aspect")
        if raw is None or raw == "" or raw.strip().lower() in media.ASPECT_MODES:
            continue
        findings.append(Finding(
            "warning",
            f"element {node.get('id') or '<image>'}: unknown data-aspect {raw!r}"
            f" (expected one of {', '.join(media.ASPECT_MODES)}) — geometry left as authored",
            code="image.bad_aspect", element=node.get("id") or "<image>",
        ))


def _check_inert_attributes(doc: Document, findings: list[Finding]) -> None:
    """Warn about attributes this ThorVG build accepts and ignores.

    Probed rather than assumed: ``visibility="hidden"`` on an element leaves the
    element in the picture. An author who wrote it has said something about the
    frame that the renderer does not do, and gets a wrong picture with no error
    — the exact failure mode `check` exists to catch. ``display="none"`` is what
    hides, and it is honoured.
    """
    for node in doc.root.iter():
        raw = node.get("visibility")
        if raw is None or raw.strip().lower() == "visible":
            continue
        findings.append(Finding(
            "warning",
            f"element {node.get('id') or local_name(node.tag)}: visibility={raw!r} is"
            f" ignored by ThorVG — the element is drawn anyway; use display=\"none\"",
            code="render.inert_attribute",
            element=node.get("id") or local_name(node.tag),
        ))


_SPAN_TIMING_ATTRS = ("data-start", "data-duration", "data-fade")


def _check_inert_tspan(doc: Document, findings: list[Finding]) -> None:
    """Warn about a ``<tspan>`` whose window, fade or animation cannot take effect.

    Probed rather than assumed, and the probe came back wider than the motion
    model: this loader draws a ``<text>`` as a **single unit**, and every
    attribute on the spans inside it is inert — a span's own ``fill``,
    ``font-size``, ``font-weight``, ``stroke``, ``x``/``dy``, ``opacity`` and
    ``display`` all render exactly as if unwritten, at every opacity (ink count
    unchanged, colour unchanged). bake reaches for the same two attributes to
    express timing — ``display="none"`` for a clip window, ``opacity`` for
    ``data-fade`` — so a windowed or faded span is drawn as if neither were
    written, and every keyframed property routed to one is dropped.

    Unlike ``visibility`` there is no rewrite: bake fixes ``<text>``/``<image>``
    by moving the attribute onto a ``<g>``, and a ``<g>`` inside ``<text>``
    makes this loader drop the whole text (measured: zero ink). So `check` names
    it, and the author either moves the timing to the ``<text>`` — which hides
    every sibling span too — or drops the span.

    A span whose declared window is the whole timeline is left alone: it asked
    for nothing the renderer could fail to do.
    """
    for node in doc.root.iter():
        if local_name(node.tag) != "tspan":
            continue
        declared = _span_timing(doc.composition, node)
        if declared is None:
            continue
        findings.append(Finding(
            "warning",
            f"{bounds.label(node)}: {declared} on a <tspan> has no effect — this renderer"
            f" draws a <text> as one unit and ignores every attribute on the spans inside"
            f" it, so the span is drawn as if none of it were written; put the timing on"
            f" the <text> (which then hides its other spans too) or drop the span.",
            code="render.inert_tspan", element=bounds.label(node),
        ))
    for anim in doc.composition.animations:
        for node in _matching_nodes(doc, anim.target):
            if local_name(node.tag) != "tspan":
                continue
            findings.append(Finding(
                "warning",
                f"{anim.target}: this animation targets a <tspan> — every keyframed"
                f" property is written onto the span and ignored, because this renderer"
                f" draws a <text> as one unit, so the span holds its starting value for"
                f" the whole composition; animate the <text> instead.",
                code="render.inert_tspan", element=bounds.label(node),
            ))
            break  # one finding per animation, however many spans it matches


_FONT_NAMES: list | None = None


def loaded_font_names() -> tuple[set[str], str | None]:
    """``(names that resolve, the face an unresolved family falls back to)``.

    The names are the ones a ``font-family`` value has to equal **exactly** to
    select a face, and they are built from the candidates the renderer actually
    loads (``fonts.DEFAULT_FONT_CANDIDATES``, skipping the ones not on this
    host): a face's family, plus ``family style`` when it is not the regular
    one, because that is how the loader names the styled face (measured: with
    ``Arial.ttf`` and ``Arial Bold.ttf`` both loaded, ``Arial`` resolves to the
    regular and ``Arial Bold`` to the bold).

    The fallback is the **first** candidate that exists — the one the renderer
    hands a family it could not resolve. Its name is read off the file rather
    than written into a message, because which face is first is a property of
    ``font_candidates``, not of this check.

    Memoised: it opens each candidate once per process, and the answer cannot
    change while one runs.
    """
    global _FONT_NAMES
    if _FONT_NAMES is None:
        from nanoframes.fonts import DEFAULT_FONT_CANDIDATES, family_name

        names: set[str] = set()
        fallback: str | None = None
        for path in DEFAULT_FONT_CANDIDATES:
            if not os.path.exists(path):
                continue
            family, style = family_name(path)
            if not family:
                continue
            styled = f"{family} {style}" if style and style.lower() != "regular" else family
            if fallback is None:
                fallback = styled
            names.add(family)
            names.add(styled)
        _FONT_NAMES = [names, fallback]
    return _FONT_NAMES[0], _FONT_NAMES[1]


def _check_font_family(doc: Document, findings: list[Finding]) -> None:
    """Warn about a ``font-family`` value that cannot select any loaded face.

    ThorVG's SVG loader matches the **whole value** against the names of the
    faces it has loaded: there is no CSS list semantics, no per-glyph fallback
    chain and no quoting, and the comparison is case-sensitive (measured on
    thorvg-python 1.1.3 — ``Arial`` and ``Arial Bold`` resolve to their faces
    while ``arial``, ``'Arial'`` and ``Arial, sans-serif`` all render with the
    bundled Sarasa face; surrounding whitespace is trimmed, so ``" Arial"``
    still resolves).

    That makes the corpus's portable-looking CSS stacks
    (``Arial, 'DejaVu Sans', sans-serif``) inert, and *silently* so: the
    author reads Arial and gets Sarasa, which is a wrong picture with no error —
    the failure mode `check` exists to catch. This is the same shape as
    ``render.inert_attribute``, and like it the warning only reports; the fix is
    to name one loaded face exactly.

    Checked on ``<text>`` only, because that is the element whose glyphs the
    value decides. A ``font-family`` on a ``<g>`` does not reach the text inside
    it either, but that is a separate rule and is documented, not warned about.
    """
    names, fallback = loaded_font_names()
    for node in doc.root.iter():
        if local_name(node.tag) != "text":
            continue
        raw = node.get("font-family")
        if raw is None or not raw.strip():
            continue
        value = raw.strip()
        if value in names:
            continue
        if fallback is None:  # no face loaded at all: the run is blank, not falling back
            because = ("so nothing is drawn for this run at all — no face is loaded;"
                       " `nanoframes doctor` names what is missing.")
        else:
            because = (f"so the text is drawn with {fallback!r} instead; name one loaded"
                       f" face exactly ({fallback!r} is the default).")
        findings.append(Finding(
            "warning",
            f"{bounds.label(node)}{_drawn_text(node)}: font-family={raw!r} selects no"
            f" loaded face — this renderer matches the whole value against the faces it"
            f" has loaded (no CSS list, no per-glyph fallback, case-sensitive), "
            + because,
            code="render.unresolved_font_family", element=bounds.label(node),
        ))


def _drawn_text(node, limit: int = 24) -> str:
    """The words an element draws, for a finding that has no ``id`` to point at.

    A composition's ``<text>`` often carries no ``id`` (a generated chart, a
    hand-written card), and a warning about the face it asked for is useless
    without something that identifies *which* run of text it is about.
    """
    text = " ".join("".join(node.itertext()).split())
    if not text:
        return ""
    return f" ({text[:limit]}…)" if len(text) > limit else f" ({text})"


def _span_timing(comp: Composition, node) -> str | None:
    """The timing a span declared that will not happen, or ``None`` if it declared none.

    Returns the authored attributes as they were written (the message quotes
    them back), or ``None`` when the span carries no timing, or carries a window
    equal to the whole composition — a no-op the renderer is not failing to do.
    """
    start = _opt_float(node.get("data-start"))
    duration = _opt_float(node.get("data-duration"))
    fade = _opt_float(node.get("data-fade"))
    if fade is not None and fade > 0:
        return f"data-fade={node.get('data-fade')!r}"
    if start is None and duration is None:
        return None
    clip_start = start or 0.0
    clip_end = clip_start + (duration if duration is not None else comp.duration)
    if clip_start <= 1e-9 and clip_end >= comp.duration - 1e-9:
        return None
    declared = [f"{name}={node.get(name)!r}" for name in _SPAN_TIMING_ATTRS
                if node.get(name) is not None]
    return " ".join(declared)


def _check_media(doc: Document, findings: list[Finding]) -> None:
    """Video-backed ``<image>`` nodes: the toolchain they need and the time they map to.

    Two silent failures live here. Without ffmpeg the composition simply cannot
    render, so that is an error. And a window that maps past the end of its own
    source freezes on the last frame — visible, wrong, and easy to author by
    accident (``data-in`` too early, or a speed/window mismatch).
    """
    comp = doc.composition
    entries = []
    for node in refs.iter_images(doc.root):
        spec = media.parse_media(node, doc.base_dir, comp.duration)
        if spec is not None:
            entries.append((node, spec))
    if not entries:
        return
    if not media.has_tool("ffmpeg"):
        findings.append(Finding(
            "error",
            f"{len(entries)} video-backed <image> node(s) need ffmpeg to extract frames,"
            " and ffmpeg was not found on PATH",
            code="media.missing_tool",
        ))
        return

    probed: dict = {}
    for node, spec in entries:
        label = node.get("id") or "<image>"
        for problem in media.media_attribute_problems(node):
            findings.append(Finding(
                "warning", f"element {label}: {problem} (using the default)",
                code="media.bad_attribute", element=label,
            ))
        if spec.loop:
            continue
        if spec.source not in probed:
            probed[spec.source] = media.probe_duration(spec.source)
        duration = probed[spec.source]
        if duration is None:
            continue
        mapped_end = spec.in_point + spec.duration * spec.speed
        if mapped_end > duration + 1e-6:
            findings.append(Finding(
                "warning",
                f"element {label}: this clip maps up to {mapped_end:.2f}s of a"
                f" {duration:.2f}s source ({os.path.basename(spec.source)}) — the picture"
                f" freezes at the end; add data-loop to repeat, or move data-in earlier",
                code="media.out_of_range", element=label,
            ))


def _check_nested(doc: Document, measurer, findings: list[Finding], depth: int) -> None:
    """Lint embedded compositions too — `check` on a parent covers its children.

    A nested ``.nf.svg`` is inlined at render time, so a defect inside it is a
    defect in the parent's output; without this, `check` on the parent would
    report a clean composition whose child draws nothing. No extraction is
    involved — the child is linted, not rendered. The depth cap doubles as the
    cycle guard (a composition embedding itself stops here with a warning).
    """
    for source in media.nested_sources(doc):
        name = os.path.basename(source)
        try:
            child = parse_file(source)
        except (OSError, ParseError) as exc:
            findings.append(Finding("warning", f"nested composition {name}: {exc}",
                                    code="media.nested_unreadable"))
            continue
        if depth >= _MAX_NESTED_DEPTH:
            findings.append(Finding(
                "warning",
                f"nested composition {name}: nesting is deeper than {_MAX_NESTED_DEPTH}"
                " levels (or a composition includes itself) — not checked further",
                code="media.nested_depth"))
            continue
        for finding in lint_document(child, measurer, _depth=depth + 1):
            findings.append(Finding(finding.severity, f"[{name}] {finding.message}",
                                    code=finding.code, element=finding.element,
                                    t=finding.t))


def _opt_float(raw: str | None):
    """A declared numeric attribute, or ``None`` when it was not declared (or is junk)."""
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _check_safe_margin(doc: Document, measurer, findings: list[Finding]) -> None:
    """Opt-in: text must stay inside ``data-safe-margin`` px of the canvas edge.

    Restricted to text on purpose — a full-bleed background legitimately touches
    every edge, so checking all geometry would fire on every composition and
    mean nothing. Title-safe is a claim about where the *words* are.
    """
    comp = doc.composition
    margin = _opt_float(doc.root.get("data-safe-margin"))
    if margin is None or margin <= 0:
        return
    inner = bounds.Box(margin, margin, comp.width - margin, comp.height - margin)
    for entry in _sampled_boxes(doc, measurer).values():
        if entry["tag"] != "text":
            continue
        boxes = [box for box, complete in entry["samples"] if box is not None and complete]
        outside = [b for b in boxes if not _inside(inner, b)]
        if not outside:
            continue
        box = outside[0]
        findings.append(Finding(
            "warning",
            f"{entry['label']}: text crosses the {margin:g}px safe margin"
            f" (box [{box.x0:.0f},{box.y0:.0f},{box.x1:.0f},{box.y1:.0f}] vs the"
            f" [{inner.x0:g},{inner.y0:g} .. {inner.x1:g},{inner.y1:g}] content area)",
            code="layout.outside_safe_margin", element=entry["label"],
        ))


def _check_palette(doc: Document, findings: list[Finding]) -> None:
    """Opt-in: bound the number of distinct paint colors (``data-palette-budget``).

    Counts declared ``fill``/``stroke``/``stop-color`` values plus any fill/stroke
    a keyframe animates to, ignoring ``none``/``currentColor``/``url(#...)``.
    """
    budget = _opt_float(doc.root.get("data-palette-budget"))
    if budget is None or budget <= 0:
        return
    colors: set[str] = set()
    for node in doc.root.iter():
        for attr in _PAINT_ATTRS:
            value = node.get(attr)
            if value is None:
                continue
            normalized = _normalize_color(value)
            if normalized:
                colors.add(normalized)
    for anim in doc.composition.animations:
        for kf in anim.keyframes:
            for prop in ("fill", "stroke"):
                if prop in kf.props:
                    normalized = _normalize_color(str(kf.props[prop]))
                    if normalized:
                        colors.add(normalized)
    if len(colors) <= budget:
        return
    shown = ", ".join(sorted(colors)[:8]) + ("…" if len(colors) > 8 else "")
    findings.append(Finding(
        "warning",
        f"palette budget {budget:g} exceeded: {len(colors)} distinct paint colors used"
        f" ({shown})",
        code="design.palette_over_budget",
    ))


_PAINT_ATTRS = ("fill", "stroke", "stop-color")
_NON_COLORS = ("none", "currentcolor", "transparent", "inherit")


def _normalize_color(value: object) -> str | None:
    """A comparable color token, or ``None`` for non-colors and paint servers."""
    text = str(value).strip().lower()
    if not text or text in _NON_COLORS or text.startswith("url("):
        return None
    return text


def _inside(outer: bounds.Box, box: bounds.Box) -> bool:
    """Whether ``box`` fits within ``outer`` (with the shared sub-pixel slack)."""
    return (box.x0 >= outer.x0 - _EDGE_SLACK and box.y0 >= outer.y0 - _EDGE_SLACK
            and box.x1 <= outer.x1 + _EDGE_SLACK and box.y1 <= outer.y1 + _EDGE_SLACK)


def _slack(canvas: bounds.Box) -> bounds.Box:
    return bounds.Box(canvas.x0 - _EDGE_SLACK, canvas.y0 - _EDGE_SLACK,
                      canvas.x1 + _EDGE_SLACK, canvas.y1 + _EDGE_SLACK)

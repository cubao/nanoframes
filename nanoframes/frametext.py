"""Per-frame text: a ``<text>`` whose words are a function of the frame.

A composition is static markup, so a readout that changes every frame — a frame
counter, a clock, a progress label — has no way to be written as one element.
The idiom that filled the gap was to emit one ``<text>`` per frame, each with
its own ``data-start`` window: a document a hundred times the size of the rest
of the composition, and a trap at the window edges (a window that starts exactly
at a frame's time is a hair outside it for some frames; see
``nanoframes.timeline.frame_times``).

``data-frame-text`` is the declarative form of the same thing. It names the
frame's own numbers in braces, and bake substitutes them for the frame it is
building::

    <text x="100" y="440" font-size="74"
          data-frame-text="This frame index: {frame}, second: {second:.2f}"/>

The fields are the composition's clock, not arbitrary computation — a
composition stays a document that says what it draws, and this is the one part
of a frame that was only ever *about* the frame. Format specs are Python's
(``{second:.2f}``, ``{frame:04d}``), and an unknown field is reported by
``nanoframes check`` rather than drawn as literal braces.

Auto-layout runs after substitution, so a chip, a wrap or a curve measures the
words actually drawn at that time, not the template.
"""

from __future__ import annotations

import string

#: Attribute that turns a <text>'s content into a per-frame template.
ATTRIBUTE = "data-frame-text"

#: The frame's own numbers. Deliberately small: a template that could reach
#: outside the frame would be a program, and a composition is not one.
FIELDS = {
    "frame": "the frame's index, from 0 (integer)",
    "second": "the frame's time in seconds (float; `time` is an alias)",
    "time": "alias of `second`",
    "fps": "the composition's frame rate",
    "duration": "the composition's duration in seconds",
    "frames": "how many frames the clip has",
}


class TemplateError(ValueError):
    """A ``data-frame-text`` that cannot be evaluated."""


def fields_used(template: str) -> list[str]:
    """The field names a template reads, in order, or raise ``TemplateError``.

    Only ``{name}`` and ``{name:spec}`` are meaningful: attribute access,
    indexing and conversions (``{frame.__class__}``) are refused rather than
    evaluated, because a template is a label about the frame, not an expression
    language. A stray brace is refused too — it would otherwise reach the frame
    as literal text and look like a typo nobody could find.
    """
    used: list[str] = []
    for _literal, field, spec, conversion in string.Formatter().parse(template):
        if field is None:
            continue
        if conversion is not None or field == "" or any(c in field for c in ".[]"):
            raise TemplateError(f"{{{field}}} is not a plain field name")
        if field not in FIELDS:
            known = ", ".join(sorted(FIELDS))
            raise TemplateError(f"unknown field {{{field}}} — the frame offers: {known}")
        if spec:
            _check_spec(field, spec)
        used.append(field)
    return used


def _check_spec(field: str, spec: str) -> None:
    """Refuse a format spec the field's type cannot take, at lint time."""
    sample = {"frame": 1, "frames": 1, "fps": 30}.get(field, 0.0)
    try:
        format(sample, spec)
    except (ValueError, TypeError) as exc:
        raise TemplateError(f"{{{{{field}:{spec}}}}} is not a valid format: {exc}") from exc


def format_template(template: str, comp, t: float) -> str:
    """The words this template draws at time ``t``.

    The frame index is ``round(t * fps)`` rather than a counter carried along:
    the frame is a property of its time, so a render of one arbitrary frame
    (``--t``, ``preview``, a digest sample) reads the same as the batch.
    """
    rate = comp.fps or 1
    frame = int(round(t * rate))
    values = {
        "frame": frame,
        "second": t,
        "time": t,
        "fps": comp.fps,
        "duration": comp.duration,
        "frames": comp.frame_count,
    }
    fields_used(template)  # same refusal at render time as at check time
    parts: list[str] = []
    for literal, field, spec, _conv in string.Formatter().parse(template):
        parts.append(literal)
        if field is not None:
            parts.append(format(values[field], spec or ""))
    return "".join(parts)

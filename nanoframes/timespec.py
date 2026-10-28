"""Time specs: the ways an author writes "when", parsed in one place.

`--t 2.5` is fine for a human typing a number and wrong for everything else an
author means: "half way", "1:05.5", "the last frame", "from 2s to 4s". Every
command that takes a time takes all of them, because they are parsed here and
not at each call site — which is also why `nanoframes render --t 50%` and
`nanoframes debug --t 50%` cannot disagree about where that is.

The grammar, in the order the parser tries it:

===============  ==========================================================
``120``          a frame index
``120f``         a frame index, said out loud
``3.2s`` ``500ms``  a time
``1:05.5``       minutes:seconds
``50%``          a fraction of the clip
``start`` ``end``  the first and last rendered frame
``2s..4s``       a range (end exclusive), either side omittable
===============  ==========================================================

A bare number is a *frame*, because that is what a frame's identity is and what
a digest or a log names; a duration is written with a unit. This mirrors
fframes' `time_spec`, deliberately: an author moving between the two tools
should not have to relearn what `120` means.
"""

from __future__ import annotations

import re

#: `mm:ss(.f)` / `hh:mm:ss(.f)`
_CLOCK_RE = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")
_BARE_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


class TimeSpecError(ValueError):
    """A time or range that does not name a place in this clip."""


def parse_time(spec, comp, *, default: float | None = None) -> float:
    """Resolve one time spec to seconds.

    ``default`` is what an explicitly empty spec means (``--t`` given no value
    cannot happen, but a range's open ends use this).
    """
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        if default is None:
            raise TimeSpecError("empty time spec")
        return default
    if isinstance(spec, (int, float)):
        return _check(float(spec), comp)

    text = str(spec).strip().lower()
    rate = comp.fps or 1
    duration = comp.duration

    if text == "start":
        return 0.0
    if text == "end":
        # The last rendered frame, not `duration`: those differ by one frame and
        # `end` has to name a frame that exists.
        return max(0.0, duration - 1.0 / rate)

    if text.endswith("%"):
        return _check(_number(text[:-1], spec) / 100.0 * duration, comp)

    # Parse the number first and range-check after: `_check` raises
    # TimeSpecError, which is a ValueError, so wrapping it here discarded the
    # "outside the clip" message and reported a parse failure instead.
    if text.endswith("ms"):
        value = _number(text[:-2], spec)
        return _check(value / 1000.0, comp)
    if text.endswith("s"):
        return _check(_number(text[:-1], spec), comp)

    clock = _CLOCK_RE.match(text)
    if clock is not None:
        hours = int(clock.group(1) or 0)
        return _check(hours * 3600 + int(clock.group(2)) * 60 + float(clock.group(3)), comp)

    if text.endswith("f"):
        return _check(float(text[:-1]) / rate, comp)
    if _BARE_RE.match(text):
        value = float(text)
        # `1.0` is a *time*: every command here took seconds before this
        # grammar existed, and an author who writes `--t 2.5` means two and a
        # half seconds. A bare *integer* is a frame, which is how a frame is
        # named in a digest, a log or this project's own messages. The two
        # readings disagree only for values that look like one and not the
        # other, and `120f` / `4.0s` are there when the intent must be explicit.
        if "." in text:
            return _check(value, comp)
        return _check(value / rate, comp)

    raise TimeSpecError(f"cannot read {spec!r} as a time — try 3.2s, 120, 50%,"
                        f" 1:05.5, start or end")


def _number(text: str, spec) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise TimeSpecError(f"cannot read {spec!r} as a time — try 3.2s, 120,"
                            f" 50%, 1:05.5, start or end") from exc


def _check(seconds: float, comp) -> float:
    """A time outside the clip is a mistake worth refusing, not clamping.

    Clamping would render the first (or last) frame while the command line says
    something else — the kind of quiet substitution this package's checks exist
    to avoid. `end` is the one value that sits inside by construction.
    """
    limit = comp.duration + 1.0 / (comp.fps or 1) + 1e-9
    if seconds < -1e-9 or seconds > limit:
        raise TimeSpecError(f"{seconds:g}s is outside the clip (0..{comp.duration:g}s)")
    return max(0.0, seconds)


def parse_range(spec, comp, *, default=None) -> tuple:
    """Resolve ``a..b`` to ``(start, end)`` in seconds; either side may be open.

    ``end`` is exclusive, as a range is everywhere else. No ``..`` means a single
    time, whose range is that frame: ``parse_range("2s", comp)`` is
    ``(2.0, 2.0 + 1/fps)``. That is what makes `--from/--to` one mechanism
    rather than two.
    """
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        return default if default is not None else (0.0, comp.duration)
    text = str(spec)
    if ".." not in text:
        start = parse_time(text, comp)
        return start, start + 1.0 / (comp.fps or 1)
    left, right = text.split("..", 1)
    start = parse_time(left, comp, default=0.0)
    end = parse_time(right, comp, default=comp.duration)
    if end <= start:
        raise TimeSpecError(f"empty range: {spec!r} ends at or before it starts")
    return start, end


def frame_indices(spec, comp) -> list:
    """Every frame index a spec selects, in order.

    The one place a range becomes frames: `render`, `strip` and `video` all ask
    this, so a range cannot mean 30 frames in one command and 31 in another.
    """
    start, end = parse_range(spec, comp)
    rate = comp.fps or 1
    first = int(round(start * rate))
    last = int(round(end * rate))
    first = max(0, min(first, comp.frame_count - 1))
    last = max(first + 1, min(last, comp.frame_count))
    return list(range(first, last))

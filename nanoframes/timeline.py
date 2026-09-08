"""Deterministic seek(t) evaluation of the animation timeline.

Given a `Composition` and a time `t` (seconds), produce the per-target property
values and the per-element effective clip/fade opacity. Everything here is pure
and deterministic: same (composition, t) => same result.

Supported animated properties:
- ``opacity``            : float 0..1, linear/eased interpolation
- ``transform``          : dict {"translate":[x,y], "scale":[sx,sy], "rotate":deg}
- ``fill`` / ``stroke``  : "#RRGGBB" (or "#RRGGBBAA") color interpolation
Anything else is stepped (holds the earlier keyframe until the next one).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nanoframes.model import Composition, Element, Keyframe

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?$")


@dataclass
class TargetedProps:
    """Computed animation properties for one CSS selector at a given time."""

    target: str
    props: dict[str, object]


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------


def _ease(ease: str, u: float) -> float:
    if ease == "ease-in":
        return u * u
    if ease == "ease-out":
        return 1.0 - (1.0 - u) ** 2
    if ease == "ease-in-out":
        return 3.0 * u * u - 2.0 * u * u * u
    return u  # linear and anything unknown


# ---------------------------------------------------------------------------
# Property interpolation
# ---------------------------------------------------------------------------


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _interpolate(value_a: object, value_b: object, u: float) -> object:
    """Interpolate two keyframe values at eased fraction ``u``."""

    def is_num(v: object) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    if is_num(value_a) and is_num(value_b):
        return _lerp(float(value_a), float(value_b), u)

    if isinstance(value_a, dict) and isinstance(value_b, dict):
        # Recurse over shared keys so nested lists (e.g. transform) interpolate.
        out: dict[str, object] = {}
        for key in value_a:
            va, vb = value_a.get(key), value_b.get(key)
            if key in value_b:
                out[key] = _interpolate(va, vb, u)
            else:
                out[key] = va
        return out

    if isinstance(value_a, list) and isinstance(value_b, list) and len(value_a) == len(value_b):
        if all(is_num(v) for v in value_a) and all(is_num(v) for v in value_b):
            return [_lerp(float(x), float(y), u) for x, y in zip(value_a, value_b)]
        return value_a

    if isinstance(value_a, str) and isinstance(value_b, str):
        ma, mb = _HEX_RE.match(value_a), _HEX_RE.match(value_b)
        if ma and mb:
            return _lerp_color(value_a, value_b, u)

    # Non-interpolable: hold the earlier keyframe until we reach the next one.
    return value_a


def _lerp_color(a: str, b: str, u: float) -> str:
    def rgb(hexstr: str) -> tuple[int, int, int]:
        s = hexstr.lstrip("#")
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)

    ra, ga, ba = rgb(a)
    rb, gb, bb = rgb(b)
    chans = [round(_lerp(x, y, u)) for x, y in ((ra, rb), (ga, gb), (ba, bb))]
    return "#{:02x}{:02x}{:02x}".format(*chans)


def _keyframe_value(kf: Keyframe, key: str) -> object | None:
    return kf.props.get(key)


def _evaluate_animation(keyframes: list[Keyframe], t: float) -> dict[str, object]:
    """Evaluate all properties of a single animation at time ``t``."""
    kfs = sorted(keyframes, key=lambda k: k.t)
    if not kfs:
        return {}
    if t <= kfs[0].t:
        return dict(kfs[0].props)
    if t >= kfs[-1].t:
        return dict(kfs[-1].props)

    # Find bracketing pair.
    for i in range(len(kfs) - 1):
        ka, kb = kfs[i], kfs[i + 1]
        if ka.t <= t <= kb.t:
            span = kb.t - ka.t
            u = 1.0 if span == 0 else (t - ka.t) / span
            u = _ease(ka.ease, u)
            props: dict[str, object] = {}
            for key in list(dict.fromkeys([*ka.props, *kb.props])):
                va, vb = _keyframe_value(ka, key), _keyframe_value(kb, key)
                if va is None or vb is None:
                    props[key] = va if va is not None else vb
                else:
                    props[key] = _interpolate(va, vb, u)
            return props
    return dict(kfs[-1].props)


# ---------------------------------------------------------------------------
# Public evaluation API
# ---------------------------------------------------------------------------


def evaluate(composition: Composition, t: float) -> list[TargetedProps]:
    """Return the animated properties for every timeline target at time ``t``."""
    return [
        TargetedProps(target=a.target, props=_evaluate_animation(a.keyframes, t))
        for a in composition.animations
    ]


def effective_opacity(element: Element, t: float) -> tuple[bool, float]:
    """Clip-presence + fade folded into an effective opacity.

    Returns ``(visible, opacity)``. ``visible`` is False outside the element's
    clip window (points at which it should not be rasterized at all).
    """
    start = element.clip_start
    end = start + (element.clip_duration or 0.0)

    if t < start or t > end:
        return False, 0.0

    opacity = 1.0
    if element.fade_in > 0:
        opacity = min(1.0, (t - start) / element.fade_in)
    if element.fade_out > 0:
        opacity = min(opacity, (end - t) / element.fade_out)
    return True, max(0.0, opacity)
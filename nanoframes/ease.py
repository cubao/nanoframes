"""Easing curves: the vocabulary a keyframe's ``ease`` names, and what it means.

A keyframe's ``ease`` is the curve of the segment that **arrives at** it — the
convention CSS transitions, Lottie, GSAP and Framer Motion all share. So the
*last* keyframe's ``ease`` is the one that shapes the landing, which is the beat
an author is actually choosing; an ``ease`` on the *first* keyframe shapes
nothing, because no segment arrives there (``check`` says so, as
``animation.inert_ease``).

The four names that always existed — ``linear``, ``ease-in``, ``ease-out``,
``ease-in-out`` — keep their exact arithmetic, so a composition that already
uses them renders bit-identically. Everything else here is additive:

``cubic-bezier(x1, y1, x2, y2)``
    any curve, written the way every motion-design reference table writes it.
    ``x1`` and ``x2`` must lie in ``0..1`` (that is what keeps the curve a
    function of time); ``y`` is free, so an overshooting settle — the classic
    ``cubic-bezier(0.175, 0.885, 0.32, 1.275)`` — is expressible instead of
    being hand-built out of extra keyframes.

a small set of named curves
    taken from the industry tables (see ``NAMED_BEZIERS``): Material 3's
    standard / emphasized / accelerate / decelerate, Apple's HIG default, the
    premium "gentle float", and the overshoot pair ``ease-out-back`` and
    ``ease-in-back``. These are the names the motion-design vocabulary reaches
    for, so an agent can copy a table row either as its name or as its numbers.

An ``ease`` naming none of these still falls back to linear, exactly as before.
The difference is that ``nanoframes check`` now names it
(``animation.unknown_ease``) rather than leaving the author to notice that the
motion never received the curve they wrote.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# The four original curves — arithmetic unchanged, so existing frames are stable
# ---------------------------------------------------------------------------


def _linear(u: float) -> float:
    return u


def _ease_in(u: float) -> float:
    return u * u


def _ease_out(u: float) -> float:
    return 1.0 - (1.0 - u) ** 2


def _ease_in_out(u: float) -> float:
    return 3.0 * u * u - 2.0 * u * u * u


# ---------------------------------------------------------------------------
# Cubic bezier
# ---------------------------------------------------------------------------


def _axis(a: float, b: float, t: float) -> float:
    """One coordinate of a cubic bezier through ``(0,0)`` and ``(1,1)``."""
    mt = 1.0 - t
    return 3.0 * mt * mt * t * a + 3.0 * mt * t * t * b + t * t * t


def _solve_t(x1: float, x2: float, u: float, steps: int = 48) -> float:
    """Invert ``x(t) = u`` for ``t`` by bisection.

    Bisection rather than Newton-with-derivative: it costs a few more
    iterations but uses only ``+``, ``*``, ``/`` and comparisons, so two
    machines can disagree only where the arithmetic itself does. Cross-architecture
    determinism is a claim this project checks, so the cheaper-to-reason-about
    solver is the right one.
    """
    lo, hi = 0.0, 1.0
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        if _axis(x1, x2, mid) < u:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def cubic_bezier(x1: float, y1: float, x2: float, y2: float) -> Callable[[float], float]:
    """A CSS-style cubic-bezier timing function.

    Raises ``ValueError`` for control points that would make the curve
    non-monotonic in time (``x1``/``x2`` outside ``0..1``) — a curve that runs
    backwards cannot be evaluated at a single time, and silently linearizing it
    is the failure mode this module exists to avoid.
    """
    for name, value in (("x1", x1), ("x2", x2)):
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"cubic-bezier {name}={value} must lie in 0..1")

    def curve(u: float) -> float:
        if u <= 0.0:
            return 0.0
        if u >= 1.0:
            return 1.0
        return _axis(y1, y2, _solve_t(x1, x2, u))

    return curve


# ---------------------------------------------------------------------------
# The named table
# ---------------------------------------------------------------------------

# Implemented directly, not as beziers: these are the names that predate this
# module and their exact numbers are load-bearing for existing renders.
_CURVES: Dict[str, Callable[[float], float]] = {
    "linear": _linear,
    "ease-in": _ease_in,
    "ease-out": _ease_out,
    "ease-in-out": _ease_in_out,
}

#: Named cubic beziers, with the numbers the industry tables give them
#: (``LottieFiles/motion-design-skill``, MIT: MD3 and Apple HIG rows).
NAMED_BEZIERS: Dict[str, Tuple[float, float, float, float]] = {
    "ease-out-cubic": (0.215, 0.61, 0.355, 1.0),
    "ease-in-out-cubic": (0.645, 0.045, 0.355, 1.0),
    "ease-out-expo": (0.16, 1.0, 0.3, 1.0),
    "ease-out-back": (0.175, 0.885, 0.32, 1.275),   # bounce settle; overshoots past the target
    "ease-in-back": (0.6, -0.28, 0.735, 0.045),     # winds up before it leaves
    "standard": (0.2, 0.0, 0.0, 1.0),               # Material 3 standard / "snappy UI"
    "emphasized": (0.05, 0.7, 0.1, 1.0),            # Material 3 emphasized — entrances
    "accelerate": (0.3, 0.0, 1.0, 1.0),             # Material 3 — exits, dismissals
    "decelerate": (0.0, 0.0, 0.0, 1.0),             # Material 3 — entering
    "apple": (0.25, 0.1, 0.25, 1.0),                # Apple HIG default
    "gentle": (0.4, 0.0, 0.2, 1.0),                 # premium "gentle float", ambient
}

_NUM = r"[-+]?(?:[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"
_BEZIER_RE = re.compile(
    r"^cubic-bezier\(\s*(" + _NUM + r")\s*,\s*(" + _NUM + r")\s*,"
    r"\s*(" + _NUM + r")\s*,\s*(" + _NUM + r")\s*\)$"
)

# Parsed curves, keyed by the exact string an author wrote. `ease` is evaluated
# once per segment per frame, so re-parsing a `cubic-bezier(...)` literal on
# every frame would be the only cost in an otherwise table lookup.
_CACHE: Dict[str, Optional[Callable[[float], float]]] = {}


def _build(spec: str) -> Optional[Callable[[float], float]]:
    if not spec:
        return None
    known_curve = _CURVES.get(spec)
    if known_curve is not None:
        return known_curve
    numbers = NAMED_BEZIERS.get(spec)
    if numbers is not None:
        return cubic_bezier(*numbers)
    match = _BEZIER_RE.match(spec)
    if match is None:
        return None
    try:
        return cubic_bezier(*(float(g) for g in match.groups()))
    except ValueError:
        return None


def curve(spec: str) -> Optional[Callable[[float], float]]:
    """The curve an ``ease`` value names, or ``None`` when it names nothing."""
    if spec in _CACHE:
        return _CACHE[spec]
    built = _build(spec)
    _CACHE[spec] = built
    return built


def known(spec: str) -> bool:
    """Whether an ``ease`` value is one this renderer actually applies."""
    return curve(spec) is not None


def eased(spec: str, u: float) -> float:
    """Evaluate ``ease`` at fraction ``u``; an unknown name falls back to linear."""
    resolved = curve(spec)
    return u if resolved is None else resolved(u)


def names() -> list:
    """Every ``ease`` value that resolves, sorted (documentation and tests)."""
    return sorted(set(_CURVES) | set(NAMED_BEZIERS))

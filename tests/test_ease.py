"""The easing vocabulary: which ``ease`` values resolve, and what they do.

The load-bearing cases are the two ends of the contract — the four original
names must keep the *exact* arithmetic they always had (existing compositions
render bit-identically), and the curves that only this module can express must
actually be able to leave the unit interval (an overshoot is the point of the
`-back` pair, not a rounding artefact to clamp away).
"""

import pytest

from nanoframes import ease

# --- the four originals are frozen in place ---------------------------------

def test_the_original_four_keep_their_exact_arithmetic():
    """A composition already using these names must not move by a single bit."""
    for u in (0.0, 0.13, 0.5, 0.77, 1.0):
        assert ease.eased("linear", u) == u
        assert ease.eased("ease-in", u) == u * u
        assert ease.eased("ease-out", u) == 1.0 - (1.0 - u) ** 2
        assert ease.eased("ease-in-out", u) == 3.0 * u * u - 2.0 * u * u * u


def test_ease_in_out_is_symmetric_at_the_midpoint():
    assert ease.eased("ease-in-out", 0.5) == 0.5


# --- every curve lands exactly on its endpoints -----------------------------

def test_every_curve_is_exact_at_both_ends():
    """An eased keyframe must land on its declared value, not near it."""
    for name in ease.names():
        assert ease.eased(name, 0.0) == 0.0, name
        assert ease.eased(name, 1.0) == 1.0, name


# --- cubic-bezier -----------------------------------------------------------

def test_the_identity_bezier_reproduces_linear():
    """cubic-bezier(1/3,1/3,2/3,2/3) is exactly x(t)=t, y(t)=t."""
    curve = ease.curve("cubic-bezier(0.3333333333333333, 0.3333333333333333,"
                       " 0.6666666666666666, 0.6666666666666666)")
    assert curve is not None
    for u in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert abs(curve(u) - u) < 1e-6


def test_a_bezier_is_solved_for_x_and_evaluated_at_y():
    """The two axes are not interchangeable: x is inverted, y is read back."""
    decelerating = ease.curve("cubic-bezier(0.2, 0, 0, 1)")   # Material 3 standard
    accelerating = ease.curve("cubic-bezier(0.3, 0, 1, 1)")   # Material 3 accelerate
    assert decelerating(0.5) > 0.6      # most of the distance is covered early
    assert accelerating(0.5) < 0.4      # most of it is left for the end


def test_a_bezier_whose_x_control_points_leave_the_unit_interval_is_refused():
    """x1/x2 outside 0..1 make the curve run backwards in time — not a curve."""
    assert not ease.known("cubic-bezier(1.5, 0, 0, 1)")
    assert not ease.known("cubic-bezier(0, 0, -0.2, 1)")
    # y is free, which is exactly how the overshoot pair is spelled
    assert ease.known("cubic-bezier(0.175, 0.885, 0.32, 1.275)")


def test_malformed_bezier_literals_are_not_curves():
    for bad in ("cubic-bezier(0.2, 0, 1)", "cubic-bezier(a, b, c, d)",
                "cubic-bezier(0.2 0 0 1)", "cubic-bezier", "cubic-bezier()"):
        assert not ease.known(bad), bad


# --- overshoot is expressible, and is not clamped ---------------------------

def test_the_back_pair_leaves_the_unit_interval():
    """Overshoot and anticipation are the capability the four names lack."""
    peak = max(ease.eased("ease-out-back", i / 200) for i in range(201))
    dip = min(ease.eased("ease-in-back", i / 200) for i in range(201))
    assert peak > 1.05          # lands past the target, then settles back
    assert dip < -0.02          # winds up in the opposite direction first


def test_overshoot_is_not_silently_clamped_to_one():
    assert ease.eased("ease-out-back", 0.7) > 1.0


# --- the table itself -------------------------------------------------------

def test_every_documented_name_resolves():
    for name in ("linear", "ease-in", "ease-out", "ease-in-out",
                 "ease-out-cubic", "ease-in-out-cubic", "ease-out-expo",
                 "ease-out-back", "ease-in-back", "standard", "emphasized",
                 "accelerate", "decelerate", "apple", "gentle"):
        assert ease.known(name), name


def test_an_unknown_name_falls_back_to_linear():
    """The old behaviour is kept — what changes is that `check` now names it."""
    for bad in ("ease-out-back ", "Ease-Out", "wobble", "", "bounce"):
        assert not ease.known(bad), bad
        assert ease.eased(bad, 0.37) == 0.37


def test_a_missing_ease_is_linear_and_is_not_an_unknown_name():
    """``""`` is what an absent ease degrades to; it must not be reported."""
    assert ease.eased("", 0.6) == 0.6


@pytest.mark.parametrize("name", ["standard", "emphasized", "apple", "gentle"])
def test_a_decelerating_curve_advances_further_than_linear_early(name):
    """The industry curves are monotone in time, so a lookup is well defined."""
    previous = -1.0
    for i in range(101):
        value = ease.eased(name, i / 100)
        assert value >= previous - 1e-12
        previous = value

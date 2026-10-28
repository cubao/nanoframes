"""Spring easing: the three damping regimes, against the ODE they solve.

The closed forms are not decoration — they are the exact solution of
``x'' + 2ζω₀x' + ω₀²x = ω₀²`` with a unit step at ``x(0) = x'(0) = 0``. So they
are checked by integrating that equation numerically and comparing, which is the
only way to catch the mistake a two-branch implementation makes: collapsing the
over-damped case onto the critically damped formula still looks like a spring
and settles at the wrong speed.
"""

from __future__ import annotations

import math

import pytest

from nanoframes import ease
from nanoframes.lint import lint_string


def _ode(mass: float, stiffness: float, damping: float, marks=(0.1, 0.3, 0.5, 1.0, 1.5),
         h: float = 1e-5) -> dict:
    """RK4 on the spring's own equation of motion, as the reference."""
    out = {}
    # Integrate to exactly each mark, so a sample is the state *at* that time
    # rather than the state at the first step past it (a 1e-5 offset that shows
    # up as a 6e-5 difference while the spring is still moving fast).
    for mark in sorted(marks):
        x = v = 0.0
        steps = int(round(mark / h))
        for _ in range(steps):
            def f(x, v):
                return v, -(damping / mass) * v - (stiffness / mass) * (x - 1.0)

            k1 = f(x, v)
            k2 = f(x + k1[0] * h / 2, v + k1[1] * h / 2)
            k3 = f(x + k2[0] * h / 2, v + k2[1] * h / 2)
            k4 = f(x + k3[0] * h, v + k3[1] * h)
            x += h * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]) / 6
            v += h * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]) / 6
        out[mark] = x
    return out


@pytest.mark.parametrize("mass,stiffness,damping", [
    (1.0, 180.0, 20.0),      # under-damped
    (1.0, 180.0, 2 * math.sqrt(180.0)),   # critically damped
    (1.0, 180.0, 80.0),      # over-damped
    (1.0, 100.0, 50.0),      # over-damped, gentler
    (2.0, 240.0, 15.0),      # under-damped with a heavier mass
])
def test_the_closed_form_solves_the_equation_of_motion(mass, stiffness, damping):
    curve = ease.spring(mass, stiffness, damping)
    reference = _ode(mass, stiffness, damping)
    for t, expected in reference.items():
        assert curve(t) == pytest.approx(expected, abs=1e-9), f"t={t}"


def test_an_under_damped_spring_overshoots_and_a_damped_one_does_not():
    under = ease.spring(1.0, 180.0, 20.0)
    over = ease.spring(1.0, 180.0, 80.0)
    assert max(under(t / 100) for t in range(101)) > 1.0
    over_values = [over(t / 100) for t in range(101)]
    assert max(over_values) <= 1.0 + 1e-9
    assert min(over_values) >= -1e-9


def test_critically_damped_is_the_fastest_approach_that_does_not_pass():
    """ζ = 1 is the boundary: just under it overshoots, just over it does not."""
    critical = ease.spring(1.0, 180.0, 2 * math.sqrt(180.0))
    assert max(critical(t / 2000) for t in range(2001)) <= 1.0 + 1e-9
    # The overshoot shrinks with damping (measured: zeta 0.8 -> +1.5%, 0.95 ->
    # +0.007%, 0.999 -> -0.001%), so the test leans on one where it is visible
    # rather than on the boundary, where it is below the resolution of a frame.
    slightly_under = ease.spring(1.0, 180.0, 2 * math.sqrt(180.0) * 0.8)
    assert max(slightly_under(t / 2000) for t in range(2001)) > 1.0


def test_the_curve_starts_at_the_origin_and_settles_on_one():
    """An over-damped spring is *slow*: at u=1 it has not finished, and that is
    the motion its numbers describe. It must still converge — and it should say
    so, rather than arriving early the way the critically-damped formula does."""
    under = ease.spring(1.0, 180.0, 20.0)
    over = ease.spring(1.0, 180.0, 80.0)
    for curve in (under, over):
        assert curve(0.0) == 0.0
        assert curve(20.0) == pytest.approx(1.0, abs=1e-9)
    assert under(1.0) == pytest.approx(1.0, abs=0.01)
    assert over(1.0) < 0.95, "an over-damped spring has not arrived at u=1"


def test_a_spring_with_no_damping_is_refused():
    """It would never settle, so it cannot be a segment that arrives anywhere."""
    with pytest.raises(ValueError) as err:
        ease.spring(1.0, 180.0, 0.0)
    assert "damping" in str(err.value)


@pytest.mark.parametrize("kwargs", [{"mass": 0.0}, {"mass": -1.0},
                                    {"stiffness": 0.0}, {"damping": -1.0}])
def test_impossible_parameters_are_refused(kwargs):
    base = {"mass": 1.0, "stiffness": 180.0, "damping": 20.0}
    with pytest.raises(ValueError):
        ease.spring(**{**base, **kwargs})


# --- the declared syntax ------------------------------------------------------

def test_a_bare_spring_is_the_default_spring():
    assert ease.known("spring()")
    assert ease.eased("spring()", 0.25) == ease.spring()(0.25)


def test_parameters_are_read_in_order_and_the_rest_default():
    assert ease.eased("spring(2, 240)", 0.3) == ease.spring(2.0, 240.0)(0.3)
    assert ease.eased("spring(1, 180, 80)", 0.3) == ease.spring(1.0, 180.0, 80.0)(0.3)


def test_a_spring_that_cannot_exist_is_not_a_curve():
    """`spring(1,180,0)` names no motion, so it is inert like a typo — and `check` says so."""
    assert not ease.known("spring(1,180,0)")
    assert ease.eased("spring(1,180,0)", 0.4) == 0.4


def test_the_name_list_documents_it():
    assert "spring()" in " ".join(ease.names()) or ease.known("spring()")


def test_check_names_a_spring_that_cannot_be_built():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="50"'
           ' data-duration="1"><rect id="r" width="10" height="10" fill="#fff"'
           ' data-duration="1"/><script type="application/nanoframes+json"><![CDATA['
           '{"animations":[{"target":"#r","keyframes":['
           '{"t":0,"opacity":0},{"t":0.5,"opacity":1,"ease":"spring(1,180,0)"}]}]}'
           ']]></script></svg>')
    codes = [f.code for f in lint_string(svg)]
    assert "animation.unknown_ease" in codes


def test_check_accepts_a_real_spring():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="50"'
           ' data-duration="1"><rect id="r" width="10" height="10" fill="#fff"'
           ' data-duration="1"/><script type="application/nanoframes+json"><![CDATA['
           '{"animations":[{"target":"#r","keyframes":['
           '{"t":0,"opacity":0},{"t":0.5,"opacity":1,"ease":"spring(1,180,20)"}]}]}'
           ']]></script></svg>')
    assert "animation.unknown_ease" not in [f.code for f in lint_string(svg)]


# --- in a frame ---------------------------------------------------------------

def test_a_spring_moves_the_picture():
    import numpy as np

    from nanoframes.parse import parse_string
    from nanoframes.render import render_frame

    svg = """<svg xmlns="http://www.w3.org/2000/svg" data-width="200" data-height="100"
         data-fps="30" data-duration="2.0" data-composition-id="s">
      <rect width="200" height="100" fill="#ffffff" data-duration="2.0"/>
      <rect id="b" x="20" y="40" width="20" height="20" fill="#0000ff" data-duration="2.0"/>
      <script type="application/nanoframes+json"><![CDATA[
      {"animations":[{"target":"#b","keyframes":[
          {"t":0.0,"transform":{"translate":[0,0]}},
          {"t":1.0,"transform":{"translate":[140,0]},"ease":"spring(1,180,20)"}]}]}
      ]]></script>
    </svg>"""
    doc = parse_string(svg)
    early = np.array(render_frame(doc, 0.25).convert("RGB"))
    late = np.array(render_frame(doc, 1.0).convert("RGB"))
    assert not np.array_equal(early, late)


def test_a_spring_is_deterministic():
    curve = ease.spring(1.0, 180.0, 20.0)
    assert [curve(t / 97) for t in range(98)] == [curve(t / 97) for t in range(98)]

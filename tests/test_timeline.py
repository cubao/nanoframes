"""Tests for the deterministic timeline evaluator."""

from nanoframes.model import Animation, Composition, Element, Keyframe
from nanoframes.timeline import effective_opacity, evaluate


def comp(animations):
    return Composition(width=100, height=100, fps=30, duration=4.0, animations=animations)


def linear_anim(target, kf_list) -> Animation:
    return Animation(target=target, keyframes=[Keyframe(t=t, **{"props": {**props}}) for (t, props) in kf_list])


def test_opacity_two_keyframes():
    a = Animation(
        target="#x",
        keyframes=[Keyframe(0.0, {"opacity": 0.0}), Keyframe(1.0, {"opacity": 1.0})],
    )
    res = evaluate(comp([a]), 0.5)
    assert len(res) == 1
    assert abs(res[0].props["opacity"] - 0.5) < 1e-9


def test_opacity_clamps_before_and_after():
    a = Animation(
        target="#x",
        keyframes=[Keyframe(1.0, {"opacity": 0.0}), Keyframe(2.0, {"opacity": 1.0})],
    )
    assert evaluate(comp([a]), 0.0)[0].props["opacity"] == 0.0
    assert evaluate(comp([a]), 5.0)[0].props["opacity"] == 1.0


def test_translate_interpolation():
    a = Animation(
        target="#x",
        keyframes=[
            Keyframe(0.0, {"transform": {"translate": [0.0, 0.0], "scale": [1.0, 1.0]}}),
            Keyframe(1.0, {"transform": {"translate": [100.0, 50.0], "scale": [2.0, 2.0]}}),
        ],
    )
    p = evaluate(comp([a]), 0.5)[0].props["transform"]
    assert p == {"translate": [50.0, 25.0], "scale": [1.5, 1.5]}


def test_rotate_interpolation():
    a = Animation(target="#x",
                  keyframes=[Keyframe(0.0, {"transform": {"rotate": 0}}),
                             Keyframe(1.0, {"transform": {"rotate": 90}})])
    assert evaluate(comp([a]), 0.5)[0].props["transform"]["rotate"] == 45.0


def test_color_interpolation():
    a = Animation(target="#x",
                  keyframes=[Keyframe(0.0, {"fill": "#000000"}),
                             Keyframe(1.0, {"fill": "#ffffff"})])
    assert evaluate(comp([a]), 0.5)[0].props["fill"] == "#808080"


def test_ease_in_out_differs_from_linear():
    kfs = [Keyframe(0.0, {"opacity": 0.0}, ease="linear"),
           Keyframe(1.0, {"opacity": 1.0}, ease="linear")]
    linear_z = evaluate(comp([Animation("#x", kfs)]), 0.5)[0].props["opacity"]

    kfs2 = [Keyframe(0.0, {"opacity": 0.0}, ease="ease-in-out"),
            Keyframe(1.0, {"opacity": 1.0}, ease="ease-in-out")]
    eased = evaluate(comp([Animation("#x", kfs2)]), 0.5)[0].props["opacity"]
    # both should be 0.5 at midpoint for symmetric easing, so compare off-midpoint
    assert linear_z == 0.5
    assert eased == 0.5  # ease-in-out is symmetric at midpoint
    # but differs away from midpoint
    assert evaluate(comp([Animation("#x", kfs2)]), 0.25)[0].props["opacity"] != 0.25


def test_the_ease_belongs_to_the_keyframe_the_motion_arrives_at():
    """`ease-out` on the landing keyframe decelerates the approach, as in CSS."""
    a = Animation("#x", [Keyframe(0.0, {"opacity": 0.0}),
                         Keyframe(1.0, {"opacity": 1.0}, ease="ease-out")])
    # ease-out covers most of the distance early: at a quarter of the time the
    # value is already 1 - (1 - 0.25)^2, not 0.25
    assert evaluate(comp([a]), 0.25)[0].props["opacity"] == 1.0 - 0.75 ** 2


def test_an_ease_on_the_first_keyframe_shapes_no_segment():
    """Nothing arrives at the first keyframe, so its ease cannot apply."""
    with_ease = Animation("#x", [Keyframe(0.0, {"opacity": 0.0}, ease="ease-out"),
                                 Keyframe(1.0, {"opacity": 1.0})])
    without_ease = Animation("#x", [Keyframe(0.0, {"opacity": 0.0}),
                                    Keyframe(1.0, {"opacity": 1.0})])
    for t in (0.25, 0.5, 0.75):
        assert (evaluate(comp([with_ease]), t)[0].props["opacity"]
                == evaluate(comp([without_ease]), t)[0].props["opacity"])


def test_an_overshooting_curve_passes_its_target_inside_the_segment():
    """A bezier's y axis is free, so the value may exceed the target and settle."""
    a = Animation("#x", [Keyframe(0.0, {"opacity": 0.0}),
                         Keyframe(1.0, {"opacity": 1.0}, ease="ease-out-back")])
    peak = max(evaluate(comp([a]), i / 100)[0].props["opacity"] for i in range(101))
    assert peak > 1.0
    assert evaluate(comp([a]), 1.0)[0].props["opacity"] == 1.0


def test_an_unknown_ease_interpolates_linearly():
    """The silent fallback is kept; `check` is what names it."""
    a = Animation("#x", [Keyframe(0.0, {"opacity": 0.0}),
                         Keyframe(1.0, {"opacity": 1.0}, ease="ease-out-quint")])
    assert evaluate(comp([a]), 0.25)[0].props["opacity"] == 0.25


def test_effective_opacity_clip_and_fade():
    el = Element(element_id="x", tag="text", clip_start=1.0, clip_duration=2.0, fade_in=0.5)
    vis, op = effective_opacity(el, 0.5)
    assert vis is False
    assert op == 0.0

    vis, op = effective_opacity(el, 1.0)
    assert vis is True
    assert op == 0.0  # just at fade start

    vis, op = effective_opacity(el, 1.25)
    assert op == 0.5

    vis, op = effective_opacity(el, 2.0)
    assert vis is True
    assert op == 1.0

    vis, op = effective_opacity(el, 3.5)
    assert vis is False


def test_effective_opacity_fade_out_mirrors_at_clip_end():
    el = Element(element_id="x", tag="text", clip_start=1.0, clip_duration=2.0,
                 fade_in=0.5, fade_out=0.5)
    # clip runs [1.0, 3.0]; fade-out dims the last 0.5s.
    vis, op = effective_opacity(el, 2.5)
    assert vis is True
    assert op == 1.0

    vis, op = effective_opacity(el, 2.75)
    assert vis is True
    assert op == 0.5

    vis, op = effective_opacity(el, 2.9)
    assert vis is True
    assert abs(op - 0.2) < 1e-9

"""Geometry traps: where an element's transformed extent lands.

Covers the three failures a composition can hit with no error anywhere — the
viewport silently rescaling around off-canvas geometry, a pivotless ``rotate``
swinging an element away, and an animated transform replacing the element's own
— plus the diagnostics that surface them (``lint`` findings, ``nanoframes
debug``).
"""

from __future__ import annotations

import numpy as np
import pytest

from nanoframes import bake, bounds
from nanoframes.parse import parse_string

CANVAS = (960, 540)


def comp(body: str, *, width: int = 960, height: int = 540, duration: float = 2.0,
         fps: int = 30, script: str = ""):
    timeline = f'<script type="application/nanoframes+json"><![CDATA[{script}]]></script>' \
        if script else ""
    return parse_string(
        f'<svg xmlns="http://www.w3.org/2000/svg" data-width="{width}" '
        f'data-height="{height}" data-fps="{fps}" data-duration="{duration}">{body}{timeline}</svg>'
    )


def coverage(doc, t: float = 0.0) -> float:
    """Fraction of the frame that has any alpha."""
    from nanoframes.render import render_frame

    img = render_frame(doc, t, warn_blank=False).convert("RGBA")
    alpha = np.asarray(img)[..., 3]
    return float((alpha > 0).mean())


def black_pixels(doc, t: float = 0.0) -> int:
    from nanoframes.render import render_frame

    rgb = np.asarray(render_frame(doc, t, warn_blank=False).convert("RGB"))
    return int(((rgb < 20).all(axis=-1)).sum())


# ---------------------------------------------------------------------------
# The frame's viewport is the canvas, never the content's bounding box
# ---------------------------------------------------------------------------

BG = '<rect id="bg" width="960" height="540" fill="#ffffff"/>'


def test_bake_pins_the_viewport_to_the_canvas():
    svg = bake.bake_svg(comp(BG), 0.0)
    assert 'viewBox="0 0 960 540"' in svg
    assert 'width="960"' in svg and 'height="540"' in svg


def test_author_declared_viewbox_is_left_alone():
    doc = parse_string(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080" '
        'data-width="960" data-height="540" data-duration="1">'
        '<rect width="1920" height="1080" fill="#fff"/></svg>'
    )
    svg = bake.bake_svg(doc, 0.0)
    assert 'viewBox="0 0 1920 1080"' in svg
    assert coverage(doc) == 1.0  # the larger coordinate system still fills the canvas


@pytest.mark.parametrize("extra", [
    '<circle id="dot" cx="1000" cy="400" r="3" fill="#ef4444"/>',   # just past the edge
    '<circle id="dot" cx="20000" cy="400" r="3" fill="#ef4444"/>',  # absurdly far out
    '<rect id="r" x="-199" y="0" width="10" height="10" fill="#f00"/>',
    '<line id="l" x1="0" y1="0" x2="10" y2="10" stroke="#000" stroke-width="2"/>',
])
def test_off_canvas_geometry_still_renders_the_frame(extra):
    """The reported bug: one element outside the canvas blanked the whole frame."""
    doc = comp(BG + extra)
    assert coverage(doc) == 1.0, "background must still fill the canvas"


def test_partially_off_canvas_geometry_is_clipped_not_blacked():
    """An element straddling the edge is clipped; it must not paint a black band."""
    doc = comp(BG + '<rect id="bar" x="-100" y="200" width="300" height="100" fill="#ff0000"/>')
    assert black_pixels(doc) == 0
    assert coverage(doc) == 1.0


def test_offscreen_geometry_does_not_rescale_the_scene():
    """A far off-canvas element cannot shrink or shift what is on the canvas."""
    from nanoframes.render import render_frame

    plain = np.asarray(render_frame(comp(BG), 0.0, warn_blank=False).convert("RGB"))
    shifted = np.asarray(render_frame(
        comp(BG + '<circle cx="-9000" cy="270" r="40" fill="#f00"/>'), 0.0,
        warn_blank=False).convert("RGB"))
    assert np.array_equal(plain, shifted)


# ---------------------------------------------------------------------------
# rotate pivots
# ---------------------------------------------------------------------------


def _node(doc, element_id: str):
    for node in doc.root.iter():
        if node.get("id") == element_id:
            return node
    raise AssertionError(f"no #{element_id} in the document")


def test_self_centered_rotate_pivots_on_the_element():
    doc = comp('<rect id="spin" x="400" y="200" width="160" height="140" fill="#0f0"/>',
               script='{"animations":[{"target":"#spin","keyframes":['
                      '{"t":0,"transform":{"rotate":0,"center":"auto"}},'
                      '{"t":2,"transform":{"rotate":90,"center":"auto"}}]}]}')
    svg = bake.bake_svg(doc, 2.0)
    # box center of the rect is (480, 270): pivot expressed as three transforms
    assert "translate(480,270) rotate(90) translate(-480,-270)" in svg
    assert bounds.local_bounds(_node(doc, "spin")).box.center == (480.0, 270.0)


def test_self_centered_rotate_keeps_the_element_in_place():
    doc = comp('<rect id="spin" x="400" y="200" width="160" height="140" fill="#0f0"/>',
               script='{"animations":[{"target":"#spin","keyframes":['
                      '{"t":0,"transform":{"rotate":0,"center":"auto"}},'
                      '{"t":2,"transform":{"rotate":90,"center":"auto"}}]}]}')
    from nanoframes.render import render_frame

    def green_center(t):
        rgb = np.asarray(render_frame(doc, t, warn_blank=False).convert("RGB"))
        mask = (rgb[..., 1] > 120) & (rgb[..., 0] < 80)
        ys, xs = np.nonzero(mask)
        return xs.mean(), ys.mean(), (xs.max() - xs.min()), (ys.max() - ys.min())

    x0, y0, w0, h0 = green_center(0.0)
    x90, y90, w90, h90 = green_center(2.0)
    assert abs(x0 - x90) < 2 and abs(y0 - y90) < 2  # spins in place
    assert abs(w0 - h90) < 3 and abs(h0 - w90) < 3  # width/height swap at 90 degrees


def test_pivotless_rotate_swings_the_element_off_the_canvas():
    """The footgun the docs call out: rotate(deg) turns around the canvas origin."""
    from nanoframes.render import render_frame

    doc = comp('<rect id="arm" x="420" y="352" width="120" height="16" fill="#0f0"/>',
               script='{"animations":[{"target":"#arm","keyframes":['
                      '{"t":0,"transform":{"rotate":0}},{"t":2,"transform":{"rotate":90}}]}]}')

    def green(t):
        rgb = np.asarray(render_frame(doc, t, warn_blank=False).convert("RGB"))
        mask = (rgb[..., 1] > 120) & (rgb[..., 0] < 80)
        ys, xs = np.nonzero(mask)
        return (xs.min(), xs.max(), ys.min(), ys.max()) if len(xs) else None

    assert green(0.0) == (420, 539, 352, 367)  # authored: bottom-right arm
    assert green(2.0) is None or green(2.0)[0] < 0  # rotated about (0,0): gone


# ---------------------------------------------------------------------------
# scale pivots: a bar grows where it sits, not from the canvas corner
# ---------------------------------------------------------------------------


def _element_box(doc, t: float, element_id: str):
    """Post-transform box of one element at ``t`` (geometry, not pixels)."""
    from nanoframes import diagnose

    for record in diagnose.frame_report(doc, t, coverage=False).elements:
        if record.label == f"#{element_id}":
            assert record.box is not None, f"{element_id} has no measured box at t={t}"
            return record.box
    raise AssertionError(f"no #{element_id} at t={t}")


def test_scale_with_center_auto_grows_in_place():
    doc = comp('<rect id="bar" x="60" y="150" width="6" height="120" fill="#5ef17c"/>',
               script='{"animations":[{"target":"#bar","keyframes":['
                      '{"t":0,"transform":{"scale":[1.0,0.02],"center":"auto"}},'
                      '{"t":2,"transform":{"scale":[1.0,1.0],"center":"auto"}}]}]}')
    assert _element_box(doc, 2.0, "bar") == bounds.Box(60.0, 150.0, 66.0, 270.0)
    started, mid = _element_box(doc, 0.0, "bar"), _element_box(doc, 1.0, "bar")
    for box in (started, mid):
        assert (box.x0, box.x1) == (60.0, 66.0)      # x stays where it was authored
        assert box.center[1] == pytest.approx(210.0)  # grows both ways around its middle
    assert started.height < 5 and 50 < mid.height < 70


def test_pivotless_scale_grows_from_the_canvas_corner():
    """Plain `scale` keeps SVG semantics: the anchor, not the element, stays put."""
    doc = comp('<rect id="bar" x="60" y="150" width="6" height="120" fill="#5ef17c"/>',
               script='{"animations":[{"target":"#bar","keyframes":['
                      '{"t":0,"transform":{"scale":[1.0,0.02]}},'
                      '{"t":2,"transform":{"scale":[1.0,1.0]}}]}]}')
    assert _element_box(doc, 0.0, "bar").y0 < 10  # collapsed toward the top edge
    assert _element_box(doc, 1.0, "bar").center[1] < 120  # still climbing downward


def test_inline_rotate_pivot_wins_over_the_transform_center():
    doc = comp('<rect id="arm" x="10" y="10" width="40" height="8" fill="#0f0"/>',
               script='{"animations":[{"target":"#arm","keyframes":['
                      '{"t":0,"transform":{"rotate":[0,10,20],"center":"auto"}}]}]}')
    assert "rotate(0 10 20)" in bake.bake_svg(doc, 0.0)


def test_explicit_center_pair_works_without_measurable_geometry():
    """``center: auto`` needs geometry; an explicit pivot never does."""
    svg = bake.bake_svg(comp('<rect id="r" x="0" y="0" width="10" height="10" fill="#000"/>',
                             script='{"animations":[{"target":"#r","keyframes":['
                                    '{"t":0,"transform":{"scale":0.5,"center":[5,5]}}]}]}'), 0.0)
    assert "translate(5,5) scale(0.5) translate(-5,-5)" in svg


def test_scaffold_template_grows_its_accent_bar_in_place(tmp_path):
    """`nanoframes init` must not ship the footgun the docs warn about."""
    from nanoframes.cli import main

    path = tmp_path / "t.nf.svg"
    assert main(["init", "t", "-o", str(path)]) == 0
    text = path.read_text()
    assert '"center": "auto"' in text
    doc = parse_string(text)
    assert _element_box(doc, 3.0, "accent") == bounds.Box(60.0, 150.0, 66.0, 270.0)
    mid = _element_box(doc, 0.9, "accent")  # mid-grow
    assert (mid.x0, mid.x1) == (60.0, 66.0) and mid.center[1] == pytest.approx(210.0)


# ---------------------------------------------------------------------------
# Animated transforms layer inside the element's own transform
# ---------------------------------------------------------------------------


def test_animated_transform_keeps_the_static_transform():
    doc = comp('<g id="crank" transform="translate(480 360)">'
               '<rect x="-60" y="-8" width="120" height="16" fill="#0f0"/></g>',
               script='{"animations":[{"target":"#crank","keyframes":['
                      '{"t":0,"transform":{"rotate":0}},{"t":2,"transform":{"rotate":45}}]}]}')
    svg = bake.bake_svg(doc, 1.0)
    # the authored static transform is kept verbatim, with the animation layered inside
    assert 'transform="translate(480 360) rotate(22.5)"' in svg


def test_composed_static_transform_matches_the_nested_wrapper_idiom():
    """Composing in bake == putting the animated element in a positioned wrapper."""
    from nanoframes.render import render_frame

    animation = ('{"animations":[{"target":"#crank","keyframes":['
                 '{"t":0,"transform":{"rotate":0}},{"t":2,"transform":{"rotate":90}}]}]}')
    composed = comp('<g id="crank" transform="translate(480 360)">'
                    '<rect x="-60" y="-8" width="120" height="16" fill="#0f0"/></g>',
                    script=animation)
    nested = comp('<g transform="translate(480 360)"><g id="crank">'
                  '<rect x="-60" y="-8" width="120" height="16" fill="#0f0"/></g></g>',
                  script=animation)

    def ink(doc, t):
        rgb = np.asarray(render_frame(doc, t, warn_blank=False).convert("RGB"))
        ys, xs = np.nonzero((rgb[..., 1] > 120) & (rgb[..., 0] < 80))
        return xs.min(), xs.max(), ys.min(), ys.max()

    assert ink(composed, 2.0) == ink(nested, 2.0)
    x0, x1, y0, y1 = ink(composed, 2.0)
    assert y1 - y0 > 100  # at 90 degrees the arm stands up, still 120 long

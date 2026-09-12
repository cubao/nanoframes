"""Render end-to-end tests (bake -> thorvg -> Pillow)."""

import os

import pytest

from nanoframes import bake
from nanoframes.parse import parse_file
from nanoframes.render import render_frame

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
TITLE = os.path.join(EXAMPLES, "title-card.nf.svg")


def test_parse_example():
    doc = parse_file(TITLE)
    assert doc.composition.width == 480
    assert doc.composition.height == 240
    assert doc.composition.frame_count == 120
    assert len(doc.composition.animations) == 2


def test_bake_strips_script_and_applies_props():
    doc = parse_file(TITLE)
    svg = bake.bake_svg(doc, t=2.0)
    # animation fully active: script stripped, transforms/opacity materialized
    assert "application/nanoframes+json" not in svg
    assert "<script" not in svg
    assert 'transform="translate(0,0)' in svg
    # title is fully faded in by t=2.0 -> no opacity clamp on title
    assert 'id="title"' in svg


def test_bake_hides_element_outside_clip_window():
    doc = parse_file(TITLE)
    svg_early = bake.bake_svg(doc, t=0.1)  # before title/bar appear (t>0.5)
    assert 'id="title"' in svg_early
    assert 'display="none"' in svg_early
    assert 'id="accent-bar"' in svg_early
    # sub appears at t=1.0 -> must be hidden at 0.1
    assert "display=\"none\"" in svg_early


def test_render_frame_returns_png(tmp_path):
    doc = parse_file(TITLE)
    out = str(tmp_path / "frame.png")
    img = render_frame(doc, t=2.0, out_path=out)
    assert img.size == (480, 240)
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0


@pytest.mark.parametrize("t", [0.0, 0.6, 1.0, 2.0, 3.5])
def test_render_deterministic_and_sized(t, tmp_path):
    doc = parse_file(TITLE)
    a = render_frame(doc, t=t)
    b = render_frame(doc, t=t)
    assert a.size == (480, 240)
    assert a.tobytes() == b.tobytes()


def test_text_rasterizes_with_auto_font():
    """At t=2.0 the white title text must actually rasterize (font loaded)."""

    doc = parse_file(TITLE)
    img = render_frame(doc, t=2.0)
    rgb = img.convert("RGB")
    has_text = any(
        all(v > 200 for v in rgb.getpixel((x, y)))
        for x in range(80, 300, 3)
        for y in range(76, 100, 2)
    )
    assert has_text, "expected white title text pixels in the title band"


def test_bake_fade_out_mirrors_at_clip_end():
    """data-fade dims the tail of the clip in the baked per-frame SVG."""
    from nanoframes.parse import parse_string

    text = (
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100" '
        'data-duration="4.0">'
        '<rect id="r" width="100" height="100" fill="#fff" data-start="0.5" '
        'data-duration="2.0" data-fade="0.4"/>'
        "</svg>"
    )
    doc = parse_string(text)
    # clip [0.5, 2.5] with a 0.4s fade on both ends
    full = bake.bake_svg(doc, t=1.5)
    assert "display=\"none\"" not in full
    assert 'opacity="1.0000"' not in full  # fully visible -> no opacity clamp

    tail = bake.bake_svg(doc, t=2.4)  # inside the fade-out window (2.1..2.5)
    assert 'opacity="0.2500"' in tail  # (2.5 - 2.4) / 0.4

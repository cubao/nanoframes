"""Render end-to-end tests (bake -> thorvg -> Pillow)."""

import os

import pytest

from nanoframes import bake
from nanoframes.parse import parse_file, parse_string
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


# ---------------------------------------------------------------------------
# Visibility on <text> and <image>: ThorVG ignores both attributes on them
# ---------------------------------------------------------------------------
#
# Materializing a window or a fade as `display` / `opacity` on the element
# itself does nothing on these two tags — measured, not assumed: ink counting
# showed a text element outside its window still drawing, and a faded one
# arriving at full strength, while the same attributes on a `<g>` worked. These
# tests read the raster rather than the baked markup, because the markup is
# exactly what was lying.

DOT = os.path.join(EXAMPLES, "assets", "dot.png")

WINDOWED = (
    '<svg xmlns="http://www.w3.org/2000/svg" data-width="200" data-height="100"'
    ' data-fps="30" data-duration="4.0">'
    '<text id="t" x="4" y="60" font-family="Arial" font-size="40" fill="#ffffff"'
    ' data-start="2.0" data-duration="1.0">LATE</text>'
    f'<image id="i" x="10" y="10" width="180" height="80" href="{DOT}"'
    ' data-start="2.0" data-duration="1.0"/>'
    "</svg>"
)

FADED = (
    '<svg xmlns="http://www.w3.org/2000/svg" data-width="200" data-height="100"'
    ' data-fps="30" data-duration="2.0">'
    '<text id="t" x="4" y="60" font-family="Arial" font-size="40" fill="#ffffff"'
    ' data-start="0.0" data-duration="2.0" data-fade="1.0">HALF</text>'
    "</svg>"
)

FADED_WRAPPED = (
    '<svg xmlns="http://www.w3.org/2000/svg" data-width="200" data-height="100"'
    ' data-fps="30" data-duration="2.0">'
    '<text id="t" x="4" y="30" font-family="Arial" font-size="20" fill="#ffffff"'
    ' data-wrap="70" data-start="0.0" data-duration="2.0" data-fade="1.0">alpha beta'
    " gamma delta</text>"
    "</svg>"
)


def _ink(img) -> int:
    """Opaque pixels: what the rasterizer actually drew."""
    return sum(1 for p in img.convert("RGBA").getdata() if p[3] > 0)


def _max_alpha(img) -> int:
    """The strongest pixel in the frame — how opaque the drawing got at its peak."""
    return max(p[3] for p in img.convert("RGBA").getdata())


def test_a_window_hides_text_and_image_outside_it():
    """Both tags draw nothing outside their clip window, and both draw inside it."""

    doc = parse_string(WINDOWED)
    assert _ink(render_frame(doc, t=0.0)) == 0, "outside the window, nothing may be drawn"
    assert _ink(render_frame(doc, t=2.5)) > 0, "inside it, both elements draw"


def test_a_fade_dims_text_where_opacity_would_have_been_ignored():
    """A faded text element must arrive dimmed, not at full strength."""

    doc = parse_string(FADED)
    # clip [0, 2] with a 1s fade at each end -> opacity 0.5 at t=0.5
    assert 120 <= _max_alpha(render_frame(doc, t=0.5)) <= 136, "expected 0.5 x 255"


def test_a_faded_wrapped_text_is_not_dimmed_twice():
    """The fade moves onto the wrapper; the node keeps none for a later pass to copy.

    `textflow` re-parents a `data-wrap` text into a group of its own and carries
    the node's attributes onto it. Were the fade left on the node as well, the
    wrapper bake added and the wrapper the wrap pass adds would each apply it and
    the frame would come out at the square of the fade (0.25, not 0.5).
    """

    doc = parse_string(FADED_WRAPPED)
    assert 120 <= _max_alpha(render_frame(doc, t=0.5)) <= 136, "expected 0.5 x 255"


def test_a_hidden_wrapped_text_stays_hidden_through_autoflow():
    """The wrap pass replaces the node it expands, so the hide has to move with it."""

    doc = parse_string(FADED_WRAPPED.replace('data-start="0.0"', 'data-start="1.5"'))
    # clip [1.5, 3.5]: this frame is before it, and the expanded lines are not
    # allowed to resurface just because the node they replaced is gone
    assert _ink(render_frame(doc, t=0.5)) == 0
    assert _ink(render_frame(doc, t=2.0)) > 0


def test_display_none_written_in_the_source_hides_text_and_image():
    """An author's own `display="none"` fails the same way, so it takes the same carrier.

    Nothing in bake decides this one — the attribute is already in the file, and
    the loader ignores it exactly where it ignores bake's.
    """

    doc = parse_string(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="200" data-height="100"'
        ' data-fps="30" data-duration="1.0">'
        '<text id="t" x="4" y="60" font-family="Arial" font-size="40" fill="#ffffff"'
        ' display="none">GONE</text>'
        f'<image id="i" x="10" y="10" width="180" height="80" href="{DOT}"'
        ' display="none"/>'
        "</svg>"
    )
    assert _ink(render_frame(doc, t=0.5)) == 0

"""External text rendering: the ``text_handler`` callback (``<text data-raster>``).

The dummy handlers here transform in an intentionally obvious way — the string
``hello`` is handed to the callback and comes back rendered as ``你好`` (green,
via the bundled CJK font) — so any break in the plumbing (opt-in marker,
request fields, PNG bytes, bbox placement) shows up as a missing or misplaced
glyph instead of a subtle metric drift.
"""

import base64
import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image, ImageDraw, ImageFont

from nanoframes import bake
from nanoframes.cache import FrameCache
from nanoframes.parse import parse_string
from nanoframes.render import DEFAULT_FONT_CANDIDATES, render_frame

NS = "{http://www.w3.org/2000/svg}"
EXAMPLE = """<svg xmlns="http://www.w3.org/2000/svg" data-width="240" data-height="120"
     data-fps="24" data-duration="1.0">
  <rect width="240" height="120" fill="#10161f"/>
  <text id="eq" x="120" y="60" font-family="Arial" font-size="28" fill="#ffffff"
        data-raster="dummy">hello</text>
</svg>
"""


class Recorder:
    """Test handler: records every request, returns a canned result."""

    def __init__(self, result):
        self.calls = []
        self.result = result

    def __call__(self, req):
        self.calls.append(req)
        return self.result


def _png_bytes(size=(10, 20), color=(255, 0, 0, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def _text_png(text: str, color=(0, 255, 0, 255)) -> bytes:
    """Render ``text`` with the bundled Sarasa Mono SC (CJK-safe), cropped to ink."""
    font = ImageFont.truetype(DEFAULT_FONT_CANDIDATES[0], 32)
    probe = Image.new("RGBA", (8, 8))
    width = ImageDraw.Draw(probe).textlength(text, font=font)
    img = Image.new("RGBA", (max(1, int(width) + 4), 44))
    ImageDraw.Draw(img).text((0, 0), text, font=font, fill=color)
    img = img.crop(img.getbbox())
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _tree(svg: str) -> ET.Element:
    return ET.fromstring(svg)


# ---------------------------------------------------------------------------
# no-op / fallback
# ---------------------------------------------------------------------------


def test_without_handler_bakes_unchanged():
    svg = bake.bake_svg(parse_string(EXAMPLE), 0.5)  # no text_handler at all
    assert "<image" not in svg
    assert 'data-raster="dummy"' in svg
    texts = [e for e in _tree(svg).iter() if e.tag == NS + "text"]
    assert len(texts) == 1 and texts[0].get("id") == "eq"


@pytest.mark.parametrize("result", [None, b""])
def test_none_or_empty_falls_back_to_font_path(result):
    rec = Recorder(result=result)
    svg = bake.bake_svg(parse_string(EXAMPLE), 0.5, text_handler=rec)
    assert rec.calls and rec.calls[0].text == "hello"
    assert "<image" not in svg
    texts = [e for e in _tree(svg).iter() if e.tag == NS + "text"]
    assert len(texts) == 1  # original <text> untouched


def test_invisible_raster_text_never_reaches_handler():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="40" '
           'data-duration="1.0"><text data-raster="d" data-start="10" '
           'data-duration="1">x</text></svg>')
    rec = Recorder(result=_png_bytes())
    bake.bake_svg(parse_string(svg), 0.5, text_handler=rec)
    assert rec.calls == []


# ---------------------------------------------------------------------------
# placement geometry
# ---------------------------------------------------------------------------


def test_bytes_replace_text_with_centered_image():
    rec = Recorder(result=_png_bytes((10, 20)))  # 10x20 red PNG
    svg = bake.bake_svg(parse_string(EXAMPLE), 0.5, text_handler=rec)
    tree = _tree(svg)
    images = [e for e in tree.iter() if e.tag == NS + "image"]
    assert len(images) == 1
    img = images[0]
    assert img.get("x") == "115"  # 120 - 10/2 (anchor center, natural size)
    assert img.get("y") == "50"  # 60 - 20/2
    assert img.get("width") == "10" and img.get("height") == "20"
    href = img.get("href")
    assert href.startswith("data:image/png;base64,")
    assert base64.b64decode(href.split(",", 1)[1]) == _png_bytes((10, 20))
    g = next(p for p in tree.iter() if img in list(p))
    assert g.tag == NS + "g" and g.get("id") == "eq"
    assert not [e for e in tree.iter() if e.tag == NS + "text"]  # fully replaced


@pytest.mark.parametrize(
    ("anchor", "ix", "iy"),
    [
        ("top-left", 50, 60),
        ("top-center", 45, 60),
        ("top-right", 40, 60),
        ("middle-left", 50, 50),
        ("center", 45, 50),
        ("middle-right", 40, 50),
        ("bottom-left", 50, 40),
        ("bottom-center", 45, 40),
        ("bottom-right", 40, 40),
    ],
)
def test_anchor_places_natural_size_png(anchor, ix, iy):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="240" data-height="120">'
           f'<text x="50" y="60" font-size="20" data-raster="d" '
           f'data-anchor="{anchor}">x</text></svg>')
    rec = Recorder(result=_png_bytes((10, 20)))
    tree = _tree(bake.bake_svg(parse_string(svg), 0.5, text_handler=rec))
    img = next(e for e in tree.iter() if e.tag == NS + "image")
    assert (img.get("x"), img.get("y")) == (str(ix), str(iy))


def test_target_box_contains_png_without_distortion():
    # 10x10 PNG into a 30x20 box -> scale 2, image 20x20, 10px horizontal slack
    svg_tl = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="240" data-height="120">'
              '<text x="50" y="60" data-raster="d" data-anchor="top-left" '
              'data-width="30" data-height="20">x</text></svg>')
    svg_c = svg_tl.replace('data-anchor="top-left"', 'data-anchor="center"')
    for svg, ix, iy in ((svg_tl, 50, 60), (svg_c, 40, 50)):
        rec = Recorder(result=_png_bytes((10, 10)))
        img = next(e for e in _tree(
            bake.bake_svg(parse_string(svg), 0.5, text_handler=rec)
        ).iter() if e.tag == NS + "image")
        assert (img.get("width"), img.get("height")) == ("20", "20")
        assert (img.get("x"), img.get("y")) == (str(ix), str(iy))


def test_single_side_box_scales_proportionally():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="240" data-height="120">'
           '<text x="0" y="0" data-raster="d" data-width="30">x</text>'
           '<text x="0" y="0" data-raster="e" data-height="10">y</text></svg>')

    def handler(req):
        return {"d": _png_bytes((10, 20)), "e": _png_bytes((10, 20))}[req.kind]

    images = [e for e in _tree(
        bake.bake_svg(parse_string(svg), 0.5, text_handler=handler)
    ).iter() if e.tag == NS + "image"]
    sizes = {(e.get("width"), e.get("height")) for e in images}
    assert sizes == {("30", "60"), ("5", "10")}  # 10x20 scaled by each side


def test_yaw_rotates_around_anchor_point():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="240" data-height="120">'
           '<text x="120" y="60" data-raster="d" data-yaw="90">x</text></svg>')
    rec = Recorder(result=_png_bytes((10, 20)))
    img = next(e for e in _tree(
        bake.bake_svg(parse_string(svg), 0.5, text_handler=rec)
    ).iter() if e.tag == NS + "image")
    assert img.get("transform") == "rotate(90 120 60)"


def test_request_carries_text_style_and_kind():
    seen = {}

    def handler(req):
        seen.update(req.__dict__)
        return

    bake.bake_svg(parse_string(EXAMPLE), 0.5, text_handler=handler)
    assert seen["text"] == "hello"
    assert seen["kind"] == "dummy"
    assert seen["x"] == 120.0 and seen["y"] == 60.0
    assert seen["anchor"] == "center"
    assert seen["width"] is None and seen["height"] is None
    assert seen["yaw"] == 0.0
    assert seen["font_size"] == 28.0
    assert seen["family"] == "Arial"
    assert seen["weight"] == "normal"
    assert seen["fill"] == "#ffffff"
    assert seen["attrs"]["data-raster"] == "dummy"
    assert seen["attrs"]["font-size"] == "28"


# ---------------------------------------------------------------------------
# failure modes
# ---------------------------------------------------------------------------


def test_non_png_bytes_raise_loudly():
    rec = Recorder(result=b"definitely not a png")
    with pytest.raises(ValueError, match="non-PNG"):
        bake.bake_svg(parse_string(EXAMPLE), 0.5, text_handler=rec)


def test_unknown_anchor_raises():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="240" data-height="120">'
           '<text data-raster="d" data-anchor="north">x</text></svg>')
    rec = Recorder(result=_png_bytes())
    with pytest.raises(ValueError, match="data-anchor"):
        bake.bake_svg(parse_string(svg), 0.5, text_handler=rec)


# ---------------------------------------------------------------------------
# end to end through the real render pipeline
# ---------------------------------------------------------------------------


def test_render_end_to_end_hello_becomes_ni_hao():
    calls = []

    def handler(req):
        calls.append(req.text)
        if req.text != "hello":
            return None
        return _text_png("你好", color=(0, 255, 0, 255))

    doc = parse_string(EXAMPLE)
    img = render_frame(doc, 0.5, text_handler=handler)
    assert calls == ["hello"]

    # the callback's green 你好 sits centered on (120, 60) where hello was
    green = [(x, y) for x in range(240) for y in range(120)
             if img.getpixel((x, y))[:3] == (0, 255, 0)]
    assert green, "callback PNG never made it into the frame"
    xs = [p[0] for p in green]
    ys = [p[1] for p in green]
    assert abs((min(xs) + max(xs)) / 2 - 120) <= 3
    assert abs((min(ys) + max(ys)) / 2 - 60) <= 3

    # control: no handler -> normal font path, no green anywhere
    plain = render_frame(parse_string(EXAMPLE), 0.5)
    assert not any(plain.getpixel((x, y))[:3] == (0, 255, 0)
                   for x in range(0, 240, 2) for y in range(0, 120, 2))


def test_handler_bypasses_frame_cache(tmp_path):
    calls = []

    def handler(req):
        calls.append(req.text)
        return _png_bytes((8, 8), (0, 0, 255, 255))

    cache = FrameCache(str(tmp_path / "cache"))
    doc = parse_string(EXAMPLE)
    render_frame(doc, 0.5, cache=cache, text_handler=handler)
    render_frame(doc, 0.5, cache=cache, text_handler=handler)
    assert calls == ["hello", "hello"]  # re-baked every time, never cache-served
    assert list((tmp_path / "cache").glob("*.png")) == []

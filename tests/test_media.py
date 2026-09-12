"""Embedded media: aspect-correct ``data-fit`` placement.

ThorVG ignores ``preserveAspectRatio`` and stretches every picture to its
declared box (probed), so the aspect-correct geometry has to be computed here.
These tests pin the computed geometry and the pixels that reach the canvas.
"""

from PIL import Image

from nanoframes import bake, media
from nanoframes.lint import lint_string
from nanoframes.parse import parse_file
from nanoframes.render import render_frame
from nanoframes.xmlutil import local_name

CANVAS = ('<svg xmlns="http://www.w3.org/2000/svg"'
          ' xmlns:xlink="http://www.w3.org/1999/xlink"'
          ' data-width="200" data-height="200" data-fps="30" data-duration="1.0">')


def _png(tmp_path, size=(100, 50), name="wide.png"):
    path = tmp_path / name
    Image.new("RGBA", size, (255, 0, 0, 255)).save(path)
    return path


def _comp(tmp_path, attrs="", box=(0, 0, 200, 200), size=(100, 50), declared=True):
    src = _png(tmp_path, size)
    x, y, w, h = box
    dims = f' width="{w}" height="{h}"' if declared else ""
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        CANVAS
        + f'<image id="pic" xlink:href="{src.name}" x="{x}" y="{y}"{dims} {attrs}/>'
        + '</svg>',
        encoding="utf-8",
    )
    return str(comp)


def _image_node(root):
    return next(n for n in root.iter() if local_name(n.tag) == "image")


def _alpha_bbox(doc):
    return render_frame(doc, 0.0).convert("RGBA").getchannel("A").getbbox()


# --- the geometry the modes compute -----------------------------------------

def test_contain_letterboxes_a_wide_source_in_a_square_box(tmp_path):
    """2:1 source in a 200x200 box keeps 2:1: 200x100, centred at y=50."""
    doc = parse_file(_comp(tmp_path, 'data-fit="contain"'))
    node = _image_node(bake.bake_tree(doc, 0.0))
    assert (node.get("x"), node.get("y")) == ("0", "50")
    assert (node.get("width"), node.get("height")) == ("200", "100")
    assert _alpha_bbox(doc) == (0, 50, 200, 150)


def test_cover_fills_the_box_and_is_clipped_to_it(tmp_path):
    """2:1 source in a 100x100 box grows to 200x100 and is clipped back to the box."""
    doc = parse_file(_comp(tmp_path, 'data-fit="cover"', box=(50, 50, 100, 100)))
    node = _image_node(bake.bake_tree(doc, 0.0))
    assert (node.get("width"), node.get("height")) == ("200", "100")
    assert _alpha_bbox(doc) == (50, 50, 150, 150)


def test_cover_emits_one_clip_path_around_the_image(tmp_path):
    doc = parse_file(_comp(tmp_path, 'data-fit="cover"', box=(50, 50, 100, 100)))
    root = bake.bake_tree(doc, 0.0)
    clips = [n for n in root.iter() if local_name(n.tag) == "clipPath"]
    assert len(clips) == 1
    rect = next(n for n in clips[0].iter() if local_name(n.tag) == "rect")
    assert (rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height")) == (
        "50", "50", "100", "100")
    groups = [n for n in root.iter()
              if local_name(n.tag) == "g" and n.get("clip-path")]
    assert groups, "no clipping group wrapped the image"
    assert groups[0].get("clip-path") == f"url(#{clips[0].get('id')})"
    assert any(local_name(c.tag) == "image" for c in groups[0])


# --- the no-op paths ---------------------------------------------------------

def test_stretch_and_absent_fit_leave_the_geometry_alone(tmp_path):
    """The default must not move: every existing composition renders unchanged."""
    for attrs in ("", 'data-fit="stretch"'):
        doc = parse_file(_comp(tmp_path, attrs))
        node = _image_node(bake.bake_tree(doc, 0.0))
        assert (node.get("x"), node.get("y")) == ("0", "0")
        assert (node.get("width"), node.get("height")) == ("200", "200")
        assert _alpha_bbox(doc) == (0, 0, 200, 200)  # stretched, as before


def test_xlink_href_survives_baking(tmp_path):
    """`xlink:href` must keep its literal prefix: ThorVG's loader ignores `ns1:href`."""
    doc = parse_file(_comp(tmp_path))  # _comp writes xlink:href
    svg = bake.bake_svg(doc, 0.0)
    assert 'xlink:href="' in svg and "ns1:href" not in svg
    assert _alpha_bbox(doc) == (0, 0, 200, 200)


def test_fit_without_a_declared_box_is_a_no_op(tmp_path):
    """No width/height means no box to fit into: leave the source at its own size."""
    doc = parse_file(_comp(tmp_path, 'data-fit="contain"', declared=False))
    root = bake.bake_tree(doc, 0.0)
    node = _image_node(root)
    assert node.get("width") is None and node.get("height") is None


def test_fit_on_a_remote_or_inlined_source_is_skipped(tmp_path):
    """A URL / data URI has no file to measure, so nothing is rewritten."""
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        CANVAS + '<image id="pic" xlink:href="https://example.com/a.png"'
        ' x="0" y="0" width="200" height="200" data-fit="contain"/></svg>',
        encoding="utf-8",
    )
    node = _image_node(bake.bake_tree(parse_file(str(comp)), 0.0))
    assert node.get("width") == "200" and node.get("height") == "200"


# --- the helpers -------------------------------------------------------------

def test_intrinsic_size_reads_the_file_and_survives_a_missing_one(tmp_path):
    path = _png(tmp_path, size=(64, 32))
    assert media.intrinsic_size(str(path)) == (64, 32)
    assert media.intrinsic_size(str(tmp_path / "nope.png")) is None


def test_unknown_fit_mode_is_reported_by_lint(tmp_path):
    comp = _comp(tmp_path, 'data-fit="fill"')
    codes = [f.code for f in lint_string(open(comp).read())]
    assert "image.bad_fit" in codes


def test_known_fit_modes_are_not_reported(tmp_path):
    for mode in media.FIT_MODES:
        comp = _comp(tmp_path, f'data-fit="{mode}"')
        codes = [f.code for f in lint_string(open(comp).read())]
        assert "image.bad_fit" not in codes

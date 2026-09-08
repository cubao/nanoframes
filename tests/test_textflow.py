"""Text auto-layout tests: measured background chips, wrapping, along-curve.

These exercise the renderer-exact ``Measurer`` path through ``bake_svg`` (the
same code the render pipeline uses), asserting the geometry bake injects.
"""

import re
import xml.etree.ElementTree as ET

import pytest

from nanoframes import bake
from nanoframes.measure import Measurer
from nanoframes.parse import parse_string

NS = "{http://www.w3.org/2000/svg}"
EXAMPLE = """<svg xmlns="http://www.w3.org/2000/svg" data-width="480" data-height="200"
     data-fps="24" data-duration="1.0">
  <text id="chip" x="40" y="80" font-family="Arial" font-size="24" fill="#fff"
        data-bg="#123456" data-bg-pad-x="10" data-bg-pad-y="6" data-bg-rx="8">Brake</text>
  <text id="wrap" x="40" y="140" font-family="Arial" font-size="20" fill="#fff"
        data-wrap="100">left middle right</text>
  <text id="arc" x="0" y="0" font-family="Arial" font-size="22"
        data-curve-d="M 20 120 C 100 40, 240 40, 320 120">ARC</text>
</svg>
"""


def _texts(tree):
    return [e for e in tree.iter() if e.tag == NS + "text"]


def test_unmeasured_composition_bakes_unchanged():
    """Without a Measurer, auto-layout is a no-op (plain bake unchanged)."""
    doc = parse_string(EXAMPLE)
    svg = bake.bake_svg(doc, 0.5, measurer=None)
    assert "data-bg" in svg
    assert svg.count("<rect ") == 0  # no injected chip


def test_bg_injects_measured_rect_behind_text():
    tree = ET.fromstring(bake.bake_svg(parse_string(EXAMPLE), 0.5, measurer=Measurer()))
    rects = [e for e in tree.iter() if e.tag == NS + "rect"]
    assert len(rects) == 1
    r = rects[0]
    assert r.get("rx") == "8"
    assert float(r.get("width")) > 0 and float(r.get("height")) > 0
    assert r.get("fill") == "#123456"
    # chip sits directly behind the text (text is the next sibling)
    idx = list(tree.iter()).index(r)
    following = list(tree.iter())[idx + 1]
    assert following.tag == NS + "text" and following.get("id") == "chip"


def test_wrap_splits_into_stacked_lines():
    tree = ET.fromstring(bake.bake_svg(parse_string(EXAMPLE), 0.5, measurer=Measurer()))
    lines = [e for e in _texts(tree) if e.get("id", "").startswith("wrap")]
    assert len(lines) >= 2
    ys = [float(e.get("y")) for e in lines]
    assert len(set(ys)) == len(ys)
    assert all(ys[i + 1] > ys[i] for i in range(len(ys) - 1))


def test_curve_emits_rotated_per_char():
    tree = ET.fromstring(bake.bake_svg(parse_string(EXAMPLE), 0.5, measurer=Measurer()))
    chars = [e for e in _texts(tree) if "rotate(" in (e.get("transform") or "")]
    assert len(chars) == 3  # A R C
    assert all(e.text in "ARC" for e in chars)


def test_measure_cli(capsys, tmp_path):
    from nanoframes.cli import main
    import shutil
    src = "examples/text-measure.nf.svg"
    code = main(["measure", src])
    out = capsys.readouterr().out
    assert "width(px)" in out
    assert "chip-a" in out
    assert code == 0
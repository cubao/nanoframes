"""Text auto-layout tests: measured background chips, wrapping, along-curve.

These exercise the renderer-exact ``Measurer`` path through ``bake_svg`` (the
same code the render pipeline uses), asserting the geometry bake injects.
"""

import xml.etree.ElementTree as ET

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


# --- CJK wrapping -----------------------------------------------------------

CJK_FAMILY = "Sarasa Mono SC"
CJK_TEXT = "确定性视频渲染需要在另一台机器上保持一致"


def _cjk_style(size=20.0):
    return {"family": CJK_FAMILY, "weight": "normal", "size": size,
            "letter_spacing": 0.0}


def _wrap_texts(content, max_width, size=20.0):
    from nanoframes.textflow import _wrap
    return [t for t, _ in _wrap(content, _cjk_style(size), max_width, Measurer())]


def test_cjk_wrap_does_not_insert_spaces():
    """Whitespace is a separator between units, never a unit.

    The first version of the breaker re-joined its units with ``" "``. Latin
    units are words so that read correctly, but CJK units are single ideographs,
    so a wrapped Chinese line came out as 确 定 性 视 — a space between every
    pair of glyphs. No test wrapped CJK, so nothing caught it.
    """
    lines = _wrap_texts(CJK_TEXT, 120)
    assert len(lines) > 1, "expected the text to wrap at 120px"
    assert "".join(lines) == CJK_TEXT  # nothing dropped, nothing added
    assert all(" " not in line for line in lines)


def test_cjk_wrap_keeps_latin_words_whole():
    """A space that survives to a line is still a space; words are never split.

    Joining the lines back is lossy for whitespace alone — the separator that
    lands on a break is dropped, which is what a break is. Everything else has
    to survive.
    """
    lines = _wrap_texts("混合 mixed 文本 wrap test", 110)
    joined = "".join(lines)
    assert joined.replace(" ", "") == "混合mixed文本wraptest"
    assert all(word in joined for word in ("mixed", "wrap", "test"))
    assert any(" " in line for line in lines)
    assert "混 合" not in joined  # no space invented between ideographs


def test_every_wrapped_line_fits_its_box():
    """The one invariant the breaker has: no line wider than the box."""
    m = Measurer()
    for max_width in (60.0, 80.0, 120.0, 200.0):
        for line in _wrap_texts(CJK_TEXT, max_width):
            ink = m.ink(line, CJK_FAMILY, "normal", 20.0, 0.0)
            assert ink.right_dx - ink.left_dx + 1 <= max_width, (max_width, line)


def test_kinsoku_no_line_starts_with_a_closing_character():
    """行頭禁則: 追い出し sends the previous unit down with the offender.

    At 80px (four 20px ideographs) the break falls immediately before ``,``,
    which may not open a line, so the line before it gives up its last unit.
    """
    lines = _wrap_texts("一二三四，五六七八", 80)
    assert lines == ["一二三", "四，五六", "七八"]
    from nanoframes.textflow import _NO_START
    assert all(line[0] not in _NO_START for line in lines if line)


def test_kinsoku_no_line_ends_with_an_opening_character():
    """行末禁則: the mirror rule, for brackets that may not end a line."""
    lines = _wrap_texts("一二三（四五六）七八", 80)
    from nanoframes.textflow import _NO_END
    assert all(line[-1] not in _NO_END for line in lines if line)


def test_a_word_wider_than_the_box_is_broken_not_overflowed():
    """With no break inside it, a unit is split by character.

    Before this, an over-long word was placed whole on a line of its own —
    silently wider than the box it was told to fit. A box narrower than a
    single glyph still cannot be satisfied; this is the case above it.
    """
    style = {"family": "Arial", "weight": "normal", "size": 20.0,
             "letter_spacing": 0.0}
    from nanoframes.textflow import _wrap
    m = Measurer()
    lines = [t for t, _ in _wrap("the screenshot jumps", style, 120, m)]
    assert len(lines) > 2
    for line in lines:
        ink = m.ink(line, "Arial", "normal", 20.0, 0.0)
        assert ink.right_dx - ink.left_dx + 1 <= 120, line


def test_cjk_wrap_through_bake_emits_no_spaces():
    """End to end: the emitted SVG carries the same defect the unit test names."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="400" '
           'data-height="200"><rect width="400" height="200" fill="#000"/>'
           f'<text id="w" x="20" y="60" font-family="{CJK_FAMILY}" font-size="20" '
           f'fill="#fff" data-wrap="120">{CJK_TEXT}</text></svg>')
    tree = ET.fromstring(bake.bake_svg(parse_string(svg), 0.0, measurer=Measurer()))
    lines = [e.text or "" for e in _texts(tree) if e.get("id", "").startswith("w")]
    assert len(lines) > 1
    assert "".join(lines) == CJK_TEXT
    assert all(" " not in line for line in lines)


def test_curve_emits_rotated_per_char():
    tree = ET.fromstring(bake.bake_svg(parse_string(EXAMPLE), 0.5, measurer=Measurer()))
    chars = [e for e in _texts(tree) if "rotate(" in (e.get("transform") or "")]
    assert len(chars) == 3  # A R C
    assert all(e.text in "ARC" for e in chars)


def test_a_hidden_text_carries_its_hide_onto_the_group_that_replaces_it():
    """These passes remove the node they expand, so its `display` must move too.

    Re-parenting without copying it would draw lines the frame had hidden:
    `data-wrap` and `data-curve-*` both build a fresh `<g>` and drop the original.
    Called directly on the parsed tree, with no bake wrapper in between, so this
    reads the group the pass itself builds.
    """
    from nanoframes import textflow

    for attr in ('data-wrap="100"', 'data-curve-d="M 20 120 C 100 40, 240 40, 320 120"'):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="480" data-height="200"'
               f' data-duration="1.0"><text id="t" x="40" y="140" font-family="Arial"'
               f' font-size="20" fill="#fff" {attr} display="none">left middle'
               " right</text></svg>")
        root = parse_string(svg).root
        textflow.apply_text_autoflow(root, Measurer())
        group = next(e for e in root.iter() if e.tag == NS + "g")
        assert group.get("display") == "none", f"{attr} lost the hide"
        assert _texts(group), "the pass still expanded the text"


def test_fit_shrinks_font_size_to_width():
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" data-width="400" data-height="80"><rect width="400" height="80" fill="#000"/><text id="t" x="10" y="60" font-family="Arial" font-size="48" fill="#fff" data-fit="120" data-fit-min="8">MUCH TOO WIDE</text></svg>'''
    tree = ET.fromstring(bake.bake_svg(parse_string(svg), 0.5, measurer=Measurer()))
    t = [e for e in _texts(tree) if e.get("id") == "t"][0]
    size = float(t.get("font-size"))
    assert size < 48
    # fitted single line must actually fit: measure its ink width
    m = Measurer().ink(t.text or "", "Arial", "normal", size)
    assert (m.right_dx - m.left_dx + 1) <= 120


def test_measure_cli(capsys, tmp_path):
    from nanoframes.cli import main
    src = "examples/text-measure.nf.svg"
    code = main(["measure", src])
    out = capsys.readouterr().out
    assert "width(px)" in out
    assert "chip-a" in out
    assert code == 0


def test_bundled_maple_mono_cn_font_present_and_monospace():
    """The bundled monospace CJK font exists, is monospace, and is known-safe."""
    import os

    from nanoframes.render import DEFAULT_FONT_CANDIDATES

    bundled = [p for p in DEFAULT_FONT_CANDIDATES if "SarasaMonoSC" in p]
    assert bundled, "bundled Sarasa Mono SC not in default candidates"
    path = bundled[0]
    assert os.path.exists(path), f"bundled font missing: {path}"

    from nanoframes.fonts import family_name
    family, style = family_name(path)
    assert family == "Sarasa Mono SC"

    from fontTools.ttLib import TTFont
    f = TTFont(path)
    assert f["post"].isFixedPitch, "Sarasa Mono SC must be monospace"
    assert 0x4E2D in f.getBestCmap(), "Sarasa Mono SC must have CJK (中 U+4E2D)"
    # ligature-driving features must be stripped
    if "GSUB" in f:
        tags = {r.FeatureTag for r in f["GSUB"].table.FeatureList.FeatureRecord}
        assert not ({"liga", "clig", "rlig", "dlig", "calt"} & tags), f"ligature features remain: {tags}"

"""Diagnostics: lint's geometry findings, `nanoframes debug`, loop seams."""

from __future__ import annotations

import contextlib
import io
import json

import pytest

from nanoframes import diagnose, timeline
from nanoframes.cli import main
from nanoframes.lint import lint_string
from nanoframes.parse import parse_string
from nanoframes.render import measurer as render_measurer
from nanoframes.render import render_frame


def comp(body: str, *, width: int = 400, height: int = 200, duration: float = 2.0,
         fps: int = 30, script: str = ""):
    timeline_json = f'<script type="application/nanoframes+json"><![CDATA[{script}]]></script>' \
        if script else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" data-width="{width}" data-height="{height}"'
        f' data-fps="{fps}" data-duration="{duration}">{body}{timeline_json}</svg>'
    )


def warnings(findings) -> str:
    return "\n".join(str(f) for f in findings if f.severity == "warning")


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(argv)
    return code, buf.getvalue()


# ---------------------------------------------------------------------------
# lint: geometry that renders as nothing
# ---------------------------------------------------------------------------


def test_lint_flags_geometry_that_never_lands_on_the_canvas():
    doc = comp('<rect id="lost" x="-900" y="-900" width="100" height="100" fill="#f00"/>')
    out = warnings(lint_string(doc))
    assert "#lost" in out and "never lands" in out


def test_lint_stays_quiet_when_an_element_only_starts_off_canvas():
    """Sliding in from outside the canvas is legitimate (the frame clips it)."""
    doc = comp('<rect id="in" x="0" y="80" width="80" height="40" fill="#0f0"/>',
               script='{"animations":[{"target":"#in","keyframes":['
                      '{"t":0,"transform":{"translate":[-300,0]}},'
                      '{"t":0.5,"transform":{"translate":[0,0]}}]}]}')
    assert "never lands" not in warnings(lint_string(doc))


def test_lint_reports_the_deepest_offending_element_only():
    doc = comp('<g id="outer" transform="translate(-800 -800)">'
               '<rect id="inner" width="50" height="50" fill="#f00"/></g>')
    out = warnings(lint_string(doc))
    assert out.count("never lands") == 1
    assert "#outer" in out


def test_lint_warns_about_a_pivotless_rotate_far_from_the_origin():
    doc = comp('<rect id="arm" x="160" y="150" width="120" height="16" fill="#0f0"/>',
               script='{"animations":[{"target":"#arm","keyframes":['
                      '{"t":0,"transform":{"rotate":0}},{"t":2,"transform":{"rotate":90}}]}]}')
    out = warnings(lint_string(doc))
    assert "no pivot" in out and "#arm" in out and 'center": "auto"' in out


@pytest.mark.parametrize("transform", [
    '{"rotate": [0, 220, 158]}',                        # inline pivot
    '{"rotate": 0, "center": "auto"}',                  # pivot from the transform
    '{"rotate": 0, "center": [220, 158]}',              # explicit pivot
])
def test_lint_accepts_rotates_that_carry_a_pivot(transform):
    keyframe = '{"t": %s, "transform": %s}'
    script = ('{"animations":[{"target":"#arm","keyframes":['
              + keyframe % ("0", transform) + "," + keyframe % ("2", transform) + "]}]}")
    doc = comp('<rect id="arm" x="160" y="150" width="120" height="16" fill="#0f0"/>',
               script=script)
    assert "no pivot" not in warnings(lint_string(doc))


def test_lint_warns_about_a_pivotless_scale_that_would_grow_from_the_corner():
    doc = comp('<rect id="bar" x="300" y="400" width="200" height="40" fill="#0f0"/>',
               script='{"animations":[{"target":"#bar","keyframes":['
                      '{"t":0,"transform":{"scale":[1.0,0.02]}},'
                      '{"t":2,"transform":{"scale":[1.0,1.0]}}]}]}')
    out = warnings(lint_string(doc))
    assert "scale has no pivot" in out and "#bar" in out


def test_lint_allows_rotating_around_the_origin_inside_the_element():
    """A rect authored from (0,0) rotating on its own corner is a normal idiom."""
    doc = comp('<rect id="fan" x="0" y="0" width="120" height="16" fill="#0f0"/>',
               script='{"animations":[{"target":"#fan","keyframes":['
                      '{"t":0,"transform":{"rotate":0}},{"t":2,"transform":{"rotate":90}}]}]}')
    assert "no pivot" not in warnings(lint_string(doc))


def test_lint_warns_when_transform_shapes_do_not_match_across_keyframes():
    doc = comp('<rect id="arm" x="160" y="150" width="120" height="16" fill="#0f0"/>',
               script='{"animations":[{"target":"#arm","keyframes":['
                      '{"t":0,"transform":{"rotate":0}},'
                      '{"t":2,"transform":{"rotate":[90,220,158]}}]}]}')
    out = warnings(lint_string(doc))
    assert "more than one shape" in out


def test_lint_errors_on_a_transform_bake_cannot_express():
    """A rotate object (the shape this API dropped) must fail `check`, not the render."""
    doc = comp('<rect id="arm" x="160" y="150" width="120" height="16" fill="#0f0"/>',
               script='{"animations":[{"target":"#arm","keyframes":['
                      '{"t":0,"transform":{"rotate":{"deg":0,"center":"auto"}}}]}]}')
    findings = lint_string(doc)
    errors = [str(f) for f in findings if f.severity == "error"]
    assert any("rotate takes degrees" in e for e in errors), findings


@pytest.mark.parametrize("transform", [
    '{"scale": true}',
    '{"center": 5}',
    '{"scale": [1,2,3]}',
    '{"translate": 5}',
    '{"rotate": [45]}',
    '{"rotate": [0,1,2,3]}',
])
def test_lint_errors_on_malformed_transform_values(transform):
    """Whatever bake refuses, `check` must name first — never a mid-render crash."""
    from nanoframes.bake import transform_string

    doc = comp('<rect id="r" x="10" y="10" width="40" height="40" fill="#0f0"/>',
               script='{"animations":[{"target":"#r","keyframes":['
                      '{"t":0,"transform":' + transform + '}]}]}')
    assert any(f.severity == "error" for f in lint_string(doc)), transform
    with pytest.raises(ValueError):
        transform_string(json.loads(transform))


# ---------------------------------------------------------------------------
# diagnose: per-frame boxes, clip scan, loop seam
# ---------------------------------------------------------------------------


def test_frame_report_places_and_flags_elements():
    doc = parse_string(comp('<rect id="bg" width="400" height="200" fill="#fff"/>'
                            '<circle id="lost" cx="900" cy="90" r="10" fill="#f00"/>'))
    report = diagnose.frame_report(doc, 0.0)
    by_label = {el.label: el for el in report.elements}
    assert by_label["#bg"].status == "on-canvas"
    assert by_label["#lost"].status == "off-canvas"
    assert by_label["#lost"].blank
    assert report.coverage == pytest.approx(1.0)


def test_frame_report_marks_an_element_hidden_by_its_clip_window():
    doc = parse_string(comp('<rect id="later" width="400" height="200" fill="#fff"'
                            ' data-start="1.0" data-duration="1.0"/>'))
    early = {el.label: el for el in diagnose.frame_report(doc, 0.0).elements}
    assert not early["#later"].painted


def test_clip_scan_flags_an_element_that_is_never_visible():
    doc = parse_string(comp('<rect id="ok" width="400" height="200" fill="#fff"/>'
                            '<rect id="lost" x="-900" y="0" width="10" height="10" fill="#f00"/>'))
    scan = diagnose.scan_clip(doc)
    assert [e.label for e in scan.never_visible] == ["#lost"]
    assert "#lost" in [e.label for e in scan.reported()]


# --- the contribution probe (`debug --pixels`) ------------------------------

BURIED = ('<rect width="400" height="200" fill="#101820"/>'
          '<text id="caption" x="20" y="100" font-family="Arial" font-size="28"'
          ' fill="#ffffff">CAPTION</text>'
          '<rect id="curtain" width="400" height="200" fill="#101820"/>')


def test_probe_finds_an_element_covered_by_a_later_sibling():
    """The one fault no box measure can see.

    `caption` is on the canvas by every arithmetic reading; a later sibling
    paints over it. Its box is unchanged, its status is `on-canvas`, and nothing
    of it reaches the picture.
    """
    doc = parse_string(comp(BURIED))
    plain = {e.label: e for e in diagnose.frame_report(
        doc, 0.0, measurer=render_measurer()).elements}
    assert plain["#caption"].status == "on-canvas"
    assert plain["#caption"].contributes is None, "no probe, no claim"

    report = diagnose.frame_report(doc, 0.0, measurer=render_measurer(), pixels=True)
    by_label = {e.label: e for e in report.elements}
    assert by_label["#caption"].contributes is False
    assert by_label["#caption"].covered
    assert by_label["#curtain"].contributes is True
    assert not by_label["#curtain"].covered
    assert [e.label for e in report.covered] == ["#caption"]


def test_probe_does_not_claim_anything_about_elements_it_did_not_probe():
    """A hidden or unmeasured element has no contribution to report."""
    doc = parse_string(comp('<rect id="bg" width="400" height="200" fill="#fff"/>'
                            '<rect id="later" x="0" y="0" width="10" height="10" fill="#f00"'
                            ' data-start="1.0" data-duration="1.0"/>'))
    report = diagnose.frame_report(doc, 0.0, measurer=render_measurer(), pixels=True)
    by_label = {e.label: e for e in report.elements}
    assert not by_label["#later"].painted
    assert by_label["#later"].contributes is None


def test_probe_only_reports_buried_elements_the_author_named():
    """A check that fires on a background rectangle every time gets ignored."""
    doc = parse_string(comp(BURIED))
    report = diagnose.frame_report(doc, 0.0, measurer=render_measurer(), pixels=True)
    unnamed_buried = [e for e in report.elements
                      if e.contributes is False and not e.has_id]
    assert unnamed_buried, "the fixture's background is genuinely covered"
    assert all(not e.covered for e in unnamed_buried)


def test_probe_leaves_the_tree_as_it_found_it():
    """Hiding is done in place, so a second probe has to see the same frame."""
    doc = parse_string(comp(BURIED))
    first = diagnose.frame_report(doc, 0.0, measurer=render_measurer(), pixels=True)
    second = diagnose.frame_report(doc, 0.0, measurer=render_measurer(), pixels=True)
    assert ([e.label for e in first.covered] == [e.label for e in second.covered]
            == ["#caption"])


def test_cli_debug_pixels_reports_the_buried_element(tmp_path):
    src = tmp_path / "buried.nf.svg"
    src.write_text(comp(BURIED), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["debug", str(src), "--pixels", "--no-scan"])
    assert code == 0
    text = out.getvalue()
    assert "buried" in text and "#caption" in text


def test_cli_debug_pixels_json_carries_the_verdict(tmp_path):
    src = tmp_path / "buried.nf.svg"
    src.write_text(comp(BURIED), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["debug", str(src), "--pixels", "--no-scan", "--json"])
    payload = json.loads(out.getvalue())
    assert payload["frame"]["covered"] == ["#caption"]
    assert payload["identity"]["components"]["source"]
    for element in payload["frame"]["elements"]:
        assert "contributes" in element


def test_loop_seam_closed_when_motion_finishes_by_the_last_frame():
    """A loop closes at duration - 1/fps (the last rendered frame), not at duration."""
    doc = parse_string(comp('<rect id="p" width="40" height="40" fill="#0f0"/>', duration=2.0,
                            script='{"animations":[{"target":"#p","keyframes":['
                                   '{"t":0,"transform":{"translate":[0,0]}},'
                                   '{"t":1,"transform":{"translate":[120,0]}},'
                                   '{"t":1.966667,"transform":{"translate":[0,0]}},'
                                   '{"t":2.0,"transform":{"translate":[0,0]}}]}]}'))
    assert timeline.last_frame_time(doc.composition) == pytest.approx(1.966667)
    seam = diagnose.loop_seam(doc)
    assert seam.closed, f"seam should be closed, got {seam.differing_fraction}"
    assert seam.last_t == pytest.approx(1.966667)


def test_loop_seam_open_when_motion_ends_after_the_last_frame():
    """Closing at `duration` instead of the last frame leaves a visible jump."""
    doc = parse_string(comp('<rect id="p" width="40" height="40" fill="#0f0"/>', duration=2.0,
                            script='{"animations":[{"target":"#p","keyframes":['
                                   '{"t":0,"transform":{"translate":[0,0]}},'
                                   '{"t":2.0,"transform":{"translate":[120,0]}}]}]}'))
    seam = diagnose.loop_seam(doc)
    assert not seam.closed
    assert seam.differing_fraction > 0.0


# ---------------------------------------------------------------------------
# CLI + the blank-frame guard
# ---------------------------------------------------------------------------


def test_cli_debug_reports_frames_and_clip_scan(tmp_path):
    path = tmp_path / "c.nf.svg"
    path.write_text(comp('<rect id="ok" width="400" height="200" fill="#fff"/>'
                         '<rect id="lost" x="-900" y="0" width="10" height="10" fill="#f00"/>'))
    code, out = run(["debug", str(path), "--t", "0"])
    assert code == 0
    assert "#lost" in out and "off-canvas" in out
    assert "clip scan" in out
    assert "draws nothing in any sampled frame" in out


def test_cli_debug_loop_reports_the_seam(tmp_path):
    path = tmp_path / "c.nf.svg"
    path.write_text(comp('<rect id="p" width="40" height="40" fill="#0f0"/>',
                         script='{"animations":[{"target":"#p","keyframes":['
                                '{"t":0,"transform":{"translate":[0,0]}},'
                                '{"t":2.0,"transform":{"translate":[120,0]}}]}]}'))
    code, out = run(["debug", str(path), "--loop", "--no-scan"])
    assert code == 0
    assert "loop seam" in out and "OPEN" in out
    assert "duration - 1/fps" in out


def test_render_frame_warns_when_the_frame_is_blank():
    doc = parse_string(comp('<rect id="later" width="400" height="200" fill="#fff"'
                            ' data-start="1.0" data-duration="1.0"/>'))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        render_frame(doc, 0.0)
    message = buf.getvalue()
    assert "fully transparent" in message
    assert "nanoframes debug" in message


def test_render_frame_is_quiet_for_a_normal_frame():
    doc = parse_string(comp('<rect id="bg" width="400" height="200" fill="#fff"/>'))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        render_frame(doc, 0.0)
    assert buf.getvalue() == ""

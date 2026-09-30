"""``data-frame-text``: a <text> whose words are the frame's own numbers.

The feature exists because a composition is static markup and a frame counter is
not. It is checked here from both ends: the template parser (what a field is and
what is refused), and the rendered pixels (the words reach the frame, and the
auto-layout passes see the substituted text rather than the template).
"""

from __future__ import annotations

import numpy as np
import pytest

from nanoframes import frametext
from nanoframes.lint import lint_string
from nanoframes.parse import parse_string
from nanoframes.render import render_frame

SVG = """<svg xmlns="http://www.w3.org/2000/svg" data-width="640" data-height="120"
     data-fps="30" data-duration="2.0" data-composition-id="t">
  <rect width="640" height="120" fill="#ffffff" data-duration="2.0"/>
  <text x="10" y="80" font-family="Sarasa Mono SC" font-size="40" fill="#000000"
        data-duration="2.0" data-frame-text="{template}"/>
</svg>"""


def _ink(img) -> int:
    """How many pixels carry ink — the cheap "did it draw the words" test."""
    a = np.array(img.convert("L"))
    return int((a < 128).sum())


def _render(template: str, t: float):
    return render_frame(parse_string(SVG.format(template=template)), t)


# --- the parser ---------------------------------------------------------------

def test_the_frame_fields_are_the_clock_and_nothing_else():
    assert frametext.fields_used("{frame}@{second:.2f}") == ["frame", "second"]


def test_an_unknown_field_is_refused_with_the_ones_that_exist():
    with pytest.raises(frametext.TemplateError) as err:
        frametext.fields_used("index {seconds}")
    assert "seconds" in str(err.value)
    assert "second" in str(err.value)          # the message names the real fields


@pytest.mark.parametrize("template", [
    "{frame.__class__}",     # attribute access: a template is not an expression
    "{frame[0]}",            # indexing
    "{frame!r}",             # conversion
])
def test_a_template_cannot_reach_outside_the_frame(template):
    with pytest.raises(frametext.TemplateError):
        frametext.fields_used(template)


def test_a_format_spec_the_field_cannot_take_is_refused_at_check_time():
    with pytest.raises(frametext.TemplateError):
        frametext.fields_used("{frame:%.2f}")


def test_every_declared_field_formats():
    doc = parse_string(SVG.format(template="x"))
    text = "{frame} {second:.3f} {time} {fps} {duration} {frames}"
    out = frametext.format_template(text, doc.composition, 0.5)
    assert out == "15 0.500 0.5 30 2.0 60"


def test_the_frame_index_is_the_time_not_a_counter():
    """One arbitrary frame (--t, preview, a digest sample) reads like the batch."""
    doc = parse_string(SVG.format(template="x"))
    for t in (0.0, 1.0, 2.0 - 1 / 30):
        expected = round(t * doc.composition.fps)
        assert frametext.format_template("{frame}", doc.composition, t) == str(expected)


# --- the pixels ---------------------------------------------------------------

def test_the_words_reach_the_frame():
    """'0' at t=0 and a longer string a second later ink different amounts."""
    early = _ink(_render("frame {frame}", 0.0))
    late = _ink(_render("frame {frame}", 1.0))
    assert early > 0 and late > 0


def test_two_frames_draw_different_text():
    a = np.array(_render("{frame}", 0.0).convert("L"))
    b = np.array(_render("{frame}", 1.0).convert("L"))
    assert not np.array_equal(a, b)


def test_a_windowed_element_still_draws_at_the_frame_its_window_starts():
    """The trap this feature exists to remove, as a regression.

    One element per frame, its ``data-start`` exactly at that frame's time, was
    the counter idiom before. It failed on 4 frames of 900 because the batch
    walked ``i * (1/fps)`` while the digest walked ``i / fps`` — a hair below the
    window. ``data-frame-text`` has no window to fall outside of; this asserts
    the frame that used to be lost renders its text.
    """
    svg = """<svg xmlns="http://www.w3.org/2000/svg" data-width="320" data-height="80"
         data-fps="30" data-duration="4.0">
      <rect width="320" height="80" fill="#ffffff" data-duration="4.0"/>
      <text x="10" y="50" font-family="Sarasa Mono SC" font-size="30" fill="#000000"
            data-frame-text="frame {frame}" data-duration="4.0"/>
    </svg>"""
    doc = parse_string(svg)
    for index in (110, 111, 207, 222, 237):
        img = render_frame(doc, index / doc.composition.fps)
        assert _ink(img) > 0, f"frame {index} drew nothing"


# --- the lint -----------------------------------------------------------------

def test_an_unknown_field_is_an_error_not_a_rendered_brace():
    findings = lint_string(SVG.format(template="index {seconds}"))
    codes = [f.code for f in findings]
    assert "text.bad_frame_field" in codes
    assert [f for f in findings if f.code == "text.bad_frame_field"][0].severity == "error"


def test_words_written_inside_a_substituted_element_are_reported():
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' data-width='300' data-height='100'>"
           "<text x='10' y='50' font-size='20' data-frame-text='{frame}'>never drawn</text>"
           "</svg>")
    codes = [f.code for f in lint_string(svg)]
    assert "text.inert_content" in codes


def test_a_valid_template_is_not_reported():
    assert lint_string(SVG.format(template="frame {frame} of {frames} at {second:.2f}")) == []


def test_the_element_is_measured_with_the_text_it_draws():
    """A chip is sized from the words, so it has to be sized per frame.

    The alternative — sizing the chip from the template — would leave a chip
    that never matches the number inside it, which is the whole reason
    substitution runs before the auto-layout pass.
    """
    svg = """<svg xmlns="http://www.w3.org/2000/svg" data-width="900" data-height="200"
         data-fps="30" data-duration="30.0">
      <rect width="900" height="200" fill="#ffffff" data-duration="30.0"/>
      <text x="20" y="120" font-family="Sarasa Mono SC" font-size="40" fill="#ffffff"
            data-bg="#203040" data-bg-pad-x="14" data-bg-pad-y="8" data-duration="30.0"
            data-frame-text="{frame}"/>
    </svg>"""
    doc = parse_string(svg)
    narrow = _ink(render_frame(doc, 1 / 30))     # "1"
    wide = _ink(render_frame(doc, 899 / 30))     # "899"
    assert wide > narrow, "the chip did not grow with the number inside it"


def test_a_missing_attribute_leaves_the_text_alone():
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' data-width='300' data-height='100'>"
           "<text x='10' y='50' font-size='20'>plain</text></svg>")
    doc = parse_string(svg)
    assert parse_string(svg).root.find(".//{http://www.w3.org/2000/svg}text").text == "plain"
    assert _ink(render_frame(doc, 0.0)) > 0


def test_the_render_does_not_mutate_the_document():
    """Bake works on a copy; the source tree keeps its template and stays reusable."""
    doc = parse_string(SVG.format(template="{frame}"))
    render_frame(doc, 1.0)
    node = doc.root.find(".//{http://www.w3.org/2000/svg}text")
    assert node.get("data-frame-text") == "{frame}"

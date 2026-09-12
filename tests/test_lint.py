"""Lint findings: the arithmetic checks that turn a silent failure into a name.

Each case here is a composition that renders *something valid and wrong* (or a
budget the author asked to be held to) and the finding that has to name it.
"""

from nanoframes.lint import lint_string

CANVAS = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="200" data-height="100"'
          ' data-fps="30" data-duration="4.0"{extra}>')


def _codes(findings):
    return [f.code for f in findings]


def _script(animations: str) -> str:
    return ('<script type="application/nanoframes+json"><![CDATA['
            '{"animations": [' + animations + ']}]]></script>')


# --- animation outside the element's visible window -------------------------

def test_animation_entirely_outside_visibility_window_is_reported():
    """The element appears after its animation finished: the motion is never seen."""
    svg = (CANVAS.format(extra="")
           + '<rect id="box" x="10" y="10" width="20" height="20" fill="#000"'
             ' data-start="2.0" data-duration="2.0"/>'
           + _script('{"target": "#box", "keyframes":'
                     ' [{"t": 0, "opacity": 0}, {"t": 0.5, "opacity": 1}]}')
           + '</svg>')
    assert "animation.outside_visibility" in _codes(lint_string(svg))


def test_animation_inside_the_visible_window_is_clean():
    svg = (CANVAS.format(extra="")
           + '<rect id="box" x="10" y="10" width="20" height="20" fill="#000"'
             ' data-start="0.0" data-duration="4.0"/>'
           + _script('{"target": "#box", "keyframes":'
                     ' [{"t": 0, "opacity": 0}, {"t": 0.5, "opacity": 1}]}')
           + '</svg>')
    assert "animation.outside_visibility" not in _codes(lint_string(svg))


# --- safe margin (opt-in) ---------------------------------------------------

def test_safe_margin_flags_text_near_the_edge():
    svg = (CANVAS.format(extra=' data-safe-margin="30"')
           + '<text id="t" x="10" y="60" font-family="Arial" font-size="20"'
             ' fill="#ffffff">hi</text></svg>')
    findings = lint_string(svg)
    assert "layout.outside_safe_margin" in _codes(findings)
    assert next(f for f in findings if f.code == "layout.outside_safe_margin").element == "#t"


def test_safe_margin_ignores_the_background():
    """A full-bleed rect touches every edge by design; title-safe is about text."""
    svg = (CANVAS.format(extra=' data-safe-margin="30"')
           + '<rect id="bg" width="200" height="100" fill="#000000"/>'
           + '<text id="t" x="60" y="60" font-family="Arial" font-size="20"'
             ' fill="#ffffff">hi</text></svg>')
    assert "layout.outside_safe_margin" not in _codes(lint_string(svg))


def test_safe_margin_is_off_unless_declared():
    svg = (CANVAS.format(extra="")
           + '<text id="t" x="10" y="60" font-family="Arial" font-size="20"'
             ' fill="#ffffff">hi</text></svg>')
    assert "layout.outside_safe_margin" not in _codes(lint_string(svg))


# --- palette budget (opt-in) ------------------------------------------------

THREE_COLORS = ('<rect width="10" height="10" fill="#111111"/>'
                '<rect width="10" height="10" fill="#222222"/>'
                '<rect width="10" height="10" fill="#333333"/>')


def test_palette_budget_flags_too_many_colors():
    svg = CANVAS.format(extra=' data-palette-budget="2"') + THREE_COLORS + '</svg>'
    assert "design.palette_over_budget" in _codes(lint_string(svg))


def test_palette_budget_within_limit_is_clean():
    svg = CANVAS.format(extra=' data-palette-budget="4"') + THREE_COLORS + '</svg>'
    assert "design.palette_over_budget" not in _codes(lint_string(svg))


def test_palette_budget_counts_colors_a_keyframe_animates_to():
    svg = (CANVAS.format(extra=' data-palette-budget="2"')
           + '<rect id="r" width="10" height="10" fill="#111111"/>'
           + '<rect width="10" height="10" fill="#222222"/>'
           + _script('{"target": "#r", "keyframes":'
                     ' [{"t": 0, "fill": "#333333"}, {"t": 1, "fill": "#111111"}]}')
           + '</svg>')
    assert "design.palette_over_budget" in _codes(lint_string(svg))


def test_palette_budget_is_off_unless_declared():
    svg = CANVAS.format(extra="") + THREE_COLORS + '</svg>'
    assert "design.palette_over_budget" not in _codes(lint_string(svg))


def test_palette_ignores_non_colors():
    """``none`` / paint servers are not palette entries."""
    svg = (CANVAS.format(extra=' data-palette-budget="0"')
           + '<rect width="10" height="10" fill="none" stroke="none"/>'
           + '<rect width="10" height="10" fill="url(#grad)"/></svg>')
    assert "design.palette_over_budget" not in _codes(lint_string(svg))

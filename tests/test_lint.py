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


def test_inert_visibility_is_reported():
    """ThorVG draws the element anyway — probed, not assumed.

    An author who wrote `visibility="hidden"` has asked for something the
    renderer does not do, and gets a wrong frame with no error.
    """
    svg = (CANVAS.format(extra="")
           + '<rect id="hid" width="10" height="10" fill="#f00" visibility="hidden"/>'
           + '</svg>')
    findings = lint_string(svg)
    assert "render.inert_attribute" in _codes(findings)
    assert any(f.element == "hid" for f in findings)


def test_visibility_visible_is_not_reported():
    """`visible` is the default, so writing it changes nothing to warn about."""
    svg = (CANVAS.format(extra="")
           + '<rect id="ok" width="10" height="10" fill="#0f0" visibility="visible"/>'
           + '</svg>')
    assert "render.inert_attribute" not in _codes(lint_string(svg))


# --- timing written on a <tspan> --------------------------------------------

def _span(span_attrs: str, *, text_attrs: str = "", script: str = "") -> str:
    """One `<text>` holding one span — the shape every case below varies."""
    return (CANVAS.format(extra="")
            + f'<text id="host" x="10" y="50" font-family="Arial" font-size="20"'
              f'{text_attrs}><tspan id="late"{span_attrs}>LATE</tspan></text>'
            + (f'<script type="application/nanoframes+json"><![CDATA[{script}]]></script>'
               if script else "")
            + "</svg>")


def test_a_window_on_a_tspan_is_reported():
    """The window is baked as display="none" on the span — which this loader ignores.

    Measured by ink count at the same opacity: a span "hidden" by its window draws
    identically to one that is not, so the author gets a caption that is on screen
    for the whole composition while every arithmetic reading agrees with the markup.
    """
    findings = lint_string(_span(' data-start="1.0" data-duration="1.0"'))
    assert "render.inert_tspan" in _codes(findings)
    finding = next(f for f in findings if f.code == "render.inert_tspan")
    assert finding.element == "#late"
    assert "data-start='1.0'" in finding.message and "data-duration='1.0'" in finding.message


def test_a_fade_on_a_tspan_is_reported():
    """`data-fade` rides on `opacity`, which is ignored on a span for the same reason."""
    assert "render.inert_tspan" in _codes(lint_string(_span(' data-fade="0.5"')))


def test_a_plain_span_is_not_reported():
    """A span that declares no timing has asked for nothing the renderer cannot do."""
    assert "render.inert_tspan" not in _codes(lint_string(_span("")))


def test_a_span_window_covering_the_whole_composition_is_not_reported():
    """Declaring the full timeline is a no-op window: there is no failure to name.

    The canvas runs 4s, so `data-start="0" data-duration="4"` excludes no time —
    warning here would be a false positive, and the check exists to be trusted.
    """
    assert "render.inert_tspan" not in _codes(
        lint_string(_span(' data-start="0" data-duration="4.0" data-fade="0"')))


def test_the_same_window_on_the_text_is_not_reported():
    """The remedy the finding proposes has to be clean itself.

    bake hands the attributes to a `<g>` around the `<text>`, where this loader
    does read them, so moving the timing up is the fix.
    """
    svg = (CANVAS.format(extra="")
           + '<text id="host" x="10" y="50" font-family="Arial" font-size="20"'
             ' data-start="1.0" data-duration="1.0">LATE</text></svg>')
    assert "render.inert_tspan" not in _codes(lint_string(svg))


def test_an_animation_aimed_at_a_tspan_is_reported():
    """Every keyframed property is written onto the span and dropped.

    `opacity` is the measured case: the span is left at `opacity="0.0000"` at t=0
    and still draws at full strength.
    """
    script = ('{"animations": [{"target": "#late", "keyframes":'
              ' [{"t": 0, "opacity": 0}, {"t": 1, "opacity": 1}]}]}')
    findings = lint_string(_span("", script=script))
    assert "render.inert_tspan" in _codes(findings)
    finding = next(f for f in findings if f.code == "render.inert_tspan")
    assert finding.element == "#late"
    assert "#late" in finding.message


def test_an_animation_aimed_at_the_text_is_not_reported():
    """Animating the `<text>` is the fix, and the check has to stay quiet on it."""
    script = ('{"animations": [{"target": "#host", "keyframes":'
              ' [{"t": 0, "opacity": 0}, {"t": 1, "opacity": 1}]}]}')
    assert "render.inert_tspan" not in _codes(lint_string(_span("", script=script)))

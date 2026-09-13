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
    assert any(f.element == "#hid" for f in findings)


def test_visibility_visible_is_not_reported():
    """`visible` is the default, so writing it changes nothing to warn about."""
    svg = (CANVAS.format(extra="")
           + '<rect id="ok" width="10" height="10" fill="#0f0" visibility="visible"/>'
           + '</svg>')
    assert "render.inert_attribute" not in _codes(lint_string(svg))


# --- text properties ThorVG accepts and ignores ------------------------------

def _run(attrs: str = "", *, tag: str = "text", wrap: str = "") -> str:
    """One `<text>` (or a `<g>` around one) carrying `attrs` — the shape varies."""
    inside = (f'<{tag} id="t" x="10" y="50" font-family="Arial" font-size="20"'
              f'{attrs}>HELLO WORLD</{tag}>')
    return CANVAS.format(extra="") + (f'<g id="wrap"{wrap}>{inside}</g>' if wrap else inside) \
        + "</svg>"


def test_text_anchor_middle_and_end_are_reported():
    """Measured: every run is left-aligned at its x whatever the anchor says.

    Ink count and pixel colour are identical to the same run without the
    attribute, so a "centred" title still starts at its x — a claim about the
    frame the renderer does not honour.
    """
    for anchor in ("middle", "end"):
        findings = lint_string(_run(f' text-anchor="{anchor}"'))
        finding = next(f for f in findings if f.code == "render.inert_attribute")
        assert finding.element == "#t"
        assert f"text-anchor='{anchor}'" in finding.message


def test_text_anchor_start_is_not_reported():
    """`start` is the initial value: it asks for nothing to warn about."""
    assert "render.inert_attribute" not in _codes(lint_string(_run(' text-anchor="start"')))


def test_letter_spacing_is_reported():
    """Measured: the run keeps its natural spacing, so tracked text reads as one word."""
    for value in ("6", "6px", "0.2em"):
        findings = lint_string(_run(f' letter-spacing="{value}"'))
        finding = next(f for f in findings if f.code == "render.inert_attribute")
        assert "letter-spacing" in finding.message and value in finding.message


def test_a_zero_or_normal_letter_spacing_is_not_reported():
    """`normal` and a zero length ask for no spacing, which is what the run gets."""
    for value in ("normal", "0", "0px", "0em"):
        assert "render.inert_attribute" not in _codes(
            lint_string(_run(f' letter-spacing="{value}"'))), value


def test_the_two_text_properties_are_reported_separately():
    """One moves a run and one widens it: two claims, two findings.

    Folding them together would say one thing about two different failures — the
    same reason the drawing-nothing family (`<marker>`, `<pattern>`) and the
    paints-black one (`rgba()`) keep their own wording in the gap table.
    """
    findings = [f for f in lint_string(_run(' text-anchor="middle" letter-spacing="6"'))
                if f.code == "render.inert_attribute"]
    assert len(findings) == 2
    assert any("text-anchor='middle'" in f.message for f in findings)
    assert any("letter-spacing='6'" in f.message for f in findings)


def test_an_inert_text_property_on_a_group_over_text_is_reported():
    """Nothing is inherited into the glyphs, so a wrapper's declaration is just as dead."""
    findings = lint_string(_run(' letter-spacing="6"', wrap=' letter-spacing="6"'))
    assert any(f.element == "#wrap" and "letter-spacing" in f.message for f in findings)


def test_an_inert_text_property_with_no_text_under_it_is_not_reported():
    """A declaration on a node with no glyphs in scope says nothing about the frame."""
    svg = (CANVAS.format(extra="")
           + '<rect id="bar" width="10" height="10" fill="#f00" text-anchor="middle"'
             ' letter-spacing="6"/></svg>')
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


def test_a_span_under_a_landing_text_is_not_reported():
    """A span has no box of its own, so a span that draws is never called blank.

    A span used to be measured at its own ``x``/``y`` — which it cannot have,
    every attribute on a span being inert — so a span that the frame plainly
    draws (479 ink pixels) reported geometry at the origin and was called a
    drawing of nothing.
    """
    assert lint_string(_span("")) == []


def test_a_span_under_an_off_canvas_text_is_still_reported():
    """Nothing is hidden: the line is named, because the line is what has geometry.

    The check must not learn "spans are exempt" — the characters a span carries
    are drawn, and a line that never lands has to be named whether or not a span
    sits in it.
    """
    svg = (CANVAS.format(extra="")
           + '<text id="host" x="10" y="-200" font-family="Arial" font-size="20"'
             ' fill="#ffffff">WORD <tspan id="late">LATE</tspan></text></svg>')
    findings = lint_string(svg)
    assert "geometry.never_on_canvas" in _codes(findings)
    assert next(f for f in findings
                if f.code == "geometry.never_on_canvas").element == "#host"


# --- font-family that selects no loaded face ---------------------------------

def _text(attrs: str = "") -> str:
    """One `<text>` run — the shape every case below varies."""
    return (CANVAS.format(extra="")
            + f'<text x="10" y="50" font-size="20"{attrs}>HELLO WORLD</text></svg>')


def test_a_css_font_stack_is_reported():
    """The whole value is one font name, so a portable-looking stack selects nothing.

    ThorVG's loader has no list semantics and no per-glyph fallback: it compares
    the entire value against the faces it loaded, and draws with the first one
    when nothing matches. Measured by ink count, `Arial, sans-serif` draws
    exactly the bundled Sarasa face — so the markup says Arial and the picture
    says Sarasa, with no error anywhere.
    """
    findings = lint_string(_text(' font-family="Arial, \'DejaVu Sans\', sans-serif"'))
    assert "render.unresolved_font_family" in _codes(findings)


def test_the_warning_names_the_face_that_actually_draws():
    """The fallback is read off the candidate list, not written into the message.

    Which face a run lands on is a property of `fonts.DEFAULT_FONT_CANDIDATES`
    order; a message that hardcoded a name would keep saying Sarasa after the
    list changed.
    """
    from nanoframes.lint import loaded_font_names

    _, fallback = loaded_font_names()
    finding = next(f for f in lint_string(_text(' font-family="NoSuchFontAnywhere"'))
                   if f.code == "render.unresolved_font_family")
    assert fallback in finding.message
    assert "NoSuchFontAnywhere" in finding.message


def test_a_value_that_is_not_an_exact_name_is_reported():
    """Case, quoting and partial names all miss — measured, one ink count each."""
    for value in ("sarasa mono sc", "'Sarasa Mono SC'", "Sarasa", "monospace"):
        findings = lint_string(_text(f' font-family="{value}"'))
        assert "render.unresolved_font_family" in _codes(findings), value


def test_an_exact_loaded_name_is_not_reported():
    """The fix, and the one declaration the check has to stay quiet on.

    The bundled face is always loaded and always first, which is why this name
    works on every host and the test does not depend on the machine's fonts.
    """
    assert "render.unresolved_font_family" not in _codes(
        lint_string(_text(' font-family="Sarasa Mono SC"')))


def test_surrounding_whitespace_does_not_make_a_name_unresolved():
    """Trimmed by the loader — measured: `" Arial"` draws Arial, not the fallback."""
    assert "render.unresolved_font_family" not in _codes(
        lint_string(_text(' font-family="  Sarasa Mono SC  "')))


def test_an_unidentified_run_is_quoted_in_the_message():
    """These `<text>` nodes usually carry no `id`, so the warning quotes the words.

    The corpus is full of them: a face warning that says only `<text>` does not
    tell a reader which of twenty runs it is about.
    """
    finding = next(f for f in lint_string(_text(' font-family="Arial, sans-serif"'))
                   if f.code == "render.unresolved_font_family")
    assert "HELLO WORLD" in finding.message


def test_no_font_family_is_not_reported():
    """Undeclared is not unresolved: the default face is a choice, not a mistake."""
    assert "render.unresolved_font_family" not in _codes(lint_string(_text()))


def test_a_font_family_on_a_group_is_not_reported():
    """Out of scope on purpose: the check is about the element that draws glyphs.

    A `font-family` on a `<g>` does not reach the `<text>` inside it (measured),
    but that is a rule about inheritance, not about a value that cannot resolve,
    and it is documented rather than warned about.
    """
    svg = (CANVAS.format(extra="")
           + '<g font-family="Arial, sans-serif"><text x="10" y="50" font-size="20">HI'
             "</text></g></svg>")
    assert "render.unresolved_font_family" not in _codes(lint_string(svg))

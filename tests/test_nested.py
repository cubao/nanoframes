"""Nested compositions: a `.nf.svg` embedded in another `.nf.svg`.

ThorVG cannot draw an SVG file as an `<image>` source (probed: nothing renders,
where a PNG renders), so a nested composition is inlined — the child is baked at
the mapped time and its tree replaces the node inside a scaling group.
"""

import os

from nanoframes import media
from nanoframes.media import MediaCache, MediaResolver
from nanoframes.parse import parse_file
from nanoframes.render import render_frame

CHILD_MOVING = """<svg xmlns="http://www.w3.org/2000/svg" data-width="50" data-height="50"
     data-fps="10" data-duration="1.0">
  <rect width="50" height="50" fill="#000000"/>
  <rect id="dot" x="0" y="0" width="10" height="10" fill="#ff0000"/>
  <script type="application/nanoframes+json"><![CDATA[
  {"animations": [{"target": "#dot", "keyframes": [
    {"t": 0.0, "transform": {"translate": [0, 0]}},
    {"t": 1.0, "transform": {"translate": [40, 0]}}
  ]}]}
  ]]></script>
</svg>
"""


def _child(tmp_path, name="child.nf.svg", content=CHILD_MOVING):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _parent(tmp_path, child_name="child.nf.svg", image_attrs='x="0" y="0" width="50" height="50"',
            duration=1.0, name="parent.nf.svg"):
    comp = tmp_path / name
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="200" data-height="200"'
        f' data-fps="10" data-duration="{duration}">'
        f'<image id="child" href="{child_name}" {image_attrs}/></svg>',
        encoding="utf-8")
    return str(comp)


def _render(tmp_path, comp, t):
    doc = parse_file(comp)
    resolver = MediaResolver(MediaCache(str(tmp_path / "cache")), fps=10, scale=1.0)
    assert resolver.prepare(doc) == []
    return render_frame(doc, t, media_resolver=resolver).convert("RGB")


def _alpha_bbox(comp, t):
    doc = parse_file(comp)
    resolver = MediaResolver(MediaCache(os.path.join(os.path.dirname(comp), ".cache")),
                             fps=10, scale=1.0)
    resolver.prepare(doc)
    img = render_frame(doc, t, media_resolver=resolver).convert("RGBA")
    return img.getchannel("A").getbbox()


def test_nested_composition_is_scaled_into_the_image_box(tmp_path):
    _child(tmp_path)
    comp = _parent(tmp_path, image_attrs='x="50" y="50" width="100" height="100"')
    assert _alpha_bbox(comp, 0.0) == (50, 50, 150, 150)


def test_nested_composition_is_recognized_by_suffix(tmp_path):
    _child(tmp_path)
    doc = parse_file(_parent(tmp_path))
    assert media.has_video_source(doc) is False
    assert media.needs_media_pass(doc) is True
    assert len(media.nested_sources(doc)) == 1


def test_nested_child_timeline_runs_on_the_parent_clock(tmp_path):
    _child(tmp_path)
    comp = _parent(tmp_path)
    assert _render(tmp_path, comp, 0.0) != _render(tmp_path, comp, 0.5)
    assert _render(tmp_path, comp, 0.0) != _render(tmp_path, comp, 1.0)


def test_nested_in_point_shifts_the_child_clock(tmp_path):
    """data-in 0.5 at t=0 must equal an untouched child at t=0.5."""
    _child(tmp_path)
    plain = _parent(tmp_path, name="plain.nf.svg")
    anchored = _parent(tmp_path, image_attrs='x="0" y="0" width="50" height="50" data-in="0.5"',
                       name="anchored.nf.svg")
    assert _render(tmp_path, anchored, 0.0) == _render(tmp_path, plain, 0.5)


def test_nested_speed_matches_the_equivalent_time(tmp_path):
    """2x speed at t=0.5 must equal 1x at t=1.0."""
    _child(tmp_path)
    plain = _parent(tmp_path, name="plain.nf.svg")
    fast = _parent(tmp_path, image_attrs='x="0" y="0" width="50" height="50" data-speed="2.0"',
                   name="fast.nf.svg")
    assert _render(tmp_path, fast, 0.5) == _render(tmp_path, plain, 1.0)


def test_nested_composition_honours_data_fit(tmp_path):
    """A 1:1 child in a 2:1 box under `contain` is centred at its own size."""
    _child(tmp_path)
    comp = _parent(tmp_path, image_attrs='x="0" y="0" width="100" height="50" data-aspect="contain"')
    assert _alpha_bbox(comp, 0.0) == (25, 0, 75, 50)


def test_nested_composition_hidden_by_its_window_draws_nothing(tmp_path):
    _child(tmp_path)
    comp = _parent(tmp_path, image_attrs='x="0" y="0" width="50" height="50" data-start="2.0"',
                   duration=1.0)
    assert _alpha_bbox(comp, 0.0) is None


def test_nested_child_is_affected_by_the_parent_transform(tmp_path):
    _child(tmp_path)
    comp = _parent(tmp_path, image_attrs='x="0" y="0" width="50" height="50" transform="translate(20,20)"')
    assert _alpha_bbox(comp, 0.0) == (20, 20, 70, 70)


def test_missing_nested_composition_is_reported_not_fatal(tmp_path):
    comp = _parent(tmp_path, "nope.nf.svg")
    doc = parse_file(comp)
    resolver = MediaResolver(MediaCache(str(tmp_path / "cache")), fps=10, scale=1.0)
    warnings = resolver.prepare(doc)
    assert warnings and "nope.nf.svg" in warnings[0]
    # and rendering still produces a frame rather than raising
    assert render_frame(doc, 0.0, media_resolver=resolver) is not None


# --- `check` follows nested compositions ------------------------------------

BROKEN_CHILD = """<svg xmlns="http://www.w3.org/2000/svg" data-width="50" data-height="50"
     data-duration="1.0">
  <rect id="ok" width="10" height="10" fill="#000000"/>
  <script type="application/nanoframes+json"><![CDATA[
  {"animations": [{"target": "#missing", "keyframes": [{"t": 0, "opacity": 1}]}]}
  ]]></script>
</svg>
"""


def test_parent_check_reports_a_child_defect(tmp_path):
    """A defect inside a nested composition is a defect in the parent's output."""
    from nanoframes.lint import lint_path

    _child(tmp_path, content=BROKEN_CHILD)
    findings = lint_path(_parent(tmp_path))
    child_findings = [f for f in findings if f.element == "#missing"]
    assert child_findings, "the child's bad target was not reported"
    assert child_findings[0].code == "animation.target_unmatched"
    assert child_findings[0].message.startswith("[child.nf.svg]")


def test_self_referencing_composition_does_not_recurse_forever(tmp_path):
    from nanoframes.lint import lint_path

    comp = tmp_path / "self.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="50" data-height="50"'
        ' data-duration="1.0">'
        '<image id="me" href="self.nf.svg" x="0" y="0" width="50" height="50"/></svg>',
        encoding="utf-8")
    codes = [f.code for f in lint_path(str(comp))]
    assert "media.nested_depth" in codes


def test_clean_nested_composition_adds_no_findings(tmp_path):
    from nanoframes.lint import lint_path

    _child(tmp_path)
    assert [f.code for f in lint_path(_parent(tmp_path))] == []

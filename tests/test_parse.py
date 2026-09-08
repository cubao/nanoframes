"""Tests for the composition model + parser."""

import pytest

from nanoframes.model import Animation, Element, Keyframe
from nanoframes.parse import ParseError, parse_string


def make_svg(body: str = "", script: str | None = None) -> str:
    s = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'data-width="480" data-height="240" data-fps="30" data-duration="4.0" '
        'data-composition-id="tc">'
        f"{body}"
    )
    if script is not None:
        s += f"<script type='application/nanoframes+json'><![CDATA[{script}]]></script>"
    s += "</svg>"
    return s


BASIC_BODY = (
    '<rect id="bg" x="0" y="0" width="480" height="240" fill="#202736"/>'
    '<text id="title" class="hl" data-start="0.5" data-duration="3" data-fade="0.4" '
    'x="40" y="120" font-size="40" fill="#f4f7ff">Hello</text>'
)


def test_parse_canvas_and_elements():
    doc = parse_string(make_svg(BASIC_BODY))
    c = doc.composition
    assert (c.width, c.height) == (480, 240)
    assert c.fps == 30
    assert c.duration == 4.0
    assert c.composition_id == "tc"
    assert c.frame_count == 120
    assert len(doc.root) >= 2

    by_id = {e.element_id: e for e in c.elements}
    title = by_id["title"]
    assert isinstance(title, Element)
    assert title.tag == "text"
    assert title.classes == ["hl"]
    assert title.clip_start == 0.5
    assert title.clip_duration == 3.0
    assert title.fade_in == 0.4
    # element without data-duration inherits composition duration
    bg = by_id["bg"]
    assert bg.clip_duration == 4.0
    assert bg.clip_start == 0.0


def test_parse_animation_timeline():
    script = json_timeline()
    doc = parse_string(make_svg(BASIC_BODY, script=script))
    anims = doc.composition.animations
    assert len(anims) == 1
    a = anims[0]
    assert isinstance(a, Animation)
    assert a.target == "#title"
    kfs = a.sorted
    assert [k.t for k in kfs] == [0.0, 0.8]
    assert isinstance(kfs[0], Keyframe)
    assert kfs[0].props["opacity"] == 0.0
    assert kfs[0].props["transform"] == {"translate": [80.0, 0.0]}
    assert kfs[0].ease == "ease-out"
    assert kfs[1].ease == "linear"


def json_timeline() -> str:
    import json

    return json.dumps(
        {
            "animations": [
                {
                    "target": "#title",
                    "keyframes": [
                        {"t": 0.0, "opacity": 0.0,
                         "transform": {"translate": [80.0, 0.0]}, "ease": "ease-out"},
                        {"t": 0.8, "opacity": 1.0, "transform": {"translate": [0.0, 0.0]}},
                    ],
                }
            ]
        }
    )


def test_root_must_be_svg():
    with pytest.raises(ParseError):
        parse_string("<div></div>")


def test_requires_positive_canvas():
    with pytest.raises(ParseError):
        parse_string('<svg xmlns="http://www.w3.org/2000/svg" data-width="0" data-height="10"/>')


def test_invalid_timeline_json():
    bad = make_svg(BASIC_BODY, script="this is not json{{{")
    with pytest.raises(ParseError):
        parse_string(bad)


def test_selector_matching():
    el = Element(element_id="a", tag="rect", classes=["c1"])
    assert el.matches("#a")
    assert el.matches(".c1")
    assert el.matches("rect")
    assert not el.matches("#b")
    assert not el.matches(".c2")
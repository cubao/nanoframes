"""What a frame's identity is, and what it deliberately is not.

Two claims, and each has a way to fail that looks like success:

* every input that can move a pixel is in — so a font swap, a toolchain change
  or a renderer edit cannot serve a frame drawn from the old inputs;
* inputs that cannot move a pixel are out — so tuning a check's budget does not
  throw away every frame of the composition that declared it.

The second is the one easier to get wrong while thinking it is being careful:
adding the whole source to the key *looks* strict and is what we had.
"""

import hashlib

import pytest

from nanoframes import identity
from nanoframes.parse import parse_file, parse_string

SVG = """<svg xmlns="http://www.w3.org/2000/svg" data-width="320" data-height="180"
     data-fps="30" data-duration="1.0">
  <rect width="320" height="180" fill="#101820"/>
  <text x="20" y="90" font-family="Arial" font-size="24" fill="#fff">{text}</text>
</svg>"""


def _doc(tmp_path, body="", name="c.nf.svg"):
    path = tmp_path / name
    path.write_text(SVG.format(text="hi") .replace("</svg>", body + "</svg>"),
                    encoding="utf-8")
    return path


# --- what is OUT ------------------------------------------------------------

@pytest.mark.parametrize("attr", identity.CHECK_ONLY_ATTRS)
def test_a_check_only_attribute_does_not_move_the_identity(tmp_path, attr):
    """`lint` reads these; nothing that draws does.

    The attribute lives in the composition's bytes, so keying on the bytes made
    a budget edit invalidate every frame of the composition — a full re-render
    for zero pixel of change.
    """
    plain = parse_string(SVG.format(text="hi"))
    tagged = parse_string(
        SVG.format(text="hi").replace("<svg ", f'<svg {attr}="24" ')
    )
    assert plain.identity == tagged.identity


def test_the_projection_drops_only_what_is_check_only():
    """The strip list is the check-only set and not something wider.

    A silent widening here would take a render attribute out of the key and turn
    the cache into a source of wrong frames, so the set is asserted by name.
    """
    assert identity.CHECK_ONLY_ATTRS == ("data-safe-margin", "data-palette-budget")


def test_reindenting_a_composition_keeps_its_identity(tmp_path):
    """The identity is what is drawn, not how the file is laid out."""
    flat = parse_string(SVG.format(text="hi"))
    indented = parse_string(SVG.format(text="hi").replace("  <rect", "\n\n    <rect"))
    assert flat.identity == indented.identity


def test_a_render_attribute_does_move_the_identity():
    """The projection is a projection, not a constant."""
    a = parse_string(SVG.format(text="hi"))
    b = parse_string(SVG.format(text="hi").replace('fill="#101820"', 'fill="#ff0000"'))
    assert a.identity != b.identity


# --- what is IN -------------------------------------------------------------

@pytest.fixture
def temp_fonts(tmp_path, monkeypatch):
    """Point the default font candidates at a temp face we can edit."""
    font = tmp_path / "face.ttf"
    font.write_bytes(b"face-one")

    def install() -> str:
        monkeypatch.setattr(identity, "DEFAULT_FONT_CANDIDATES", (str(font),))
        identity._FONTS = None  # the fingerprint is memoised per process
        return parse_string(SVG.format(text="hi")).identity

    yield font, install
    identity._FONTS = None


def test_swapping_a_font_moves_the_identity(temp_fonts):
    """ThorVG shapes from the loaded faces, so the faces are an input.

    Left out, replacing the bundled CJK face served every frame drawn with the
    old one — a wrong picture with no error and no symptom.
    """
    font, install = temp_fonts
    before = install()
    font.write_bytes(b"face-two")
    after = install()
    assert before != after


def test_a_change_in_the_renderer_moves_the_identity(monkeypatch):
    """A version alone does not cover a working tree."""
    before = identity.toolchain_fingerprint()
    # As if a module in the package had been edited.
    monkeypatch.setattr(identity, "_package_digest", lambda: "edited")
    identity._TOOLCHAIN = None
    try:
        assert identity.toolchain_fingerprint() != before
    finally:
        identity._TOOLCHAIN = None


def test_a_missing_font_candidate_is_not_an_input(tmp_path, monkeypatch):
    """An absent face cannot have drawn anything, so it cannot be an input."""
    identity._FONTS = None
    monkeypatch.setattr(identity, "DEFAULT_FONT_CANDIDATES", (str(tmp_path / "nope.ttf"),))
    try:
        empty = identity.font_fingerprint()
    finally:
        identity._FONTS = None
    assert empty == hashlib.sha256(b"").hexdigest()


def test_a_font_change_misses_the_cache(tmp_path, monkeypatch):
    """The claim the identity exists for, at the layer that acts on it.

    A cache hit is not an error and has no symptom — it is the old picture under
    the new question — so the assertion is that the frame stored under the
    previous identity is not served for it.
    """
    from PIL import Image

    from nanoframes.cache import FrameCache

    font = tmp_path / "face.ttf"
    font.write_bytes(b"one")
    comp = tmp_path / "c.nf.svg"
    comp.write_text(SVG.format(text="hi"), encoding="utf-8")
    cache = FrameCache(str(tmp_path / "cache"))
    frame = Image.new("RGBA", (320, 180), (0, 0, 0, 255))

    monkeypatch.setattr(identity, "DEFAULT_FONT_CANDIDATES", (str(font),))
    identity._FONTS = None
    try:
        before = parse_file(str(comp)).identity
        cache.put(before, 0.0, frame)
        assert cache.get(before, 0.0, 320, 180) is not None

        font.write_bytes(b"two")
        identity._FONTS = None
        after = parse_file(str(comp)).identity

        assert after != before
        assert cache.get(after, 0.0, 320, 180) is None, "served a frame from the old face"
    finally:
        identity._FONTS = None


def test_identity_is_stable_within_and_across_documents(tmp_path):
    """Two parses of the same bytes agree — the memo must not leak state."""
    src = _doc(tmp_path)
    assert parse_file(str(src)).identity == parse_file(str(src)).identity


# --- the shape of it --------------------------------------------------------

def test_components_name_every_input_and_the_digest_covers_them():
    """The report has to be able to say *which* input moved."""
    doc = parse_string(SVG.format(text="hi"))
    parts = doc.identity_components()
    assert set(parts) == {"source", "media", "fonts", "toolchain"}
    assert doc.identity == identity.digest(parts)
    assert doc.identity == identity.frame_identity(doc.root, None)


def test_a_media_component_is_named_none_rather_than_empty():
    """An empty string and an absent key read the same in a report; be explicit."""
    doc = parse_string(SVG.format(text="hi"))
    assert doc.identity_components()["media"] == "none"

"""External references: local asset resolution and the media fingerprint.

A frame is a pure function of the composition *and* the assets it draws from.
These tests pin the second half of that: the render identity has to move when a
referenced file changes under an unchanged path, or the frame cache serves a
stale picture.
"""

import os
import xml.etree.ElementTree as ET

from nanoframes import refs
from nanoframes.parse import parse_file, parse_string

SVG = """<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100"
     data-fps="30" data-duration="1.0">
  <rect width="100" height="100" fill="#000"/>
  {body}
</svg>"""

IMAGE = '<image id="pic" href="{href}" width="10" height="10"/>'


def _comp(tmp_path, body="", name="comp.nf.svg"):
    path = tmp_path / name
    path.write_text(SVG.format(body=body), encoding="utf-8")
    return str(path)


def test_no_images_has_no_media_fingerprint(tmp_path):
    """An asset-free composition fingerprints no media, and still has an identity."""
    doc = parse_file(_comp(tmp_path))
    assert doc.media_key == ""
    assert doc.identity


def test_identity_tracks_asset_content(tmp_path):
    """Same composition bytes, different asset bytes -> different identity."""
    asset = tmp_path / "dot.png"
    asset.write_bytes(b"first")
    body = IMAGE.format(href="dot.png")
    before = parse_file(_comp(tmp_path, body)).identity
    assert before != ""

    asset.write_bytes(b"second")
    after = parse_file(_comp(tmp_path, body)).identity
    assert after != before


def test_identity_is_stable_when_nothing_changes(tmp_path):
    (tmp_path / "dot.png").write_bytes(b"same")
    src = _comp(tmp_path, IMAGE.format(href="dot.png"))
    assert parse_file(src).identity == parse_file(src).identity


def test_remote_and_inlined_refs_are_not_fingerprinted(tmp_path):
    for ref in ("https://example.com/a.png", "data:image/png;base64,AAAA"):
        doc = parse_file(_comp(tmp_path, IMAGE.format(href=ref)))
        assert doc.media_key == ""
        assert doc.identity


def test_relative_refs_resolve_against_the_composition_dir(tmp_path):
    sub = tmp_path / "assets"
    sub.mkdir()
    (sub / "dot.png").write_bytes(b"x")
    doc = parse_file(_comp(tmp_path, IMAGE.format(href="assets/dot.png")))
    assert refs.local_image_paths(doc.root, doc.base_dir) == [os.path.normpath(str(sub / "dot.png"))]


def test_fingerprint_includes_the_ref_path(tmp_path):
    """Moving an asset (same bytes, new path) is still a different key."""
    (tmp_path / "a.png").write_bytes(b"identical")
    (tmp_path / "b.png").write_bytes(b"identical")
    root_a = ET.fromstring(SVG.format(body=IMAGE.format(href="a.png")))
    root_b = ET.fromstring(SVG.format(body=IMAGE.format(href="b.png")))
    fa = refs.media_fingerprint(root_a, str(tmp_path))
    fb = refs.media_fingerprint(root_b, str(tmp_path))
    assert fa and fb and fa != fb


def test_missing_asset_does_not_raise_and_is_stable(tmp_path):
    body = IMAGE.format(href="nope.png")
    first = parse_file(_comp(tmp_path, body)).media_key
    second = parse_file(_comp(tmp_path, body)).media_key
    assert first and first == second


def test_string_documents_skip_unresolvable_relative_refs():
    """No base_dir -> a relative ref cannot be hashed, and must not be guessed at."""
    doc = parse_string(SVG.format(body=IMAGE.format(href="dot.png")))
    assert doc.media_key == ""

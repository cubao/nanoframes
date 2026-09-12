"""Tests for the fast re-render cache."""

import os

from nanoframes.cache import FrameCache
from nanoframes.parse import parse_file, parse_string
from nanoframes.render import render_frame

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
TITLE = os.path.join(EXAMPLES, "title-card.nf.svg")


def test_cache_miss_then_hit(tmp_path):
    doc = parse_file(TITLE)
    cache = FrameCache(str(tmp_path / "cache"))
    a = render_frame(doc, t=1.5, cache=cache)
    assert cache.get(doc.identity, 1.5, 480, 240) is not None
    # second render is served from cache and byte-identical
    b = render_frame(doc, t=1.5, cache=cache)
    assert a.tobytes() == b.tobytes()
    assert os.path.exists(cache.frame_path(doc.identity, 1.5, 480, 240))


def test_cache_keeps_draft_and_full_frames_apart(tmp_path):
    """The canvas size is in the key, so a draft does not evict full frames."""
    doc = parse_file(TITLE)
    cache = FrameCache(str(tmp_path / "cache"))
    full = render_frame(doc, t=1.5, cache=cache)
    draft = render_frame(doc, t=1.5, cache=cache, scale=0.5)
    assert full.size == (480, 240)
    assert draft.size == (240, 120)
    # both entries survived
    assert cache.get(doc.identity, 1.5, 480, 240) is not None
    assert cache.get(doc.identity, 1.5, 240, 120) is not None


def test_cache_key_changes_with_content(tmp_path):
    doc = parse_file(TITLE)
    cache = FrameCache(str(tmp_path / "cache"))
    render_frame(doc, t=2.0, cache=cache)
    k1 = cache.frame_key(doc.identity, 2.0, 480, 240)

    # edit the source text: identity (a hash of the raw bytes) must change
    edited = open(TITLE).read().replace('font-size="44"', 'font-size="46"')
    doc3 = parse_string(edited)
    assert doc3.identity != doc.identity
    assert cache.frame_key(doc3.identity, 2.0, 480, 240) != k1


def test_no_cache_renders_independently(tmp_path):
    doc = parse_file(TITLE)
    a = render_frame(doc, t=2.0)
    b = render_frame(doc, t=2.0)
    assert a.tobytes() == b.tobytes()

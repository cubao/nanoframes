"""Tests for the fast re-render cache."""

import os

import pytest

from nanoframes.cache import FrameCache
from nanoframes.parse import parse_file
from nanoframes.render import render_frame

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
TITLE = os.path.join(EXAMPLES, "title-card.nf.svg")


def test_cache_miss_then_hit(tmp_path):
    doc = parse_file(TITLE)
    cache = FrameCache(str(tmp_path / "cache"))
    a = render_frame(doc, t=1.5, cache=cache)
    assert not cache.get(doc.identity, 1.5, 480, 240) is None
    # second render is served from cache and byte-identical
    b = render_frame(doc, t=1.5, cache=cache)
    assert a.tobytes() == b.tobytes()
    assert os.path.exists(cache.frame_path(doc.identity, 1.5))


def test_cache_key_changes_with_content(tmp_path):
    import copy

    doc = parse_file(TITLE)
    cache = FrameCache(str(tmp_path / "cache"))
    render_frame(doc, t=2.0, cache=cache)
    k1 = cache.frame_key(doc.identity, 2.0)

    doc2 = parse_file(TITLE)
    doc2.root.set("data-fps", "60")  # same source text rewritten
    # different content -> different identity (source_key unchanged here because
    # we mutated the tree post-parse; use a text-edit to be exact):
    new_text = open(TITLE).read().replace('data-fps="30"', 'data-fps="30"')  # identical
    from nanoframes.parse import parse_string

    doc3 = parse_string(open(TITLE).read().replace('font-size="44"', 'font-size="46"'))
    assert doc3.identity != doc.identity
    assert cache.frame_key(doc3.identity, 2.0) != k1


def test_no_cache_renders_independently(tmp_path):
    doc = parse_file(TITLE)
    a = render_frame(doc, t=2.0)
    b = render_frame(doc, t=2.0)
    assert a.tobytes() == b.tobytes()
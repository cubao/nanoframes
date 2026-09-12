"""Tests for the fast re-render cache."""

import os
import shutil
import time

import pytest

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


def test_cache_key_follows_asset_content(tmp_path):
    """An edited ``<image>`` under an unchanged href must miss the cache.

    The composition bytes are identical here, so only the media fingerprint can
    move the key. Before it existed, swapping a referenced PNG served the frames
    that drew the old one.
    """
    from PIL import Image

    asset = tmp_path / "dot.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(asset)
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100"'
        ' data-fps="30" data-duration="1.0">'
        '<image href="dot.png" width="100" height="100"/></svg>',
        encoding="utf-8",
    )
    cache = FrameCache(str(tmp_path / "cache"))
    doc1 = parse_file(str(comp))
    first = render_frame(doc1, t=0.0, cache=cache)

    Image.new("RGBA", (4, 4), (0, 0, 255, 255)).save(asset)
    doc2 = parse_file(str(comp))
    assert doc2.identity != doc1.identity, "the asset's content is folded in"
    second = render_frame(doc2, t=0.0, cache=cache)
    assert first.tobytes() != second.tobytes(), "served a frame for the old asset"


def test_no_cache_renders_independently(tmp_path):
    doc = parse_file(TITLE)
    a = render_frame(doc, t=2.0)
    b = render_frame(doc, t=2.0)
    assert a.tobytes() == b.tobytes()


def _frames(cache, n, size=(4, 4)):
    """Put ``n`` distinct frames through the cache."""
    from PIL import Image

    img = Image.new("RGBA", size, (0, 0, 0, 255))
    for i in range(n):
        cache.put(f"source-{i}", 0.0, img)


def test_cache_trims_to_its_byte_cap(tmp_path):
    """The key is content-hashed, so edits orphan frames; the cap bounds them."""
    cache = FrameCache(str(tmp_path / "c"), max_bytes=10 * 1024)
    _frames(cache, 12)                      # each 4x4 PNG is ~100 bytes
    cache.trim(max_bytes=500)               # an explicit, easily-checked cap
    frames, size = cache.stats()
    assert size <= 500, f"cache kept {size} bytes past its cap"
    assert frames < 12
    # The newest entries survive: the frames a current composition can still ask for.
    assert any(cache.get(f"source-{i}", 0.0, 4, 4) is not None for i in (11, 10))


def test_cache_trim_runs_automatically_on_write(tmp_path):
    cache = FrameCache(str(tmp_path / "auto"), max_bytes=800)
    _frames(cache, 70)
    assert cache.stats()[0] < 70, "the write-path sweep never trimmed"


def test_cache_entries_expire(tmp_path):
    """Per-key TTL: an entry past its expiry is a miss, and is swept."""
    cache = FrameCache(str(tmp_path / "c"), ttl=0.05)
    _frames(cache, 1)
    assert cache.get("source-0", 0.0, 4, 4) is not None
    time.sleep(0.08)
    assert cache.get("source-0", 0.0, 4, 4) is None   # filtered out on read
    assert cache.sweep() == 1                         # and purged on the next pass
    assert cache.stats()[0] == 0

    permanent = FrameCache(str(tmp_path / "p"), ttl=None)
    _frames(permanent, 1)
    assert permanent.get("source-0", 0.0, 4, 4) is not None


def test_cache_adopts_payloads_without_an_index(tmp_path):
    """The payloads are the source of truth: a lost index is rebuilt from them.

    This is also the v1 migration path — the pre-index layout wrote a flat
    ``<cache_dir>/<hash>.png``, and opening that directory adopts whatever is
    there instead of throwing the frames away.
    """
    root = tmp_path / "c"
    cache = FrameCache(str(root))
    _frames(cache, 3)
    assert cache.stats()[0] == 3
    # Simulate a lost index (or a directory from before the index existed) by
    # deleting every non-payload file: the payloads are the source of truth.
    cache.close()
    for name in os.listdir(root):
        if not name.endswith(".png") and name != "files":
            path = os.path.join(root, name)
            os.unlink(path) if os.path.isfile(path) else shutil.rmtree(path)
    reopened = FrameCache(str(root))
    frames, size = reopened.stats()
    assert frames == 3 and size > 0, "payloads were not adopted"
    assert reopened.get("source-1", 0.0, 4, 4) is not None


def test_cache_drops_rows_whose_payload_vanished(tmp_path):
    cache = FrameCache(str(tmp_path / "c"))
    _frames(cache, 2)
    os.unlink(cache.frame_path("source-0", 0.0, 4, 4))
    assert cache.get("source-0", 0.0, 4, 4) is None     # miss, not a crash
    assert cache.stats()[0] == 1                        # dead row dropped
    adopted, dropped = cache.reconcile()
    assert (adopted, dropped) == (0, 0)                 # index agrees with disk


def test_cache_clear_reports_and_removes(tmp_path):
    cache = FrameCache(str(tmp_path / "c"))
    _frames(cache, 1)
    assert cache.stats()[0] == 1
    assert cache.clear() == 1
    assert cache.stats() == (0, 0)
    assert not os.path.exists(cache.cache_dir)


def test_cache_rejects_nonsense_limits(tmp_path):
    with pytest.raises(ValueError):
        FrameCache(str(tmp_path / "a"), max_bytes=0)
    with pytest.raises(ValueError):
        FrameCache(str(tmp_path / "b"), ttl=-1)

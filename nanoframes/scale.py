"""Draft rendering at a reduced scale (``--scale``).

A draft render exists to answer "does the whole thing look right?" in seconds
instead of minutes. Two things have to shrink for that to pay off:

* **the canvas** — fewer pixels to rasterize, encode and hand to ffmpeg;
* **the assets** — ThorVG resamples every ``<image>`` source into its
  destination rect on *every* frame, so a 1560x991 board costs a full source
  resample on all 1425 frames no matter how small the canvas is. On a
  board-heavy composition that resample is the dominant per-frame cost, and
  scaling only the canvas buys almost nothing (~10%).

So ``prescale_images`` rewrites each distinct source once, before the frame
loop, into a disk-cached copy at the render scale. ThorVG then resamples from
a small source and the frame cost drops with the scale the way you would
expect.

Draft output is for looking at, not for delivering: the prescaled asset is
resampled from the reduced copy, so a draft frame is not a pixel-exact
downscale of the full-quality frame.
"""

from __future__ import annotations

import hashlib
import os
import tempfile

from nanoframes.parse import Document
from nanoframes.refs import IMAGE_REF_ATTRS, REMOTE_SCHEMES
from nanoframes.xmlutil import local_name

# Set to the authored path on the first prescale pass, so a later pass at a
# different scale still resizes the true source rather than a reduced copy.
_SOURCE_ATTR = "data-src"



def draft_size(width: int, height: int, scale: float) -> tuple[int, int]:
    """Canvas size for a render at ``scale``, rounded to even pixels.

    H.264 with ``yuv420p`` (what the video path produces) rejects odd
    dimensions, so draft sizes are snapped to even here rather than failing
    later inside ffmpeg.
    """
    return _even(width * scale), _even(height * scale)


def _even(value: float) -> int:
    return max(2, int(round(value)) // 2 * 2)


def prescale_images(doc: Document, scale: float) -> int:
    """Make every local ``<image>`` reference match ``scale``; return the count changed.

    ``scale < 1`` points the node at a resized copy; ``scale >= 1`` restores the
    authored path, so a draft render never degrades a later full-quality one on
    the same ``doc``. Re-entrant at any scale: the first pass records the
    authored path in ``data-src``, so a later pass resizes the true source
    rather than an already-reduced copy.
    """
    done = 0
    for node in doc.root.iter():
        if local_name(node.tag) != "image":
            continue
        authored = node.get(_SOURCE_ATTR)
        if authored is not None and scale >= 1.0:
            for attr in [a for a in IMAGE_REF_ATTRS if node.get(a) is not None] or ["href"]:
                node.set(attr, authored)
            del node.attrib[_SOURCE_ATTR]
            done += 1
            continue
        if scale >= 1.0:
            continue
        for attr in IMAGE_REF_ATTRS:
            ref = authored or node.get(attr)
            if not ref or ref.startswith(REMOTE_SCHEMES):
                continue
            src = _resolve(ref, doc.base_dir)
            if src is None:
                continue
            node.set(_SOURCE_ATTR, ref)
            node.set(attr, _resized_copy(src, scale))
            done += 1
    return done


def _resolve(ref: str, base_dir: str | None) -> str | None:
    path = ref if os.path.isabs(ref) else os.path.normpath(os.path.join(base_dir or ".", ref))
    return path if os.path.exists(path) else None


def _cache_dir() -> str:
    path = os.path.join(tempfile.gettempdir(), "nanoframes-draft")
    os.makedirs(path, exist_ok=True)
    return path


def _resized_copy(src: str, scale: float) -> str:
    """A ``scale``-sized copy of ``src`` under the draft cache, resized at most once.

    The key folds in mtime and size, so editing an asset invalidates its copy
    without any bookkeeping.
    """
    st = os.stat(src)
    key = hashlib.sha256(
        f"{os.path.abspath(src)}:{st.st_mtime_ns}:{st.st_size}:{scale:.4f}".encode()
    ).hexdigest()
    out = os.path.join(_cache_dir(), key + ".png")
    if os.path.exists(out):
        return out

    from PIL import Image  # heavy import, keep it lazy

    try:
        with Image.open(src) as im:
            size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
            im.convert("RGBA").resize(size, Image.LANCZOS).save(out)
    except Exception:  # noqa: BLE001
        # Not a raster Pillow can resize — a video source (handled by the media
        # path, which extracts frames at the render scale itself) or a file this
        # build cannot decode. Leave the source alone rather than fail the render.
        return src
    return out

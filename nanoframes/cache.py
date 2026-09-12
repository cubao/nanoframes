"""Fast re-render cache.

A frame is a pure function of (composition source content, time, canvas size).
We cache the rendered PNG keyed by a hash of those, so iterating an unchanged
composition (repeated previews, re-render after unrelated edits) skips ThorVG
entirely.

The key folds in the full source bytes, so *any* edit to the composition
invalidates the cache for every frame automatically; the canvas size is in
there too, so draft (``--scale``) and full-quality frames coexist instead of
evicting each other.
"""

from __future__ import annotations

import hashlib
import os

# The cache is keyed by source content, so an edit orphans every frame of the
# previous version — without a policy it only ever grows (a real checkout of
# this repo reached 4000 entries / 116 MB). Trim on write, cheaply.
DEFAULT_MAX_ENTRIES = 2000
TRIM_EVERY = 64  # writes between directory scans


class FrameCache:
    def __init__(self, cache_dir: str = ".nanoframes-cache",
                 max_entries: int = DEFAULT_MAX_ENTRIES):
        self.cache_dir = cache_dir
        self.max_entries = max_entries
        self._writes_since_trim = 0

    # -- keys -----------------------------------------------------------------
    def frame_key(self, source_key: str, t: float, width: int, height: int) -> str:
        return hashlib.sha256(f"{source_key}:{t:.6f}:{width}x{height}".encode()).hexdigest()

    def frame_path(self, source_key: str, t: float, width: int, height: int) -> str:
        return os.path.join(self.cache_dir, self.frame_key(source_key, t, width, height) + ".png")

    # -- get / put -------------------------------------------------------------
    def get(self, source_key: str, t: float, width: int, height: int) -> "object | None":
        from PIL import Image

        path = self.frame_path(source_key, t, width, height)
        if not os.path.exists(path):
            return None
        img = Image.open(path)
        if img.size != (width, height):
            return None
        return img

    def put(self, source_key: str, t: float, image) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        image.save(self.frame_path(source_key, t, *image.size))
        self._writes_since_trim += 1
        if self.max_entries and self._writes_since_trim >= TRIM_EVERY:
            self._writes_since_trim = 0
            self.trim()

    # -- eviction ---------------------------------------------------------------
    def trim(self, max_entries: int | None = None) -> int:
        """Drop the oldest entries past the cap; returns how many were removed.

        Eviction is by modification time (oldest first) — the frames of a
        superseded composition version are exactly the ones that will never be
        asked for again.
        """
        cap = self.max_entries if max_entries is None else max_entries
        if not cap or not os.path.isdir(self.cache_dir):
            return 0
        entries = []
        for name in os.listdir(self.cache_dir):
            if not name.endswith(".png"):
                continue
            path = os.path.join(self.cache_dir, name)
            try:
                entries.append((os.path.getmtime(path), path))
            except OSError:
                continue
        excess = len(entries) - cap
        if excess <= 0:
            return 0
        entries.sort()
        removed = 0
        for _, path in entries[:excess]:
            # A concurrent render (or a parallel test worker) may clear or
            # overwrite entries under us; a vanished file is not an error.
            try:
                os.unlink(path)
                removed += 1
            except OSError:  # noqa: PERF203 — the guard is the point
                continue
        return removed

    def stats(self) -> tuple[int, int]:
        """``(entries, bytes)`` currently on disk."""
        if not os.path.isdir(self.cache_dir):
            return 0, 0
        entries = size = 0
        for name in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, name)
            try:
                size += os.path.getsize(path)
                if name.endswith(".png"):
                    entries += 1
            except OSError:
                continue
        return entries, size

    def clear(self) -> None:
        import shutil

        if os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir)

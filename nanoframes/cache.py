"""Fast re-render cache.

A frame is a pure function of (composition source content, time). We cache the
rendered PNG keyed by a hash of those, so iterating an unchanged composition
(repeated previews, re-render after unrelated edits) skips ThorVG entirely.

The key folds in the full source bytes, so *any* edit to the composition
invalidates the cache for every frame automatically.
"""

from __future__ import annotations

import hashlib
import os


class FrameCache:
    def __init__(self, cache_dir: str = ".nanoframes-cache"):
        self.cache_dir = cache_dir

    # -- keys -----------------------------------------------------------------
    def frame_key(self, source_key: str, t: float) -> str:
        return hashlib.sha256(f"{source_key}:{t:.6f}".encode()).hexdigest()

    def frame_path(self, source_key: str, t: float) -> str:
        return os.path.join(self.cache_dir, self.frame_key(source_key, t) + ".png")

    # -- get / put -------------------------------------------------------------
    def get(self, source_key: str, t: float, width: int, height: int) -> "object | None":
        from PIL import Image

        path = self.frame_path(source_key, t)
        if not os.path.exists(path):
            return None
        img = Image.open(path)
        if img.size != (width, height):
            return None
        return img

    def put(self, source_key: str, t: float, image) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        image.save(self.frame_path(source_key, t))

    def clear(self) -> None:
        import shutil

        if os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir)
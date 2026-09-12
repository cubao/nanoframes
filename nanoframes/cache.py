"""Fast re-render cache: one PNG per frame, in a self-maintaining directory.

A frame is a pure function of (composition source bytes, time, canvas size), so
it is cached on disk under a hash of exactly those. Iterating on an unchanged
composition (repeated previews, a re-render after an unrelated edit) then skips
ThorVG entirely; the canvas size is part of the key, so draft and full-quality
frames coexist instead of evicting each other.

The payload is a plain PNG any other tool can open, and the cache maintains
itself: per-entry TTL, a byte capacity cap with opportunistic eviction, and a
sweep of in-flight leftovers. The index and its bookkeeping come from
[diskcache](https://github.com/grantjenks/python-diskcache) — the part it does
not do, and the part this module owns, is *"this key's value is this file, under
this name"*.

Layout::

    .nanoframes-cache/
        cache.db                diskcache's SQLite index (do not touch)
        files/<aa>/<hash>.png   payload, sharded two hex chars deep
        tmp/<uuid>.part         in-flight writes, swept when stale

**The payload directory is the source of truth.** A missing or stale index is
rebuilt from it on open (see `reconcile`), which is also how a cache written by
the pre-index layout migrates — with no user action.

The cache never fails a render: a contended index read is a miss, a contended
write is skipped, and a payload deleted behind the index is re-rendered. A miss
only ever costs one frame.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import time
import uuid

from diskcache import Cache, Disk, Timeout
from loguru import logger

# loguru installs a stderr sink on import; a library has no business writing to
# its host's console. The diagnostics below stay available — an application
# (or a test) that wants them adds its own sink.
logger.remove()

# Payload bytes the cache may hold before it starts evicting — roughly 4500
# frames of a document-wide 1280x720 composition.
# Where frames live when nothing says otherwise. Also the directory `doctor`
# measures free space at, and what `cache --clear` reclaims.
DEFAULT_CACHE = ".nanoframes-cache"

DEFAULT_MAX_BYTES = 512 * 1024 * 1024
# Frames are reproducible from their composition, so an untouched entry is
# worthless after a while; a week matches diskcache's own expiry convention.
DEFAULT_TTL = 7 * 24 * 3600.0

TMP_MAX_AGE = 24 * 3600.0   # an in-flight write older than this was crashed
SWEEP_EVERY = 64            # writes between maintenance passes
_TMP_DIRNAME = "tmp"
_FILES_DIRNAME = "files"


class _PayloadDisk(Disk):
    """A disk that removes payloads rather than cache objects.

    Upstream stores every value inside one file per key and deletes that file
    itself; here the value *is* a payload path, so eviction and expiry have to
    delete what the path points at. Payloads may also be directories (a
    composition can cache a whole render tree), which upstream's ``remove``
    refuses.
    """

    def remove(self, file_path):
        full_path = os.path.join(self._directory, file_path)
        with contextlib.suppress(OSError):
            if os.path.isdir(full_path) and not os.path.islink(full_path):
                shutil.rmtree(full_path, ignore_errors=True)
            else:
                os.remove(full_path)
        with contextlib.suppress(OSError):
            os.removedirs(os.path.dirname(full_path))


def _path_bytes(path: str) -> int:
    """Size of a payload file, or a recursive walk for a directory payload."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(root, name))
    return total


class FrameCache:
    """Frame cache keyed by ``(source content, time, canvas size)``.

    ``max_bytes`` bounds payload bytes and ``ttl`` bounds an entry's age. Both
    are enforced cheaply — diskcache culls on every write, and a full sweep
    (expired entries + stale in-flight files) runs every ``sweep_every`` writes.
    A contended index degrades to a miss rather than an error.

    Cross-process safety comes from SQLite's locking plus the atomic rename in
    `put`, so two ``nanoframes`` commands can share a directory.
    """

    def __init__(self, cache_dir: str = ".nanoframes-cache",
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 ttl: float | None = DEFAULT_TTL,
                 sweep_every: int = SWEEP_EVERY):
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {max_bytes!r}")
        if ttl is not None and ttl <= 0:
            raise ValueError(f"ttl must be > 0 or None, got {ttl!r}")
        self.cache_dir = os.path.abspath(os.path.expanduser(cache_dir))
        self.frames_dir = os.path.join(self.cache_dir, _FILES_DIRNAME)
        self.tmp_dir = os.path.join(self.cache_dir, _TMP_DIRNAME)
        self.max_bytes = max_bytes
        self.ttl = ttl
        self.sweep_every = sweep_every
        self._writes_since_sweep = 0
        self._index: Cache | None = None

    # -- keys -----------------------------------------------------------------
    def frame_key(self, identity: str, t: float, width: int, height: int) -> str:
        """Stable hash of everything a frame depends on.

        ``identity`` is the document's render identity — source projection,
        assets, fonts and toolchain — so any input that can move a pixel misses
        every frame of the composition, and an input that cannot (a check-only
        attribute) does not. See `nanoframes.identity`.
        """
        return hashlib.sha256(f"{identity}:{t:.6f}:{width}x{height}".encode()).hexdigest()

    def frame_path(self, identity: str, t: float, width: int, height: int) -> str:
        """Where this frame's PNG lives (whether or not it exists yet)."""
        return self._path_for(self.frame_key(identity, t, width, height))

    # -- get / put -------------------------------------------------------------
    def get(self, identity: str, t: float, width: int, height: int):
        """The cached frame as a Pillow image, or ``None``.

        A payload deleted behind the index, or a PNG that no longer decodes, is
        dropped and reported as a miss: the frame is reproducible, so the repair
        is free.
        """
        key = self.frame_key(identity, t, width, height)
        path = self._entry_path(key)
        if path is None:
            return None
        try:
            return _load_png(path, width, height)
        except OSError as exc:
            logger.debug("FrameCache dropping an unusable payload: {}", exc)
            self._drop(key)
            return None

    def put(self, identity: str, t: float, image) -> None:
        """Store one frame (a Pillow image). A cache write never fails a render."""
        key = self.frame_key(identity, t, *image.size)
        final = self._path_for(key)
        tmp = os.path.join(self.tmp_dir, uuid.uuid4().hex + ".part")
        try:
            os.makedirs(os.path.dirname(final), exist_ok=True)
            os.makedirs(self.tmp_dir, exist_ok=True)
            image.save(tmp, format="PNG")
            # Atomic within the cache filesystem: a reader sees the complete
            # frame under its final name, or nothing at all.
            os.replace(tmp, final)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            return
        try:
            self.index.set(key, os.path.relpath(final, self.cache_dir), expire=self.ttl)
        except Timeout:
            # Index busy: the payload stays, and the next reconcile adopts it.
            logger.debug("FrameCache index busy; kept {} unregistered", final)
            return
        self._writes_since_sweep += 1
        if self.sweep_every and self._writes_since_sweep >= self.sweep_every:
            self._writes_since_sweep = 0
            self.sweep()
            self.trim()

    # -- maintenance -----------------------------------------------------------
    def sweep(self) -> int:
        """Drop expired entries and stale in-flight files; returns entries dropped."""
        removed = 0
        with contextlib.suppress(Timeout):
            removed = self.index.expire()
        self._sweep_tmp(time.time())
        return removed

    def trim(self, max_bytes: int | None = None) -> int:
        """Evict oldest entries until the payloads fit ``max_bytes``.

        Returns how many were removed. The frames of a superseded composition
        version are exactly the ones nothing will ask for again, so
        oldest-stored-first costs the fewest re-renders.
        """
        cap = self.max_bytes if max_bytes is None else max_bytes
        if cap <= 0:
            return 0
        total = self.stats()[1]
        if total <= cap:
            return 0
        removed = 0
        for key in list(self.index.iterkeys()):
            if total <= cap:
                break
            path = self._entry_path(key, heal=False)
            size = _path_bytes(path) if path and os.path.exists(path) else 0
            if self._drop(key):
                if path:
                    with contextlib.suppress(OSError):
                        os.unlink(path)
                total -= size
                removed += 1
        if removed:
            logger.info("FrameCache trimmed {} entries ({} byte cap)", removed, cap)
        return removed

    def reconcile(self) -> tuple:
        """Rebuild the index from the payloads; returns ``(adopted, dropped)``.

        ``adopted`` counts files with no index entry (a crash between the rename
        and the index write, or a directory from before the index existed);
        ``dropped`` counts entries whose payload is gone. One directory walk —
        cheap enough to run whenever a cache is opened.
        """
        on_disk = dict(self._scan_payloads())
        known = set()
        adopted = dropped = 0
        for key in list(self.index.iterkeys()):
            entry = self._read(key)
            if entry is None:
                continue
            if entry in on_disk:
                known.add(entry)
            elif self._drop(key):
                dropped += 1
        for relpath in on_disk:
            if relpath in known:
                continue
            try:
                self.index.set(self._key_of(relpath), relpath, expire=self.ttl)
                adopted += 1
            except Timeout:
                break
        if adopted or dropped:
            logger.info("FrameCache reconciled: adopted={} dropped={} dir={}",
                        adopted, dropped, self.cache_dir)
        return adopted, dropped

    def stats(self) -> tuple:
        """``(frames, payload_bytes)`` currently registered.

        A missing directory is an empty cache, so this reports without opening
        an index — otherwise asking a cleared cache how big it is would put the
        directory back.
        """
        if not os.path.isdir(self.cache_dir):
            return 0, 0
        frames = 0
        total = 0
        for key in self.index.iterkeys():
            relpath = self._read(key)
            if not isinstance(relpath, str):
                continue          # a foreign value; this class never writes one
            path = self._resolve(relpath)
            if not os.path.exists(path):
                continue
            frames += 1
            total += _path_bytes(path)
        return frames, total

    def clear(self) -> int:
        """Delete every payload and the index; returns the frames removed.

        The index is closed first — removing a file that is still open is fine
        on POSIX but not on Windows — and left closed; the next `get`/`put`
        recreates it (and finds an empty directory to adopt).
        """
        frames, _ = self.stats()
        self.close()
        with contextlib.suppress(OSError):
            shutil.rmtree(self.cache_dir)
        return frames

    def close(self) -> None:
        """Close the index; the next operation opens it again."""
        if self._index is not None:
            with contextlib.suppress(Exception):
                self._index.close()
            self._index = None

    @property
    def index(self) -> Cache:
        """The index, opened (and reconciled against the payloads) on first use.

        Opening lazy is what makes `clear` leave the directory genuinely gone,
        and what lets a deleted or foreign cache directory be adopted on the
        next call rather than at construction.
        """
        if self._index is None:
            # diskcache's size_limit counts SQLite pages, so leave it unbounded
            # and enforce the payload cap in `trim`, which sees real file sizes.
            self._index = Cache(self.cache_dir, disk=_PayloadDisk, timeout=5.0,
                                size_limit=2**63 - 1,
                                eviction_policy="least-recently-stored")
            self.reconcile()
        return self._index

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        self.close()

    # -- index -----------------------------------------------------------------
    def _entry_path(self, key: str, heal: bool = True) -> str | None:
        """The payload path an index entry points at, or ``None``.

        With ``heal`` (the read path) a missing payload drops the entry, so the
        next render repopulates both file and index.
        """
        relpath = self._read(key)
        if not isinstance(relpath, str):
            return None
        path = self._resolve(relpath)
        if os.path.exists(path):
            return path
        logger.debug("FrameCache entry without a payload: {}", relpath)
        if heal:
            self._drop(key)
        return None

    def _read(self, key: str):
        """The index value for ``key``, or ``None`` (including when contended)."""
        try:
            return self.index.get(key)
        except Timeout:
            return None

    def _drop(self, key: str) -> bool:
        try:
            return bool(self.index.delete(key))
        except Timeout:
            return False

    def _path_for(self, key: str) -> str:
        return os.path.join(self.frames_dir, key[:2], key + ".png")

    def _resolve(self, relpath: str) -> str:
        return os.path.join(self.cache_dir, relpath)

    def _key_of(self, relpath: str) -> str:
        """The frame key a payload encodes: its file name is the hash."""
        return os.path.splitext(os.path.basename(relpath))[0]

    # -- directory -------------------------------------------------------------
    def _scan_payloads(self):
        """Yield ``(relative_path, absolute_path)`` for every payload on disk.

        Recognizes both layouts: the sharded ``files/<aa>/<hash>.png`` written
        today, and the flat ``<cache_dir>/<hash>.png`` of the first release —
        which is what makes migrating an old cache a no-op for the user.
        """
        found = []
        if os.path.isdir(self.frames_dir):
            for shard in os.scandir(self.frames_dir):
                if shard.is_dir():
                    found.extend(entry.path for entry in os.scandir(shard.path))
        with contextlib.suppress(OSError):
            found.extend(entry.path for entry in os.scandir(self.cache_dir)
                         if entry.is_file() and entry.name.endswith(".png"))
        for path in found:
            if path.endswith(".png") and os.path.isfile(path):
                yield os.path.relpath(path, self.cache_dir), path

    def _sweep_tmp(self, now: float) -> int:
        """Remove in-flight writes left behind by a crashed process."""
        cutoff = now - TMP_MAX_AGE
        try:
            entries = list(os.scandir(self.tmp_dir))
        except OSError:
            return 0
        removed = 0
        for entry in entries:
            with contextlib.suppress(OSError):
                if entry.stat(follow_symlinks=False).st_mtime < cutoff:
                    os.unlink(entry.path)
                    removed += 1
        return removed


def _load_png(path: str, width: int, height: int):
    """Decode a cached PNG, or raise ``OSError`` if unreadable or wrong-sized."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as img:
            if img.size != (width, height):
                raise OSError(f"{path} is {img.size}, expected {(width, height)}")
            img.load()          # decode while the handle is open
            return img.copy()
    except UnidentifiedImageError as exc:
        raise OSError(f"{path} is not a readable image") from exc

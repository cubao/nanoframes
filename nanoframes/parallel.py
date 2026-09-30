"""Render a composition's frames across a pool of worker *processes*.

Why processes rather than threads: measured on this ThorVG build, two renders
running concurrently inside one interpreter abort the process (two Python
threads each calling ``render_svg`` crashed with SIGABRT/SIGSEGV within a few
frames — the engine's font cache and teardown are global state, and the binding
does not serialize them). A worker process owns its own copy of that state, so
the pool is the only safe way to use more than one core.

Determinism survives by construction: a frame does not depend on its
neighbours, and the pool hands back the same bytes the sequential loop wrote
(verified byte-for-byte against a 256-frame sequential render).

Workers are given the composition **path**, not a parsed document: each process
parses once and reuses it, so nothing but the frame's index and time crosses
the process boundary.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

#: Workers are started from scratch (~0.3-0.5s each on macOS, which spawns),
#: so a pool only pays for itself once every worker has a few frames to render.
MIN_FRAMES_PER_WORKER = 6

#: Ceiling on auto-selected workers. Frames are ~1.5 MB each and the rasterizer
#: is memory-bandwidth bound, so more workers stop helping before they stop
#: costing.
MAX_WORKERS = 8

_STATE: dict = {}


def resolve_jobs(requested: int, frame_count: int) -> int:
    """How many worker processes to use for ``frame_count`` frames.

    ``requested`` is the CLI's ``--jobs``: 0 means "decide for me", 1 means
    "never leave this process". Auto keeps a pool only when the frame count
    justifies it, and never asks for more workers than there are frames.
    """
    if requested and requested > 0:
        return max(1, min(requested, max(1, frame_count)))
    auto = min(MAX_WORKERS, os.cpu_count() or 1)
    if frame_count < auto * MIN_FRAMES_PER_WORKER:
        return 1
    return max(1, min(auto, frame_count))


def _init_worker(comp_path: str, dest: str, prefix: str, threads: int, scale: float,
                 dpi: float, cache_config: tuple | None, compress_level: int | None) -> None:
    """Per-process setup: parse the composition and open a private cache handle.

    Opening its own ``FrameCache`` per worker is what the cache is built for
    (SQLite locking plus an atomic rename in ``put``); a contended index
    degrades to a miss, never to an error.
    """
    from nanoframes.cache import FrameCache
    from nanoframes.parse import parse_file

    _STATE.update(
        doc=parse_file(comp_path),
        dest=dest,
        prefix=prefix,
        threads=threads,
        scale=scale,
        dpi=dpi,
        compress_level=compress_level,
        cache=FrameCache(*cache_config) if cache_config else None,
    )


def _render_one(job: tuple) -> tuple:
    """Render one frame in a worker; returns ``(index, t, was_blank)``."""
    from nanoframes.render import frame_is_blank, render_frame

    index, t = job
    dst = os.path.join(_STATE["dest"], f"{_STATE['prefix']}.{index:05d}.png")
    img = render_frame(_STATE["doc"], t, out_path=dst, threads=_STATE["threads"],
                       cache=_STATE["cache"], scale=_STATE["scale"], dpi=_STATE["dpi"],
                       warn_blank=False)
    if _STATE["compress_level"] is not None:
        # render_frame already wrote the frame; only the compression level of
        # that write differs, so rewrite it rather than re-render.
        img.save(dst, compress_level=_STATE["compress_level"])
    return index, t, frame_is_blank(img)


def render_sequence(doc, comp_path: str, times: list, dest: str, prefix: str, *,
                    jobs: int = 0, threads: int = 4, cache=None, scale: float = 1.0,
                    dpi: float = 1.0, compress_level: int | None = None) -> list:
    """Write every frame to ``dest/<prefix>.NNNNN.png``; return the blank times.

    The sequential path and the pool write the same files: a worker renders,
    saves and reports whether its frame came out fully transparent, which is
    all the caller ever needed from the loop.

    ``comp_path`` must be the file the document was parsed from — the pool
    re-parses it in each worker, so a document built from a string (there is no
    such caller today) has to take the sequential path.
    """
    from nanoframes.render import frame_is_blank, render_frame

    blank: list = []
    workers = resolve_jobs(jobs, len(times))
    if workers <= 1 or not comp_path or not os.path.exists(comp_path):
        for index, t in enumerate(times):
            dst = os.path.join(dest, f"{prefix}.{index:05d}.png")
            img = render_frame(doc, t, out_path=dst, threads=threads, cache=cache,
                               scale=scale, dpi=dpi, warn_blank=False)
            if compress_level is not None:
                img.save(dst, compress_level=compress_level)
            if frame_is_blank(img):
                blank.append(t)
        return blank

    cache_config = None
    if cache is not None:
        cache_config = (cache.cache_dir, cache.max_bytes, cache.ttl, cache.sweep_every)
    jobs_out = [(index, t) for index, t in enumerate(times)]
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(comp_path, dest, prefix, threads, scale, dpi, cache_config,
                  compress_level),
    ) as pool:
        for _index, t, is_blank in pool.map(_render_one, jobs_out, chunksize=1):
            if is_blank:
                blank.append(t)
    return blank

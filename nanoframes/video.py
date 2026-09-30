"""Render a composition to a deterministic MP4 via FFmpeg.

The frames are rendered to a temporary PNG sequence then muxed with `ffmpeg`
into H.264 (MP4) using a fixed option set for reproducible output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from nanoframes import parallel, timeline
from nanoframes.parse import Document


def mux_frames_to_mp4(
    frame_dir: str,
    prefix: str,
    fps: int,
    out_path: str,
    audio: str | None = None,
) -> str:
    """Mux a PNG sequence ``<frame_dir>/<prefix>.NNNNN.png`` into an MP4.

    Fixed ffmpeg option set (H.264, yuv420p, crf 18) so output is reproducible.
    The MP4 takes the frame sequence's own size, so a draft render (``--scale``)
    yields a smaller video without any scaling filter; ``audio`` is muxed as
    AAC with ``-shortest``.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(fps),
        "-i", os.path.join(frame_dir, f"{prefix}.%05d.png"),
    ]
    if audio:
        cmd += ["-i", audio]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


# PNG compress_level for frames that exist only to be read back by ffmpeg once:
# level 1 encodes ~2.5x faster than the default 6 and these files are deleted as
# soon as the mux finishes. Frames the caller asked to keep use the default.
_TRANSIENT_PNG_LEVEL = 1


def render_video(
    doc: Document,
    out_path: str,
    fps: int | None = None,
    scale: float = 1.0,
    threads: int = 4,
    keep_frames: str | None = None,
    cache=None,
    audio: str | None = None,
    dpi: float = 1.0,
    media_resolver=None,
    jobs: int = 1,
    comp_path: str | None = None,
) -> str:
    """Render all frames of ``doc`` into ``out_path`` (an MP4).

    ``fps`` defaults to the composition's fps. ``scale`` renders a draft at that
    fraction of the composition size (see ``nanoframes.scale``); ``dpi``
    rasterizes at that pixel density instead, so the same drawing is delivered
    at a higher resolution. If ``keep_frames`` is set, the PNG sequence is left
    in that directory instead of a temp dir.

    ``jobs`` above 1 renders frames on that many worker processes (see
    ``nanoframes.parallel``); ``comp_path`` is the file ``doc`` was parsed from
    and is what makes that possible, since each worker parses it again for
    itself.
    """
    comp = doc.composition
    fps = fps or comp.fps

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if keep_frames:
        frame_dir = keep_frames
        os.makedirs(frame_dir, exist_ok=True)
        cleanup = False
    else:
        frame_dir = tempfile.mkdtemp(prefix="nanoframes_frames_")
        cleanup = True

    try:
        prefix = comp.composition_id or "frame"
        times = timeline.frame_times(comp)
        # A media pass swaps in extracted frames per render (a resolver is not
        # picklable), so it stays in this process and renders sequentially.
        use_jobs = 1 if media_resolver is not None else jobs
        blank = parallel.render_sequence(
            doc, comp_path or "", times, frame_dir, prefix, jobs=use_jobs,
            threads=threads, cache=cache, scale=scale, dpi=dpi,
            compress_level=None if keep_frames else _TRANSIENT_PNG_LEVEL,
        )
        if blank:
            print(f"nanoframes: {len(blank)} of {comp.frame_count} frames are fully"
                  f" transparent (first at t={blank[0]:g}s) — every element is hidden or"
                  f" off-canvas there; run `nanoframes debug <comp> --t {blank[0]:g}`.",
                  file=sys.stderr)
        return mux_frames_to_mp4(frame_dir, prefix, fps, out_path, audio=audio)
    finally:
        if cleanup:
            shutil.rmtree(frame_dir, ignore_errors=True)

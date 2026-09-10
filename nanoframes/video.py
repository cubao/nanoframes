"""Render a composition to a deterministic MP4 via FFmpeg.

The frames are rendered to a temporary PNG sequence then muxed with `ffmpeg`
into H.264 (MP4) using a fixed option set for reproducible output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from nanoframes.parse import Document
from nanoframes.render import render_frame


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
) -> str:
    """Render all frames of ``doc`` into ``out_path`` (an MP4).

    ``fps`` defaults to the composition's fps. ``scale`` renders a draft at that
    fraction of the composition size (see ``nanoframes.scale``); the MP4 comes
    out at the scaled size. If ``keep_frames`` is set, the PNG sequence is left
    in that directory instead of a temp dir.
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
        step = 1.0 / fps
        for i in range(comp.frame_count):
            t = i * step
            img = render_frame(doc, t, threads=threads, cache=cache, scale=scale)
            dst = os.path.join(frame_dir, f"{prefix}.{i:05d}.png")
            if keep_frames:
                img.save(dst)
            else:
                img.save(dst, compress_level=_TRANSIENT_PNG_LEVEL)
        return mux_frames_to_mp4(frame_dir, prefix, fps, out_path, audio=audio)
    finally:
        if cleanup:
            shutil.rmtree(frame_dir, ignore_errors=True)
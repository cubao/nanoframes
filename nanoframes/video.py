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


def render_video(
    doc: Document,
    out_path: str,
    fps: int | None = None,
    scale: str | None = None,
    threads: int = 4,
    keep_frames: str | None = None,
) -> str:
    """Render all frames of ``doc`` into ``out_path`` (an MP4).

    ``fps`` defaults to the composition's fps; ``scale`` is passed straight to
    ffmpeg's ``-vf scale=`` (e.g. ``720:720``). If ``keep_frames`` is set, the
    PNG sequence is left in that directory instead of a temp dir.
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
            render_frame(doc, t, out_path=os.path.join(frame_dir, f"{prefix}.{i:05d}.png"),
                         threads=threads)

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(fps),
            "-i", os.path.join(frame_dir, f"{prefix}.%05d.png"),
        ]
        if scale:
            cmd += ["-vf", f"scale={scale}"]
        cmd += [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            out_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path
    finally:
        if cleanup:
            shutil.rmtree(frame_dir, ignore_errors=True)
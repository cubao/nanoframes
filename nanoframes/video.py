"""Render a composition to a deterministic MP4 via FFmpeg.

Two ways to get the frames to `ffmpeg`, and the cheap one is the default:

* **raw RGB on a pipe** — each frame's bytes go straight down `ffmpeg`'s stdin,
  no file and no PNG codec in between. Nothing is lost on the way (PNG is
  lossless, and a frame is 8-bit RGBA to begin with), and the measured cost of
  the round trip was 40% of the whole render: 180 frames of 960x540 took 2.50s
  as PNGs and 1.30s as raw bytes, with the output MP4 identical byte for byte.
* **a PNG sequence** — what `--keep-frames` uses, because those frames are the
  deliverable rather than a step.

Both feed the same fixed encoder options (H.264, yuv420p, crf 18), so the two
paths produce the same file; `tests/test_video_pipe.py` asserts exactly that.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from nanoframes import parallel, timeline
from nanoframes.parse import Document
from nanoframes.scale import draft_size


def _encoder_args(fps: int, audio: str | None) -> list:
    """The encoder half of the command, shared by both input paths.

    One definition so a change to the codec settings cannot move one path and
    leave the other behind — which would make the same composition encode to two
    different files depending on whether `--keep-frames` was passed.
    """
    cmd = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    return cmd


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
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
           "-i", os.path.join(frame_dir, f"{prefix}.%05d.png")]
    if audio:
        cmd += ["-i", audio]
    cmd += _encoder_args(fps, audio) + [out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def mux_raw_frames_to_mp4(
    frame_dir: str,
    prefix: str,
    frame_count: int,
    fps: int,
    width: int,
    height: int,
    out_path: str,
    audio: str | None = None,
) -> str:
    """Stream a directory of raw RGB frames into an MP4.

    The frames are copied into `ffmpeg`'s stdin in index order, so the encoder
    never sees a file and the frame bytes are never PNG-encoded and decoded
    again. The width and height are the *rendered* ones (the canvas after
    ``--scale``/``--dpi``), not the composition's, because that is the size of
    the bytes on disk.

    The input is ``-f rawvideo -pix_fmt rgb24``, the exact inverse of the writer
    in ``nanoframes.parallel``; both halves name the format, so they cannot
    drift. ``frame_count`` is passed in rather than read off the directory: the
    directory is ours, but counting files is how a stray leftover becomes a
    video with a frame from the previous render spliced into it.
    """
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{width}x{height}", "-r", str(fps), "-i", "-"]
    if audio:
        cmd += ["-i", audio]
    cmd += _encoder_args(fps, audio) + [out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for index in range(frame_count):
            path = os.path.join(frame_dir, f"{prefix}.{index:05d}.rgb")
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    proc.stdin.write(chunk)
        # `communicate()` is what closes stdin and reaps the process; closing it
        # by hand first makes communicate flush a closed pipe (ValueError).
        _, err = proc.communicate()
    except BrokenPipeError:
        # The reader hung up while frames were still going in. That is not
        # automatically a failure: `-shortest` ends the video when a shorter
        # audio track runs out, so ffmpeg closes the pipe *on purpose* after
        # consuming the frames it wants. A non-zero exit below is still the
        # error path — and its stderr is the only thing that explains it.
        err = proc.stderr.read()
        proc.wait()
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd, b"", err) from None
        return out_path
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, b"", err)
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

    Frames reach the encoder as **raw RGB on a pipe** unless ``keep_frames``
    asks for them, in which case they are written as PNGs (the caller wants the
    pictures, not a step in a pipeline). See the module docstring for the
    measurement behind that choice.
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
        pixel_format = "png" if keep_frames else "rgb"
        blank = parallel.render_sequence(
            doc, comp_path or "", times, frame_dir, prefix, jobs=use_jobs,
            threads=threads, cache=cache, scale=scale, dpi=dpi,
            compress_level=None if keep_frames else _TRANSIENT_PNG_LEVEL,
            pixel_format=pixel_format,
        )
        if blank:
            print(f"nanoframes: {len(blank)} of {comp.frame_count} frames are fully"
                  f" transparent (first at t={blank[0]:g}s) — every element is hidden or"
                  f" off-canvas there; run `nanoframes debug <comp> --t {blank[0]:g}`.",
                  file=sys.stderr)
        if keep_frames:
            return mux_frames_to_mp4(frame_dir, prefix, fps, out_path, audio=audio)
        width, height = draft_size(comp.width, comp.height, scale * dpi)
        return mux_raw_frames_to_mp4(frame_dir, prefix, len(times), fps, width, height,
                                     out_path, audio=audio)
    finally:
        if cleanup:
            shutil.rmtree(frame_dir, ignore_errors=True)

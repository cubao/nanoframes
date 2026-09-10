"""Offline, deterministic rendering of Lottie (Bodymovin) JSON animations.

`nanoframes lottie <file.json> -o out.mp4` renders every frame of a Lottie
scene with the same thorvg-python engine that rasterizes ``.nf.svg``
compositions, then muxes the PNG sequence with ffmpeg — no browser, no
Skottie. The intended source is any Lottie scene produced by the
text-to-lottie ecosystem (lottie.json deliverables): their player is for
humans, this path turns the same JSON into a deterministic MP4 offline.

Rendering model
---------------
- Canvas size comes from the scene's own ``w``/``h`` (times ``--scale``).
- Frame rate and length come from the scene: ``fr`` (fps) and the loader's
  total frame count (``op - ip``).
- Frames are drawn with ThorVG's native Lottie loader via
  ``LottieAnimation``: ``picture.load(path)`` parses, ``set_frame(i)`` seeks,
  ``canvas.add(picture)`` + draw/sync rasterizes (the binding's documented
  ``canvas.push`` API is outdated — it does not exist on SwCanvas).
- Determinism matches ``.nf.svg`` rendering: same file, same library, same
  frames. There is no frame cache (each render is a full pass); a content
  hash is a cheap way to skip re-renders.
- Images/fonts referenced by the scene resolve the way ThorVG's Lottie
  loader resolves them (local paths are relative to the process CWD). The
  CLI changes CWD to the scene's directory so ``lottie.json`` scenes with
  sibling assets "just work"; resolve ``-o``/``--keep-frames`` to absolute
  paths first.

Coverage and limits
-------------------
ThorVG's Lottie loader covers shapes, strokes, fills/gradients, images,
masks/mattes, modifiers (trim paths, repeaters), layer effects, text and
most expressions (~75%, JerryScript); audio is not processed. The loader's
byte-for-byte behavior is the contract — when in doubt, render a frame and
look. Scene-level ``markers`` are readable via ``get_marker``.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile

import thorvg_python as tvg

from nanoframes.scale import draft_size
from nanoframes.video import mux_frames_to_mp4


class LottieError(ValueError):
    """Raised when a Lottie file cannot be parsed or rendered."""


def load_scene(path: str) -> dict:
    """Read the Lottie JSON and return it with resolved context.

    Returns ``{path, dir, json, width, height, fps, ip, op}``; ``fps`` falls
    back to 30 when the file has no ``fr``.
    """
    if not os.path.exists(path):
        raise LottieError(f"no such lottie file: {path}")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise LottieError(f"{path}: not readable Lottie JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise LottieError(f"{path}: Lottie scene must be a JSON object")
    w = int(data.get("w") or 0)
    h = int(data.get("h") or 0)
    if w <= 0 or h <= 0:
        raise LottieError(f"{path}: scene must carry positive w/h")
    if not data.get("layers"):
        raise LottieError(f"{path}: scene has no layers")
    return {
        "path": os.path.abspath(path),
        "dir": os.path.dirname(os.path.abspath(path)),
        "json": data,
        "width": w,
        "height": h,
        "fps": int(data.get("fr") or 30),
        "ip": int(data.get("ip") or 0),
        "op": int(data.get("op") or 0),
    }


def render_lottie_frames(
    path: str,
    frame_dir: str,
    prefix: str = "frame",
    threads: int = 1,
    scale: float = 1.0,
) -> tuple[int, int, int]:
    """Render every frame of ``path`` into ``<frame_dir>/<prefix>.NNNNN.png``.

    ``scale`` rasterizes at that fraction of the scene's own size (a draft).
    Returns ``(fps, frame_count, duration_frames)``. Deterministic: the same
    input yields byte-identical PNGs (same engine, same loader, same order).
    """
    scene = load_scene(path)
    os.makedirs(frame_dir, exist_ok=True)
    width, height = draft_size(scene["width"], scene["height"], scale)

    engine = tvg.Engine(threads=threads)
    canvas = tvg.SwCanvas(engine)
    try:
        canvas.set_target(width, height)
        anim = tvg.LottieAnimation(engine)
        pic = anim.get_picture()
        if int(pic.load(path)) != 0:
            raise LottieError(f"{path}: ThorVG could not load the scene")
        pic.set_size(width, height)
        canvas.add(pic)

        total = int(anim.get_total_frame()[1])
        if total <= 0:
            total = max(1, scene["op"] - scene["ip"])
        for i in range(total):
            anim.set_frame(i)
            canvas.update()
            canvas.draw(True)
            canvas.sync()
            im = canvas.get_pillow()
            im.save(os.path.join(frame_dir, f"{prefix}.{i:05d}.png"))
        return scene["fps"], total, total
    finally:
        canvas.destroy()
        engine.term()


def render_lottie_video(
    path: str,
    out_path: str,
    scale: float = 1.0,
    threads: int = 4,
    keep_frames: str | None = None,
    audio: str | None = None,
) -> str:
    """Render ``path`` to a deterministic MP4 at ``out_path``.

    ``scale`` rasterizes a draft at that fraction of the scene size.
    ``keep_frames`` leaves the PNG sequence in that directory (otherwise a
    temp dir is cleaned up). Returns ``out_path``.
    """
    out_path = os.path.abspath(out_path)
    keep_frames = os.path.abspath(keep_frames) if keep_frames else None
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # ThorVG resolves scene-relative images/fonts against the CWD; scenes
    # from the text-to-lottie world keep assets next to lottie.json.
    old_cwd = os.getcwd()
    try:
        os.chdir(os.path.dirname(path))
        scene = load_scene(path)
        if keep_frames:
            frame_dir = keep_frames
            os.makedirs(frame_dir, exist_ok=True)
            cleanup = False
        else:
            frame_dir = tempfile.mkdtemp(prefix="nanoframes_lottie_")
            cleanup = True
        try:
            prefix = scene["json"].get("nm") or "lottie"
            fps, _, _ = render_lottie_frames(path, frame_dir, prefix=prefix, threads=threads,
                                             scale=scale)
            return mux_frames_to_mp4(frame_dir, prefix, fps, out_path, audio=audio)
        finally:
            if cleanup:
                shutil.rmtree(frame_dir, ignore_errors=True)
    finally:
        os.chdir(old_cwd)

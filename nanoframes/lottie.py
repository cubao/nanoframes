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
- A Lottie scene is transparent by design: the format has no scene-level
  background property (top level is ``nm/layers/ver/fr/ip/op/w/h/assets/
  markers/slots``), so the backdrop belongs to whatever plays the animation.
  Scenes are authored against the player's page — usually white — so frames
  are composited onto ``background`` (white by default, ``--bg`` on the CLI)
  before they are written or muxed. Otherwise the alpha is simply dropped by
  ``yuv420p`` and a scene drawn for a light page lands on black. Pass
  ``background=None`` to keep the alpha channel instead.
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

from nanoframes.render import set_canvas_target
from nanoframes.scale import draft_size
from nanoframes.video import mux_frames_to_mp4

#: The backdrop a Lottie frame is composited onto when none is given. Scenes
#: are authored against a player's page, and that page is white in the Lottie
#: ecosystem's previewers — so a scene that ships no background of its own
#: reads the way its author saw it, instead of as shapes on black.
DEFAULT_BACKGROUND = (255, 255, 255)

_NAMED_COLORS = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "none": None,
    "transparent": None,
}


class LottieError(ValueError):
    """Raised when a Lottie file cannot be parsed or rendered."""


def parse_background(value) -> tuple[int, int, int] | None:
    """Turn a ``--bg`` value into an ``(r, g, b)`` tuple, or ``None`` to keep alpha.

    Accepts ``none``/``transparent``, ``white``/``black``, ``#rgb``/``#rrggbb``,
    and ``"r,g,b"``. Raises ``LottieError`` on anything else — a typo in a
    color should not silently render as some other color.
    """
    if value is None:
        return DEFAULT_BACKGROUND
    if isinstance(value, tuple):
        return value
    text = str(value).strip().lower()
    if text in _NAMED_COLORS:
        return _NAMED_COLORS[text]
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 6:
            try:
                return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                pass
        raise LottieError(f"not a color: {value!r} (use #rrggbb)")
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) == 3:
            try:
                channels = tuple(int(p) for p in parts)
            except ValueError:
                channels = ()
            if len(channels) == 3 and all(0 <= c <= 255 for c in channels):
                return channels
    raise LottieError(
        f"not a color: {value!r} (use #rrggbb, 'r,g,b', white, black, or none)"
    )


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
    background: tuple[int, int, int] | None = DEFAULT_BACKGROUND,
) -> tuple[int, int, int]:
    """Render every frame of ``path`` into ``<frame_dir>/<prefix>.NNNNN.png``.

    ``scale`` rasterizes at that fraction of the scene's own size (a draft).
    ``background`` is the color transparent regions are composited onto;
    ``None`` keeps the alpha channel (PNG only — ``yuv420p`` cannot carry it,
    so an MP4 of alpha frames flattens onto black).

    Returns ``(fps, frame_count, duration_frames)``. Deterministic: the same
    input yields byte-identical PNGs (same engine, same loader, same order).
    """
    scene = load_scene(path)
    os.makedirs(frame_dir, exist_ok=True)
    width, height = draft_size(scene["width"], scene["height"], scale)

    engine = tvg.Engine(threads=threads)
    canvas = tvg.SwCanvas(engine)
    try:
        set_canvas_target(canvas, width, height)
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
            if background is not None:
                im = flatten(im, background)
            im.save(os.path.join(frame_dir, f"{prefix}.{i:05d}.png"))
        return scene["fps"], total, total
    finally:
        canvas.destroy()
        engine.term()


def flatten(im, background: tuple[int, int, int]):
    """Composite an RGBA frame onto ``background``, returning an opaque RGB image."""
    from PIL import Image  # heavy import, keep it lazy

    base = Image.new("RGBA", im.size, tuple(background) + (255,))
    return Image.alpha_composite(base, im.convert("RGBA")).convert("RGB")


def render_lottie_video(
    path: str,
    out_path: str,
    scale: float = 1.0,
    threads: int = 4,
    keep_frames: str | None = None,
    audio: str | None = None,
    background: tuple[int, int, int] | None = DEFAULT_BACKGROUND,
) -> str:
    """Render ``path`` to a deterministic MP4 at ``out_path``.

    ``scale`` rasterizes a draft at that fraction of the scene size.
    ``keep_frames`` leaves the PNG sequence in that directory (otherwise a
    temp dir is cleaned up). ``background`` is documented on
    ``render_lottie_frames``. Returns ``out_path``.
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
                                             scale=scale, background=background)
            return mux_frames_to_mp4(frame_dir, prefix, fps, out_path, audio=audio)
        finally:
            if cleanup:
                shutil.rmtree(frame_dir, ignore_errors=True)
    finally:
        os.chdir(old_cwd)

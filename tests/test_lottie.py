"""Lottie import-render tests: ThorVG's native loader, offline and deterministic."""

import hashlib
import os

import pytest

from nanoframes.lottie import (
    LottieError,
    parse_background,
    load_scene,
    render_lottie_frames,
    render_lottie_video,
)

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
BOUNCE = os.path.join(EXAMPLES, "lottie", "bounce.json")


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _alpha_scene(path: str, opacity: int = 50, color=(1, 1, 1), size: int = 64) -> str:
    """A full-canvas rectangle at ``opacity`` percent: the alpha probe scene."""
    import json

    scene = {
        "v": "5.7.0", "fr": 30, "ip": 0, "op": 1,
        "w": size, "h": size, "nm": "alpha", "assets": [],
        "layers": [{
            "ty": 4, "nm": "rect", "ip": 0, "op": 1, "st": 0, "sr": 1,
            "ks": {"o": {"a": 0, "k": 100}, "r": {"a": 0, "k": 0},
                   "a": {"a": 0, "k": [0, 0, 0]}, "s": {"a": 0, "k": [100, 100, 100]},
                   "p": {"a": 0, "k": [0, 0, 0]}},
            "shapes": [{"ty": "gr", "it": [
                {"ty": "rc", "d": 1, "s": {"a": 0, "k": [size, size]},
                 "p": {"a": 0, "k": [0, 0]}, "r": {"a": 0, "k": 0}},
                {"ty": "fl", "c": {"a": 0, "k": list(color) + [1]},
                 "o": {"a": 0, "k": opacity}, "r": 1},
                {"ty": "tr", "p": {"a": 0, "k": [size / 2, size / 2]},
                 "a": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [100, 100]},
                 "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100}},
            ]}],
        }],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(scene, fh)
    return path


def test_semi_transparent_pixels_are_not_darkened(tmp_path):
    """A 50% white fill must read back as (255,255,255,127).

    ThorVG's canvas defaults to an alpha-*premultiplied* colorspace while the
    binding hands that buffer to Pillow's ``frombuffer("RGBA")``, which reads
    straight alpha. On the default the pixel came back ``(127,127,127,127)`` —
    darkened by its own alpha — and the MP4 path (``yuv420p`` drops alpha) kept
    the darkened RGB, so every semi-transparent area of a picture rendered too
    dark and desaturated.
    """
    from PIL import Image

    scene = _alpha_scene(str(tmp_path / "alpha.json"), opacity=50)
    out = tmp_path / "frames"
    render_lottie_frames(scene, str(out), prefix="a", background=None)
    im = Image.open(out / "a.00000.png").convert("RGBA")
    r, g, b, a = im.getpixel((32, 32))
    assert a == 127
    assert (r, g, b) == (255, 255, 255), (
        f"semi-transparent white came back {(r, g, b, a)} — premultiplied alpha leaked through"
    )


def test_frames_composite_onto_a_backdrop(tmp_path):
    """The default backdrop is white and every frame comes out opaque.

    A Lottie scene has no scene-level background (the format has no such
    property), so its transparent regions have to land on something. Left
    unhandled, ffmpeg discards the alpha and a scene drawn for a light page
    renders onto black.
    """
    from PIL import Image

    out = tmp_path / "frames"
    render_lottie_frames(BOUNCE, str(out), prefix="bounce")
    im = Image.open(out / "bounce.00000.png").convert("RGBA")
    assert im.getchannel("A").getextrema() == (255, 255), "default render is not opaque"
    assert im.getpixel((2, 2)) == (255, 255, 255, 255)

    black = tmp_path / "black"
    render_lottie_frames(BOUNCE, str(black), prefix="bounce", background=(0, 0, 0))
    assert Image.open(black / "bounce.00000.png").convert("RGBA").getpixel((2, 2)) == (
        0, 0, 0, 255)


def test_parse_background():
    assert parse_background(None) == (255, 255, 255)
    assert parse_background("white") == (255, 255, 255)
    assert parse_background("black") == (0, 0, 0)
    assert parse_background("#1e1e2e") == (30, 30, 46)
    assert parse_background("#f0a") == (255, 0, 170)
    assert parse_background("12, 34, 56") == (12, 34, 56)
    assert parse_background("none") is None
    assert parse_background("transparent") is None
    for bad in ("puce", "#12345", "1,2", "300,0,0", "1,2,x"):
        with pytest.raises(LottieError):
            parse_background(bad)


def test_load_scene_metadata():
    s = load_scene(BOUNCE)
    assert s["width"] == 512 and s["height"] == 512
    assert s["fps"] == 30
    assert s["op"] - s["ip"] == 30


def test_load_rejects_bad_file(tmp_path):
    bogus = tmp_path / "x.json"
    bogus.write_text("[]")
    with pytest.raises(LottieError):
        load_scene(str(bogus))
    with pytest.raises(LottieError):
        load_scene(str(tmp_path / "missing.json"))


def test_render_frames_deterministic_and_animated(tmp_path):
    d1 = str(tmp_path / "a")
    d2 = str(tmp_path / "b")
    fps, total, _ = render_lottie_frames(BOUNCE, d1, prefix="bounce")
    assert fps == 30 and total == 30
    assert sorted(os.listdir(d1)) == [f"bounce.{i:05d}.png" for i in range(30)]

    # deterministic: same file, same engine -> byte-identical frames
    render_lottie_frames(BOUNCE, d2, prefix="bounce")
    assert _sha(os.path.join(d1, "bounce.00000.png")) == _sha(os.path.join(d2, "bounce.00000.png"))
    assert _sha(os.path.join(d1, "bounce.00015.png")) == _sha(os.path.join(d2, "bounce.00015.png"))

    # animated: first, middle, and last frames all differ (ball travels)
    shas = [_sha(os.path.join(d1, f"bounce.{i:05d}.png")) for i in (0, 15, 29)]
    assert len(set(shas)) == 3

    # ink present on the canvas (not a blank render)
    from PIL import Image

    a = Image.open(os.path.join(d1, "bounce.00000.png")).convert("RGBA").split()[3]
    assert a.getbbox() is not None


def test_render_video_mp4(tmp_path):
    if not shutil_which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    out = str(tmp_path / "bounce.mp4")
    render_lottie_video(BOUNCE, out)
    assert os.path.getsize(out) > 0
    assert out.startswith("/")  # absolute out survives the scene-dir chdir


def shutil_which(name):
    import shutil

    return shutil.which(name)


def test_cli_lottie(tmp_path):
    from nanoframes.cli import main

    import contextlib
    import io

    buf = io.StringIO()
    keep = str(tmp_path / "frames")
    out = str(tmp_path / "out.mp4")
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(["lottie", BOUNCE, "-o", out, "--keep-frames", keep])
    if not shutil_which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    assert code == 0, buf.getvalue()
    assert os.path.exists(out) and os.path.getsize(out) > 0
    assert os.listdir(keep), "--keep-frames left the PNG sequence behind"
    assert "wrote" in buf.getvalue()


def test_cli_lottie_background_flag(tmp_path):
    from nanoframes.cli import main

    import contextlib
    import io
    from PIL import Image

    keep = str(tmp_path / "frames")
    out = str(tmp_path / "out.mp4")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(["lottie", BOUNCE, "-o", out, "--keep-frames", keep, "--bg", "#1e1e2e"])
    if not shutil_which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    assert code == 0, buf.getvalue()
    first = sorted(os.listdir(keep))[0]
    assert Image.open(os.path.join(keep, first)).convert("RGBA").getpixel((2, 2)) == (
        30, 30, 46, 255)

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        assert main(["lottie", BOUNCE, "-o", out, "--bg", "puce"]) == 2
    assert "not a color" in buf.getvalue()


def test_cli_lottie_missing_file(tmp_path):
    from nanoframes.cli import main

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(["lottie", str(tmp_path / "nope.json"), "-o", str(tmp_path / "x.mp4")])
    assert code == 2
    assert "no such lottie file" in buf.getvalue()

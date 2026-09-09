"""Lottie import-render tests: ThorVG's native loader, offline and deterministic."""

import hashlib
import os

import pytest

from nanoframes.lottie import LottieError, load_scene, render_lottie_frames, render_lottie_video

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
BOUNCE = os.path.join(EXAMPLES, "lottie", "bounce.json")


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


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


def test_cli_lottie_missing_file(tmp_path):
    from nanoframes.cli import main

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(["lottie", str(tmp_path / "nope.json"), "-o", str(tmp_path / "x.mp4")])
    assert code == 2
    assert "no such lottie file" in buf.getvalue()

"""CLI end-to-end smoke tests."""

import os
import shutil

import pytest

from nanoframes.cli import main

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
TITLE = os.path.join(EXAMPLES, "title-card.nf.svg")


def run(argv):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(argv)
    return code, buf.getvalue()


def test_no_args_prints_docs_skill_guide():
    code, out = run([])
    assert code == 2
    assert "composition.md" in out
    assert "SKILL.md" in out


def test_help_prints_docs_skill_guide():
    """Agents reach for --help first; it must carry the docs/skill pointer too."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        with pytest.raises(SystemExit) as excinfo:
            main(["--help"])
    assert excinfo.value.code == 0
    out = buf.getvalue()
    # the pointer block, same as the bare invocation
    assert "composition.md" in out
    assert "lottie.md" in out
    assert "SKILL.md" in out
    # ... alongside the command list
    assert "init" in out and "lottie" in out and "render" in out


def test_init_creates_composition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _ = run(["init", "hello"])
    assert code == 0
    path = tmp_path / "hello.nf.svg"
    assert os.path.exists(path)
    content = path.read_text()
    assert "data-composition-id=\"hello\"" in content


def test_check_ok_on_example():
    code, out = run(["check", TITLE])
    assert code == 0
    assert "ok" in out


def test_check_fails_on_broken(tmp_path):
    bad = tmp_path / "bad.nf.svg"
    bad.write_text('<svg xmlns="http://www.w3.org/2000/svg" data-width="0"></svg>')
    code, out = run(["check", str(bad)])
    assert code == 1
    assert "error" in out


def test_check_warns_on_missing_image_asset(tmp_path):
    """A missing asset renders an empty layer, so check must say so."""
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100" '
        'data-duration="1"><image id="board" href="board_export/board.png" '
        'width="100" height="100"/></svg>'
    )
    code, out = run(["check", str(comp)])
    assert code == 0  # a warning, not a refusal to render
    assert "board_export/board.png" in out
    assert "not found" in out


def test_check_accepts_present_image_asset(tmp_path):
    import shutil

    comp = tmp_path / "c.nf.svg"
    shutil.copy(os.path.join(EXAMPLES, "assets", "dot.png"), tmp_path / "dot.png")
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100" '
        'data-duration="1"><image id="dot" href="dot.png" width="100" height="100"/></svg>'
    )
    code, out = run(["check", str(comp)])
    assert code == 0
    assert "not found" not in out


def test_render_single_frame(tmp_path):
    dst = str(tmp_path / "frame.png")
    code, out = run(["render", TITLE, "--t", "2.0", "-o", dst])
    assert code == 0
    assert os.path.exists(dst)
    assert os.path.getsize(dst) > 0


def test_render_batch(tmp_path):
    outdir = str(tmp_path / "frames")
    code, out = run(["render", TITLE, "-o", outdir])
    assert code == 0
    files = sorted(os.listdir(outdir))
    assert len(files) == 120  # 4s * 30fps
    assert files[0].endswith(".png")


def test_render_refuses_lint_errors(tmp_path):
    bad = tmp_path / "bad.nf.svg"
    # valid XML, but the animation targets an element that does not exist
    bad.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100" '
        'data-duration="1">'
        '<rect id="real" width="10" height="10" fill="#000"/>'
        '<script type="application/nanoframes+json"><![CDATA['
        '{"animations":[{"target":"#nope","keyframes":[{"t":0,"opacity":0}]}]}'
        ']]></script></svg>'
    )
    code, out = run(["render", str(bad), "--t", "0.5"])
    assert code == 1
    assert "lint errors" in out


def test_video_exports_mp4(tmp_path):
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    out = str(tmp_path / "clip.mp4")
    code, _ = run(["video", TITLE, "-o", out])
    assert code == 0
    assert os.path.exists(out)
    assert os.path.getsize(out) > 1024
    # probe: 4s at 30fps => ~120 frames
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=nb_frames,duration",
                           "-of", "default=noprint_wrappers=1", out],
                          capture_output=True, text=True).stdout
    assert "duration=" in info


def test_video_muxes_audio(tmp_path):
    import shutil
    import subprocess as sp

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    wav = str(tmp_path / "tone.wav")
    sp.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=1",
            "-c:a", "pcm_s16le", wav], check=True, capture_output=True)
    out = str(tmp_path / "av.mp4")
    code, _ = run(["video", TITLE, "-o", out, "--audio", wav])
    assert code == 0
    info = sp.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=codec_name",
                    "-of", "default=noprint_wrappers=1", out],
                   capture_output=True, text=True).stdout
    assert "aac" in info
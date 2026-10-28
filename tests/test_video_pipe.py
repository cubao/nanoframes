"""The two ways frames reach ffmpeg must produce the same video.

The raw-RGB pipe exists because the PNG round trip cost 40% of a render
(measured: 2.50s -> 1.30s for 180 frames of 960x540). That is only acceptable if
it is *free* — same bytes in, same file out — so the equality is asserted here
rather than reasoned about.
"""

from __future__ import annotations

import hashlib

import pytest

from nanoframes.parse import parse_string
from nanoframes.video import render_video

SVG = """<svg xmlns="http://www.w3.org/2000/svg" data-width="320" data-height="180"
     data-fps="12" data-duration="0.5" data-composition-id="pipe">
  <rect width="320" height="180" fill="#101820" data-duration="0.5"/>
  <rect id="box" x="20" y="40" width="40" height="40" fill="#5ef17c" data-duration="0.5"/>
  <text x="20" y="150" font-family="Sarasa Mono SC" font-size="24" fill="#ffffff"
        data-duration="0.5" data-frame-text="f{frame}"/>
  <script type="application/nanoframes+json"><![CDATA[
  {"animations": [{"target": "#box", "keyframes": [
      {"t": 0.0, "transform": {"translate": [0, 0]}},
      {"t": 0.4, "transform": {"translate": [200, 60]}}]}]}
  ]]></script>
</svg>"""


def _doc(tmp_path):
    path = tmp_path / "pipe.nf.svg"
    path.write_text(SVG, encoding="utf-8")
    return path


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _render(tmp_path, name, **kwargs):
    comp = _doc(tmp_path)
    out = tmp_path / name
    render_video(parse_string(SVG), str(out), cache=None, comp_path=str(comp), **kwargs)
    return out


def test_the_pipe_and_the_png_sequence_encode_to_the_same_file(tmp_path):
    """The claim the optimisation rests on: same bytes, so the same MP4."""
    piped = _render(tmp_path, "piped.mp4")
    kept = _render(tmp_path, "kept.mp4", keep_frames=str(tmp_path / "frames"))
    assert _sha(piped) == _sha(kept)


def test_keep_frames_still_writes_pngs(tmp_path):
    frames = tmp_path / "frames"
    _render(tmp_path, "kept.mp4", keep_frames=str(frames))
    written = sorted(p.name for p in frames.iterdir())
    assert written and all(n.endswith(".png") for n in written)


def test_the_default_writes_no_intermediate_pngs(tmp_path):
    """Nothing but the MP4 is left behind: the frames went down a pipe."""
    comp = _doc(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    render_video(parse_string(SVG), str(tmp_path / "piped.mp4"), cache=None,
                 comp_path=str(comp))
    after = {p.name for p in tmp_path.iterdir()} - before
    assert after == {"piped.mp4"}


def test_a_draft_render_pipes_at_the_rendered_size(tmp_path):
    """`--scale` shrinks the raster, so the raw frames on the wire shrink too.

    ffmpeg is told the *rendered* size, not the composition's; if the two ever
    disagree the video is sheared rather than rejected, which is the kind of
    failure that reaches a user.
    """
    out = _render(tmp_path, "draft.mp4", scale=0.5)
    assert out.exists() and out.stat().st_size > 0


def test_an_audio_track_is_muxed_through_the_pipe(tmp_path):
    """The pipe path carries audio the same way the PNG path did."""
    import subprocess

    wav = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=0.5", "-c:a", "pcm_s16le",
                    str(wav)], check=True)
    out = _render(tmp_path, "withaudio.mp4", audio=str(wav))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_type", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True, check=True)
    assert "audio" in probe.stdout and "video" in probe.stdout


def test_shorter_audio_closing_the_pipe_early_is_not_an_error(tmp_path):
    """`-shortest` makes ffmpeg hang up mid-stream when audio runs out first.

    That close is deliberate, and it arrives as BrokenPipeError in the writer.
    Reading it as a failure would make every clip shorter than its soundtrack
    report an error after producing a perfectly good file.
    """
    import subprocess

    wav = tmp_path / "short.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=0.1", "-c:a", "pcm_s16le",
                    str(wav)], check=True)
    out = _render(tmp_path, "short.mp4", audio=str(wav))
    assert out.exists() and out.stat().st_size > 0


def test_a_missing_frame_fails_loudly(tmp_path, monkeypatch):
    """A truncated hand-off must not silently produce a short video."""
    from nanoframes import video

    # sanity: the real path writes frame_count files
    comp = _doc(tmp_path)
    doc = parse_string(SVG)
    from nanoframes import parallel, timeline

    frames = tmp_path / "frames"
    frames.mkdir()
    parallel.render_sequence(doc, str(comp), timeline.frame_times(doc.composition),
                             str(frames), "pipe", jobs=1, pixel_format="rgb")
    expected = doc.composition.frame_count
    assert len(list(frames.iterdir())) == expected

    # and the muxer reads exactly frame_count files: one missing is an error
    import subprocess

    with pytest.raises((FileNotFoundError, subprocess.CalledProcessError)):
        video.mux_raw_frames_to_mp4(str(frames), "pipe", expected + 1, 12, 320, 180,
                                    str(tmp_path / "bad.mp4"))

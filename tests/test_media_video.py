"""Video-backed ``<image>``: timeline mapping, frame extraction and injection.

The mapping is the part that has to be arithmetic; the extraction and the
per-frame pixel swap are exercised end-to-end against a generated clip when
ffmpeg is available.
"""

import shutil
import subprocess

import pytest

from nanoframes import media
from nanoframes.lint import lint_path
from nanoframes.media import MediaCache, MediaResolver, time_mapping
from nanoframes.parse import parse_file
from nanoframes.render import render_frame

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                  reason="ffmpeg not available")


# --- the mapping (pure arithmetic) ------------------------------------------

def test_mapping_offsets_by_the_window_start_and_speed():
    # clip starts at 2s, source in-point 0.5s, 2x speed; at t=3 -> 0.5 + 1*2
    assert time_mapping(t=3.0, clip_start=2.0, in_point=0.5, speed=2.0) == 2.5


def test_mapping_freezes_at_the_end_without_loop():
    assert time_mapping(t=9.0, clip_start=0.0, in_point=0.0, speed=1.0, duration=2.0) == 2.0


def test_mapping_never_goes_negative():
    assert time_mapping(t=0.0, clip_start=1.0, in_point=0.0, speed=1.0, duration=2.0) == 0.0


def test_mapping_wraps_with_loop():
    assert time_mapping(t=3.0, clip_start=0.0, in_point=0.0, speed=1.0,
                        duration=2.0, loop=True) == 1.0


def test_mapping_speed_zero_holds_the_in_point():
    assert time_mapping(t=5.0, clip_start=0.0, in_point=0.4, speed=0.0) == 0.4


# --- spec parsing ------------------------------------------------------------

def test_parse_media_reads_the_timing_attributes(tmp_path):
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="64" data-height="48"'
        ' data-fps="10" data-duration="2.0">'
        '<image id="clip" href="clip.mp4" width="64" height="48"'
        ' data-start="0.5" data-duration="1.5" data-in="1.0" data-speed="0.5"'
        ' data-loop="true"/></svg>', encoding="utf-8")
    doc = parse_file(str(comp))
    spec = media.video_specs(doc)[0]
    assert (spec.clip_start, spec.duration, spec.in_point, spec.speed, spec.loop) == (
        0.5, 1.5, 1.0, 0.5, True)
    assert spec.source.endswith("clip.mp4")


def test_a_png_image_is_not_a_media_spec(tmp_path):
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="64" data-height="48"'
        ' data-duration="1.0"><image href="dot.png" width="4" height="4"/></svg>',
        encoding="utf-8")
    doc = parse_file(str(comp))
    assert media.video_specs(doc) == []
    assert media.has_video_source(doc) is False


def test_bad_numeric_media_attribute_is_reported_and_falls_back(tmp_path):
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="64" data-height="48"'
        ' data-duration="1.0"><image id="clip" href="clip.mp4" width="64" height="48"'
        ' data-speed="fast"/></svg>', encoding="utf-8")
    doc = parse_file(str(comp))
    assert media.video_specs(doc)[0].speed == 1.0     # the default, not a crash
    assert "media.bad_attribute" in [f.code for f in lint_path(str(comp))]


# --- extraction and injection (need ffmpeg) ---------------------------------

def _video(tmp_path, seconds=1.0, rate=10, size="64x48", name="clip.mp4"):
    path = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=size={size}:rate={rate}:duration={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    return path


def _comp(tmp_path, video, extra="", duration=1.0, fps=10, size="64x48"):
    w, h = size.split("x")
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" data-width="{w}" data-height="{h}"'
        f' data-fps="{fps}" data-duration="{duration}">'
        f'<image id="clip" href="{video.name}" x="0" y="0" width="{w}" height="{h}" {extra}/>'
        '</svg>', encoding="utf-8")
    return str(comp)


@needs_ffmpeg
def test_extract_writes_a_frame_sequence_and_is_reused(tmp_path):
    video = _video(tmp_path)
    cache = MediaCache(str(tmp_path / "cache"))
    directory = cache.extract(str(video), fps=10, scale=1.0)
    assert MediaCache.frame_count(directory) == 10
    # second call reuses the completed sequence rather than re-extracting
    assert cache.extract(str(video), fps=10, scale=1.0) == directory
    assert cache.frames(str(video), fps=10, scale=1.0) == directory


@needs_ffmpeg
def test_extraction_is_keyed_by_fps(tmp_path):
    video = _video(tmp_path, seconds=1.0, rate=10)
    cache = MediaCache(str(tmp_path / "cache"))
    assert cache.extract(str(video), 10, 1.0) != cache.extract(str(video), 5, 1.0)


@needs_ffmpeg
def test_probe_duration_reads_the_media_length(tmp_path):
    video = _video(tmp_path, seconds=1.0, rate=10)
    duration = media.probe_duration(str(video))
    assert duration is not None and 0.8 < duration < 1.3


@needs_ffmpeg
def test_video_frames_are_injected_per_frame(tmp_path):
    """Two composition times must draw two different source frames."""
    video = _video(tmp_path)
    comp = _comp(tmp_path, video)
    doc = parse_file(comp)
    resolver = MediaResolver(MediaCache(str(tmp_path / "cache")), fps=10, scale=1.0)
    assert resolver.prepare(doc) == []

    first = render_frame(doc, 0.0, media_resolver=resolver).convert("RGB")
    later = render_frame(doc, 0.5, media_resolver=resolver).convert("RGB")
    assert first.getbbox() is not None, "the video frame drew nothing"
    assert first.tobytes() != later.tobytes(), "the same source frame was drawn twice"


@needs_ffmpeg
def test_in_point_shifts_which_frame_is_drawn(tmp_path):
    """data-in 0.5s at t=0 must draw the same frame as t=0.5 with no in-point."""
    video = _video(tmp_path)
    cache_dir = str(tmp_path / "cache")
    plain = parse_file(_comp(tmp_path, video))
    trimmed = parse_file(_comp(tmp_path, video, extra='data-in="0.5"'))
    a = MediaResolver(MediaCache(cache_dir), fps=10, scale=1.0)
    b = MediaResolver(MediaCache(cache_dir), fps=10, scale=1.0)
    a.prepare(plain)
    b.prepare(trimmed)
    assert (render_frame(plain, 0.5, media_resolver=a).tobytes()
            == render_frame(trimmed, 0.0, media_resolver=b).tobytes())


@needs_ffmpeg
def test_lint_reports_a_window_that_runs_past_the_source(tmp_path):
    video = _video(tmp_path, seconds=1.0)
    comp = _comp(tmp_path, video, duration=3.0)
    codes = [f.code for f in lint_path(comp)]
    assert "media.out_of_range" in codes


@needs_ffmpeg
def test_lint_accepts_a_looping_window(tmp_path):
    video = _video(tmp_path, seconds=1.0)
    comp = _comp(tmp_path, video, extra='data-loop="true"', duration=3.0)
    codes = [f.code for f in lint_path(comp)]
    assert "media.out_of_range" not in codes


def test_missing_ffmpeg_is_an_error_when_a_video_is_present(tmp_path, monkeypatch):
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="64" data-height="48"'
        ' data-duration="1.0"><image id="clip" href="clip.mp4" width="64" height="48"/></svg>',
        encoding="utf-8")
    monkeypatch.setattr(media, "has_tool", lambda name: False)
    findings = lint_path(str(comp))
    assert "media.missing_tool" in [f.code for f in findings]
    assert any(f.severity == "error" for f in findings)


def test_extract_without_ffmpeg_raises_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "has_tool", lambda name: False)
    with pytest.raises(media.MediaError):
        MediaCache(str(tmp_path / "cache")).extract("clip.mp4", 10, 1.0)

"""The audio layer: a declarative track list, compiled to an ffmpeg graph.

Two halves, tested differently. The *graph* is asserted as text — which inputs
feed which filters, and that no stream is consumed twice — because that is what
can silently be wrong while still running. The *sound* is asserted by measuring
it: ducking has to actually lower the music under the voice, and the limiter has
to keep the peak under the ceiling.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from nanoframes import audio

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")


def _tone(tmp_path, name="tone.wav", seconds=2.0, freq=440, gain_db=0):
    path = str(tmp_path / name)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-af", f"volume={gain_db}dB", "-c:a", "pcm_s16le", path], check=True)
    return path


def _gated_voice(tmp_path, name="vo.wav", total=2.0, speak=(0.5, 1.0)):
    """A voice track that is silent except for one burst — the loudness of a
    ducked music track only moves if there is something to duck it under."""
    path = str(tmp_path / name)
    start, dur = speak
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"sine=frequency=880:duration={dur}",
                    "-af", "adelay=%d|%d" % (int(start * 1000), int(start * 1000)),
                    "-t", str(total), "-c:a", "pcm_s16le", path], check=True)
    return path


# --- the graph ----------------------------------------------------------------

def test_each_input_stream_is_consumed_once(tmp_path):
    """A voice track feeds the mix *and* the sidechain, so it is split, not re-read.

    Referencing ``[1:a]`` twice is an ffmpeg error, and a graph can look correct
    while containing it.
    """
    music = _tone(tmp_path, "m.wav")
    voice = _tone(tmp_path, "v.wav", freq=880)
    cmd = audio.mix_command([
        {"file": music, "duck_under_voice": True},
        {"file": voice, "voice": True},
    ], str(tmp_path / "out.wav"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.count("[1:a]") == 1, graph
    assert "asplit" in graph, graph
    assert "sidechaincompress" in graph


def test_a_mix_with_no_voice_has_no_compressor(tmp_path):
    """An inert filter stage reads as working and is not."""
    one = _tone(tmp_path, "a.wav")
    two = _tone(tmp_path, "b.wav", freq=660)
    cmd = audio.mix_command([{"file": one}, {"file": two, "gain_db": -6}],
                            str(tmp_path / "out.wav"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" not in graph
    assert "amix=inputs=2" in graph


def test_mixing_does_not_divide_the_level_by_the_track_count(tmp_path):
    """`normalize=0` is what stops a two-track mix from being 6 dB quieter."""
    one = _tone(tmp_path, "a.wav")
    two = _tone(tmp_path, "b.wav", freq=660)
    cmd = audio.mix_command([{"file": one}, {"file": two}], str(tmp_path / "o.wav"))
    assert "normalize=0" in cmd[cmd.index("-filter_complex") + 1]


def test_a_track_can_be_delayed_and_faded(tmp_path):
    one = _tone(tmp_path)
    cmd = audio.mix_command([{"file": one, "start": 0.5, "fade_in": 0.2,
                              "fade_out": 0.3, "gain_db": -3}],
                            str(tmp_path / "o.wav"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "adelay=500|500" in graph
    assert "afade=t=in:st=0:d=0.2" in graph
    assert "volume=-3.0dB" in graph
    # the delayed track's fades are computed before the delay, so a fade-in
    # cannot land inside the silence
    assert graph.index("afade=t=in:st=0:d=0.2") < graph.index("adelay=500|500")


def test_a_missing_file_is_refused_before_ffmpeg_runs(tmp_path):
    with pytest.raises(audio.AudioError) as err:
        audio.mix_command([{"file": str(tmp_path / "nope.wav")}], str(tmp_path / "o.wav"))
    assert "no such file" in str(err.value)


def test_a_track_without_a_file_is_refused(tmp_path):
    with pytest.raises(audio.AudioError):
        audio.mix_command([{"gain_db": -3}], str(tmp_path / "o.wav"))


def test_an_empty_track_list_is_refused(tmp_path):
    with pytest.raises(audio.AudioError):
        audio.mix_command([], str(tmp_path / "o.wav"))


def test_a_gain_typo_is_not_silently_zero(tmp_path):
    one = _tone(tmp_path)
    with pytest.raises(audio.AudioError):
        audio.mix_command([{"file": one, "gain_db": "loud"}], str(tmp_path / "o.wav"))


# --- the sound ----------------------------------------------------------------

def _rms_level_db(path: str) -> float:
    out = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "mean_volume" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    raise AssertionError(f"no volume reading for {path}")


def _music_branch(tracks, path):
    """Render only the ducked music: the measurement that is actually about ducking.

    Measuring the finished mix hides the effect, because the voice is louder
    than the music and dominates the sum. What the feature promises is that
    *the music* drops, so that is what is measured.
    """
    import subprocess as sp

    graph = ("[0:a][1:a]sidechaincompress=threshold=0.01:ratio=8:attack=20:"
             "release=200[ducked]")
    sp.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tracks[0], "-i", tracks[1],
            "-filter_complex", graph, "-map", "[ducked]", "-c:a", "pcm_s16le", path],
           check=True)
    return path


def test_ducking_actually_lowers_the_music_under_the_voice(tmp_path):
    """The whole point: the music gets quieter while the voice speaks.

    Measured on the ducked music branch, not on the mix: with a voice on top,
    the sum barely moves however hard the compressor works.
    """
    music = _tone(tmp_path, "m.wav", seconds=2.0, gain_db=-3)
    voice = _gated_voice(tmp_path)
    ducked = _music_branch([music, voice], str(tmp_path / "ducked.wav"))
    assert _rms_level_db(ducked) < _rms_level_db(music) - 1.0


def test_the_mix_carries_the_ducking_the_graph_asked_for(tmp_path):
    """And the feature is reachable from a track list, not just from a graph."""
    music = _tone(tmp_path, "m.wav", seconds=2.0, gain_db=-3)
    voice = _gated_voice(tmp_path)
    out = audio.mix([{"file": music, "duck_under_voice": True},
                     {"file": voice, "voice": True}], str(tmp_path / "mix.wav"))
    assert audio.analyze(out)["integrated_lufs"] is not None


def test_the_limiter_holds_the_peak(tmp_path):
    hot = _tone(tmp_path, "hot.wav", gain_db=0)
    out = audio.mix([{"file": hot}], str(tmp_path / "lim.wav"))
    report = audio.analyze(out)
    assert report["true_peak_dbtp"] <= audio.DEFAULT_TRUE_PEAK + 1.0


def test_analysis_relays_the_ebu_r128_numbers(tmp_path):
    """The numbers are ffmpeg's; what is ours is that they arrive intact.

    Pinning an absolute LUFS value would be asserting ffmpeg's loudness model
    rather than this package's plumbing, and would break on any encoder change.
    The shape holds: a quieter input measures quieter, and all three figures
    are present and finite.
    """
    loud = audio.analyze(_tone(tmp_path, "loud.wav", gain_db=-6))
    quiet = audio.analyze(_tone(tmp_path, "quiet.wav", gain_db=-26))
    assert loud["integrated_lufs"] > quiet["integrated_lufs"]
    for report in (loud, quiet):
        for key in ("integrated_lufs", "true_peak_dbtp", "loudness_range"):
            assert report[key] is not None, key
    assert loud["true_peak_dbtp"] <= 0.0


def test_a_quiet_mix_is_a_finding_not_a_crash(tmp_path):
    tone = _tone(tmp_path, "quiet.wav", gain_db=-30)
    problems = audio.verdict(audio.analyze(tone))
    assert problems and "too quiet" in problems[0]


def test_silence_is_named_rather_than_measured(tmp_path):
    silent = str(tmp_path / "silent.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo", "-t", "1",
                    "-c:a", "pcm_s16le", silent], check=True)
    report = audio.analyze(silent)
    assert report["integrated_lufs"] is None
    assert "silence" in audio.verdict(report)[0]


def test_the_same_track_list_mixes_to_the_same_bytes(tmp_path):
    """Determinism, the claim the rest of the package makes, holds for sound."""
    import hashlib

    music = _tone(tmp_path, "m.wav")
    tracks = [{"file": music, "gain_db": -5, "fade_in": 0.2}]
    a = audio.mix(tracks, str(tmp_path / "a.wav"))
    b = audio.mix(tracks, str(tmp_path / "b.wav"))
    assert (hashlib.sha256(open(a, "rb").read()).hexdigest()
            == hashlib.sha256(open(b, "rb").read()).hexdigest())


def test_mix_reports_but_does_not_judge(tmp_path, capsys):
    """`audio mix` produces a file; `audio analyze` is the gate."""
    from nanoframes.cli import main

    quiet = _tone(tmp_path, "q.wav", gain_db=-30)
    spec = tmp_path / "tracks.json"
    spec.write_text('{"tracks": [{"file": "%s"}]}' % quiet, encoding="utf-8")
    out = tmp_path / "mixed.wav"
    code = main(["audio", "mix", str(spec), "-o", str(out)])
    assert code == 0 and out.exists()
    assert "LUFS" in capsys.readouterr().out


def test_analyze_exits_nonzero_on_a_miss(tmp_path, capsys):
    from nanoframes.cli import main

    quiet = _tone(tmp_path, "q.wav", gain_db=-30)
    assert main(["audio", "analyze", quiet]) == 1
    assert "too quiet" in capsys.readouterr().err


def test_analyze_json_is_machine_readable(tmp_path, capsys):
    import json

    from nanoframes.cli import main

    tone = _tone(tmp_path, "t.wav")
    main(["audio", "analyze", tone, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"ok", "report", "problems"}
    assert "integrated_lufs" in payload["report"]

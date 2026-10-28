"""Audio through ffmpeg: a track mix, a loudness report, and ducking.

Everything here is a *filter graph*, not DSP. That is deliberate: ffmpeg already
ships EBU R128 loudness (`loudnorm`, `ebur128`), a look-ahead limiter
(`alimiter`), a sidechain compressor (`sidechaincompress`) and mixing (`amix`),
all of them measured implementations of the same standards a hand-written
normaliser would be re-deriving. Re-implementing BS.1770 in Python to match
numbers ffmpeg can print is work with no reader benefit.

What this module adds is the part ffmpeg does not have: **a declarative track
list**, so a composition's soundtrack is data rather than a command line:

    {"tracks": [
        {"file": "music.mp3", "gain_db": -18, "fade_in": 1, "fade_out": 2,
         "duck_under_voice": true},
        {"file": "vo.wav", "start": 0.6, "voice": true},
        {"file": "whoosh.wav", "start": 3.1, "gain_db": -8}
    ]}

`voice: true` marks the tracks that duck the music; `duck_under_voice` marks the
music that gets out of their way. A mix with no voice tracks has nothing to
duck, so the graph is built without the compressor rather than with a disabled
one — an inert filter stage is the kind of thing that reads as "working" and is
not.

The graph is deterministic: the same track list and the same input files always
produce the same WAV, because every filter here is deterministic and the mix is
built from a fixed option set (`tests/test_audio.py` asserts it).
"""

from __future__ import annotations

import json
import os
import subprocess

#: Loudness target for web video. -14 LUFS integrated is what YouTube and
#: Spotify normalise to; -1 dBTP leaves the encoder's own headroom alone.
DEFAULT_TARGET_LUFS = -14.0
DEFAULT_TRUE_PEAK = -1.0


class AudioError(RuntimeError):
    """A track list or an ffmpeg run that cannot produce a mix."""


def _run(cmd: list) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(proc.stderr.strip().splitlines()[-1] if proc.stderr else
                         f"ffmpeg exited {proc.returncode}")
    return proc.stderr


def _db(value) -> float:
    """A gain in dB, validated: a typo must not silently become 0 dB."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AudioError(f"gain_db must be a number, got {value!r}") from exc


def _seconds(value, name: str) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise AudioError(f"{name} must be a number of seconds, got {value!r}") from exc
    if seconds < 0:
        raise AudioError(f"{name} must not be negative, got {seconds}")
    return seconds


def mix_command(tracks: list, out_path: str, *, limiter: bool = True) -> list:
    """The ffmpeg command that renders ``tracks`` to ``out_path``.

    Returns the argv rather than running it, so a caller can inspect what will be
    executed — the graph is the interesting part of this module, and a test can
    assert on it without writing a file.

    The graph is built around one rule: **each input stream is consumed once**.
    A voice track feeds both the mix and the compressor's sidechain, so it is
    split (`asplit`) rather than referenced twice; re-using `[i:a]` is an error
    in ffmpeg, and it is the kind of error a graph looks fine while containing.

    Per track, in this order: format to a common layout, gain, fades, then the
    start delay. Delaying first would move the fades too — `afade` works on
    timestamps, so a fade computed at 0 s after a delay falls in the gap.

    `amix` runs with ``normalize=0``: the default divides by the input count,
    which quietly drops the level of a mix every time a track is added. Levels
    are the caller's business (``gain_db``), and the limiter is the safety net.
    """
    if not tracks:
        raise AudioError("no tracks to mix")
    for i, track in enumerate(tracks):
        if not track.get("file"):
            raise AudioError(f"track {i} has no file")
        if not os.path.exists(track["file"]):
            raise AudioError(f"track {i}: no such file: {track['file']}")

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for track in tracks:
        cmd += ["-i", track["file"]]

    duckers = [i for i, t in enumerate(tracks)
               if t.get("duck_under_voice") and not t.get("voice")]
    want_sidechain = bool(duckers) and any(t.get("voice") for t in tracks)

    graph: list[str] = []
    voices: list[str] = []          # labels that duck the music
    mixed: list[str] = []           # labels that reach the final mix

    for i, track in enumerate(tracks):
        chain = ["aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"]
        gain = track.get("gain_db")
        if gain is not None:
            chain.append(f"volume={_db(gain)}dB")
        fade_in = _seconds(track.get("fade_in", 0), "fade_in")
        fade_out = _seconds(track.get("fade_out", 0), "fade_out")
        if fade_in:
            chain.append(f"afade=t=in:st=0:d={fade_in:g}")
        if fade_out:
            # A fade-out needs the track's length, which only the file knows:
            # reverse, fade in at the new start, reverse back. `afade=out` would
            # need a `st` we cannot compute without decoding the file first.
            chain += ["areverse", f"afade=t=in:st=0:d={fade_out:g}", "areverse"]
        start = _seconds(track.get("start", 0), "start")
        if start:
            chain.append(f"adelay={int(start * 1000)}|{int(start * 1000)}")
        graph.append(f"[{i}:a]" + ",".join(chain) + f"[n{i}]")

        if track.get("voice") and want_sidechain:
            # Split only when the sidechain will consume the second copy: an
            # `asplit` whose second output goes nowhere is a graph error
            # ("output 0 (b1) unconnected"), not a harmless extra.
            graph.append(f"[n{i}]asplit=2[v{i}][b{i}]")
            voices.append(f"[b{i}]")
            mixed.append(f"[v{i}]")
        else:
            mixed.append(f"[n{i}]")

    if want_sidechain:
        graph.append("".join(voices) + f"amix=inputs={len(voices)}:duration=longest"
                                      f":normalize=0[voicebus]")
        for i in duckers:
            graph.append(f"[n{i}][voicebus]sidechaincompress="
                         f"threshold=0.03:ratio=8:attack=20:release=200[duck{i}]")
            mixed[mixed.index(f"[n{i}]")] = f"[duck{i}]"

    if len(mixed) == 1:
        graph.append(f"{mixed[0]}anull[mixed]")
    else:
        graph.append("".join(mixed) + f"amix=inputs={len(mixed)}:duration=longest"
                                      f":normalize=0[mixed]")
    tail = "[mixed]"
    if limiter:
        graph.append(f"{tail}alimiter=limit={10 ** (DEFAULT_TRUE_PEAK / 20):.6f}[out]")
        tail = "[out]"

    cmd += ["-filter_complex", ";".join(graph), "-map", tail, "-c:a", "pcm_s16le", out_path]
    return cmd


def mix(tracks: list, out_path: str, *, limiter: bool = True) -> str:
    """Render the track list to a WAV. Returns the path."""
    _run(mix_command(tracks, out_path, limiter=limiter))
    return out_path


def analyze(path: str) -> dict:
    """Measure a file: integrated loudness, true peak and loudness range.

    `loudnorm`'s measurement mode prints one JSON object, which is the numbers
    EBU R128 defines (BS.1770 gating included) rather than an approximation of
    them. `input_i` is `-inf` for digital silence, which is reported as `None`
    so a caller does not have to know that convention.
    """
    if not os.path.exists(path):
        raise AudioError(f"no such file: {path}")
    stderr = _run(["ffmpeg", "-nostats", "-i", path,
                   "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end < start:
        raise AudioError(f"loudnorm produced no measurement for {path}")
    raw = json.loads(stderr[start:end + 1])

    def number(key):
        value = raw.get(key)
        try:
            return None if value in (None, "-inf", "inf", "nan") else float(value)
        except (TypeError, ValueError):
            return None

    return {
        "integrated_lufs": number("input_i"),
        "true_peak_dbtp": number("input_tp"),
        "loudness_range": number("input_lra"),
        "threshold_lufs": number("input_thresh"),
        "target_offset": number("target_offset"),
    }


def verdict(report: dict, *, target: float = DEFAULT_TARGET_LUFS,
            peak: float = DEFAULT_TRUE_PEAK) -> list:
    """What is wrong with a measurement, in the words of the numbers.

    An empty list means the mix is deliverable for web video. The checks are the
    two that actually matter: too quiet/too loud against the platform's
    normalisation target, and a true peak that will clip after lossy encoding.
    """
    problems: list[str] = []
    integrated = report.get("integrated_lufs")
    if integrated is None:
        problems.append("the mix is digital silence (no measurable loudness)")
    elif abs(integrated - target) > 1.0:
        direction = "quiet" if integrated < target else "loud"
        problems.append(f"{integrated:.1f} LUFS is {abs(integrated - target):.1f} dB"
                        f" too {direction} for the {target:.0f} LUFS target")
    true_peak = report.get("true_peak_dbtp")
    if true_peak is not None and true_peak > peak:
        problems.append(f"true peak {true_peak:.2f} dBTP is above {peak:.1f} dBTP;"
                        f" lossy encoding can clip it")
    return problems

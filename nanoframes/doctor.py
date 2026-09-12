"""Can this checkout render at all, and what fixes each thing that cannot?

`check` answers "is this composition well-formed"; `debug` answers "where did my
drawing go". Both assume the machine can render, and when it cannot they fail
with whatever the missing piece raises — an `ImportError` from three frames
down, an ffmpeg error only in the video path, a text element that draws nothing
because no CJK face was found. This module answers the question before the
others, and every failing check names the command that fixes it, so the reader
does not have to know which of five things is wrong to act on it.

Two exit conventions, on purpose. `--json` **always exits 0** and puts the
verdict in `ok`: a non-zero exit makes a shell pipeline throw away the payload
the agent asked for. Human mode exits 1 when a check failed, because that is
what a person reading a terminal expects.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from nanoframes import identity
from nanoframes.cache import DEFAULT_MAX_BYTES
from nanoframes.fonts import DEFAULT_FONT_CANDIDATES
from nanoframes.media import has_tool

# The version whose behaviour this package is written against. ThorVG 1.0.4 via
# thorvg-python 1.1.3 is where the probed behaviours (clip-path honoured,
# preserveAspectRatio and visibility ignored) were measured; 1.1.1 crashes on
# `ctypes.Array` subscripting under Python 3.9.
MIN_THORVG_PYTHON = (1, 1, 3)

# Below this, a full render is likely to run out mid-way. The cache is a draft
# accelerator and always reproducible, so reclaiming it is the safe first move.
TIGHT_DISK_BYTES = 1 << 30


@dataclass
class Check:
    """One precondition, and how to satisfy it."""

    name: str
    ok: bool
    detail: str
    fix: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "fix": self.fix}


@dataclass
class Report:
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_dict(self) -> dict:
        return {"ok": self.ok,
                "failed": [c.name for c in self.failed],
                "checks": [c.to_dict() for c in self.checks]}


def check_thorvg() -> Check:
    """The rasterizer itself. Nothing renders without it."""
    try:
        import thorvg_python  # noqa: F401
    except Exception as exc:
        return Check("thorvg", False,
                     f"thorvg-python is not importable: {exc}",
                     "pip install -U 'thorvg-python>=1.1.3'")
    raw = identity.dist_version("thorvg-python")
    if raw == "uninstalled":
        # A vendored or source install: importable is the only signal there is,
        # and it is a real one. Saying "unknown version" would be a worse answer
        # than saying which question could not be answered.
        return Check("thorvg", True,
                     "thorvg-python is importable but has no distribution metadata"
                     " (source or vendored install); the version is unverified")
    try:
        got = tuple(int(part) for part in raw.split(".")[:3])
    except ValueError:
        return Check("thorvg", True, f"thorvg-python {raw} (version not parseable)")
    if got < MIN_THORVG_PYTHON:
        want = ".".join(str(n) for n in MIN_THORVG_PYTHON)
        return Check("thorvg", False,
                     f"thorvg-python {raw} is older than {want}, which is what the"
                     f" probed behaviours were measured against",
                     "pip install -U 'thorvg-python>=1.1.3'")
    return Check("thorvg", True, f"thorvg-python {raw}")


def check_ffmpeg() -> Check:
    """Needed for every video path: muxing, and extracting video-backed images."""
    if not has_tool("ffmpeg"):
        return Check("ffmpeg", False,
                     "ffmpeg is not on PATH: `video` and video-backed `<image>`"
                     " cannot run (still/PNG rendering does not need it)",
                     _install_ffmpeg_hint())
    return Check("ffmpeg", True, f"ffmpeg at {shutil.which('ffmpeg')}")


def check_ffprobe() -> Check:
    """Separate from ffmpeg on purpose: it reads a video's dimensions *before*
    an ingest is paid for, and the two are not always installed together."""
    if not has_tool("ffprobe"):
        return Check("ffprobe", False,
                     "ffprobe is not on PATH: a video-backed `<image>` cannot have"
                     " its frame count and duration read",
                     _install_ffmpeg_hint())
    return Check("ffprobe", True, f"ffprobe at {shutil.which('ffprobe')}")


def _install_ffmpeg_hint() -> str:
    if shutil.which("brew"):
        return "brew install ffmpeg"
    if shutil.which("apt-get"):
        return "sudo apt-get install ffmpeg"
    return "install ffmpeg and put it on PATH (https://ffmpeg.org/download.html)"


def check_fonts() -> Check:
    """At least one face has to be loadable, or `<text>` draws nothing.

    A blank text element is the quietest failure in the package: a valid frame,
    no error, no exception. The bundled face is the one this can act on — a
    system face being absent is a fact about the machine, not a fault.
    """
    present = [p for p in DEFAULT_FONT_CANDIDATES if os.path.exists(p)]
    if not present:
        return Check("fonts", False,
                     f"none of the {len(DEFAULT_FONT_CANDIDATES)} default font"
                     f" candidates exist, so `<text>` cannot rasterize at all",
                     "pip install --force-reinstall nanoframes")
    bundled = [p for p in present if os.path.dirname(p) == _bundled_font_dir()]
    if not bundled:
        return Check("fonts", True,
                     f"{len(present)} system face(s) found but the bundled CJK face"
                     f" is missing; Chinese text renders from a fallback face at"
                     f" best (run `nanoframes fonts list` to see what resolves)",
                     "pip install --force-reinstall nanoframes")
    return Check("fonts", True, f"bundled CJK face present, {len(present)} face(s) loadable")


def _bundled_font_dir() -> str:
    from nanoframes import fonts

    return os.path.join(os.path.dirname(os.path.abspath(fonts.__file__)), "fonts")


def check_disk(cache_dir: str) -> Check:
    """Room for frames. The cache is reproducible, so reclaiming it is free."""
    target = os.path.abspath(os.path.expanduser(cache_dir))
    probe = target
    while not os.path.isdir(probe):  # the cache may not exist yet
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        return Check("disk", False, f"cannot read free space at {probe}: {exc}", None)
    free = usage.free
    detail = f"{free / 1e9:.1f} GB free at {probe}"
    if free < TIGHT_DISK_BYTES:
        return Check("disk", False, detail + " — too little for a full render",
                     "nanoframes cache --clear")
    return Check("disk", True, detail + f" (cache cap {DEFAULT_MAX_BYTES / 1e6:.0f} MB)")


def report(cache_dir: str = ".nanoframes-cache") -> Report:
    """Every precondition, in the order a missing one would bite."""
    return Report(checks=[
        check_thorvg(),
        check_ffmpeg(),
        check_ffprobe(),
        check_fonts(),
        check_disk(cache_dir),
    ])

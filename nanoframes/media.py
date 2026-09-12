"""Embedded media: aspect-correct placement for ``<image>`` nodes.

ThorVG ignores ``preserveAspectRatio`` and always stretches a picture to its
declared ``width``/``height`` (probed — see docs/diagram.md's gap list for the
same class of finding), so a non-square source in a square box comes out
distorted. ``data-fit`` asks for the geometry a browser would have computed, and
this module computes it: ``contain`` letterboxes inside the box, ``cover`` fills
it and clips the overflow.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache

from nanoframes import refs
from nanoframes.xmlutil import find_parent, qname

# Accepted ``data-fit`` values. ``stretch`` is ThorVG's own behaviour, so it is
# the default and a no-op.
FIT_MODES = ("stretch", "contain", "cover")

_CLIP_PREFIX = "nf-fit-"


def _file_stat(path: str):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=256)
def _intrinsic_cached(path: str, _stat):
    """Read a picture's pixel size. ``_stat`` is part of the key, not an input."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 - an unreadable source just means "no fit"
        return None


def intrinsic_size(path: str):
    """``(width, height)`` of an image file, or ``None`` when unreadable.

    Keyed on the file's size and mtime as well as its path, so an edited source
    is re-read instead of serving a stale dimension for the process's lifetime.
    """
    stat = _file_stat(path)
    if stat is None:
        return None
    return _intrinsic_cached(path, stat)


def resolve_source(node, base_dir: str | None) -> str | None:
    """The local file an ``<image>`` points at, or ``None`` for remote ones."""
    ref = refs.image_ref(node)
    if not refs.is_local(ref):
        return None
    if os.path.isabs(ref):
        return os.path.normpath(ref)
    if base_dir:
        return os.path.normpath(os.path.join(base_dir, ref))
    return None


def _declared_box(node) -> tuple | None:
    """The element's authored box ``(x, y, w, h)``, or ``None`` without one.

    ``data-fit`` needs a box to fit into: an ``<image>`` with no declared
    ``width``/``height`` is drawn at its intrinsic size and has nothing to fit.
    """
    try:
        width = float(node.get("width"))
        height = float(node.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    try:
        x = float(node.get("x")) if node.get("x") is not None else 0.0
        y = float(node.get("y")) if node.get("y") is not None else 0.0
    except (TypeError, ValueError):
        x = y = 0.0
    return x, y, width, height


def _defs(root) -> ET.Element:
    """The root's ``<defs>``, created (and placed first) when absent."""
    for child in root:
        if child.tag == qname("defs"):
            return child
    defs = ET.Element(qname("defs"))
    root.insert(0, defs)
    return defs


def _clip_to_box(root, node, clip_id: str, box) -> None:
    """Wrap ``node`` in a group clipped to ``box`` (ThorVG honors ``clip-path``)."""
    parent = find_parent(root, node)
    if parent is None:
        return
    clip = ET.Element(qname("clipPath"), {"id": clip_id})
    x, y, width, height = box
    ET.SubElement(clip, qname("rect"), {
        "x": f"{x:g}", "y": f"{y:g}", "width": f"{width:g}", "height": f"{height:g}",
    })
    _defs(root).append(clip)

    group = ET.Element(qname("g"), {"clip-path": f"url(#{clip_id})"})
    index = list(parent).index(node)
    parent.remove(node)
    group.append(node)
    parent.insert(index, group)


def apply_fit(root, base_dir: str | None) -> None:
    """Rewrite every ``<image data-fit>`` to an aspect-correct box, in place.

    ``contain`` shrinks the picture to fit inside the authored box (letterbox);
    ``cover`` grows it to fill the box and clips the overflow to the box.
    ``stretch`` (and an absent attribute) leaves the geometry exactly as
    authored, so a composition that does not opt in renders unchanged.
    """
    ordinal = 0
    for node in list(refs.iter_images(root)):
        mode = (node.get("data-fit") or "").strip().lower()
        if mode not in FIT_MODES or mode == "stretch":
            continue
        box = _declared_box(node)
        source = resolve_source(node, base_dir)
        if box is None or source is None:
            continue
        size = intrinsic_size(source)
        if size is None:
            continue
        intrinsic_w, intrinsic_h = size
        if intrinsic_w <= 0 or intrinsic_h <= 0:
            continue

        x, y, width, height = box
        fit = min if mode == "contain" else max
        scale = fit(width / intrinsic_w, height / intrinsic_h)
        drawn_w, drawn_h = intrinsic_w * scale, intrinsic_h * scale
        node.set("x", f"{x + (width - drawn_w) / 2.0:g}")
        node.set("y", f"{y + (height - drawn_h) / 2.0:g}")
        node.set("width", f"{drawn_w:g}")
        node.set("height", f"{drawn_h:g}")

        if mode == "cover":
            ordinal += 1
            clip_id = f"{_CLIP_PREFIX}{node.get('id') or 'img'}-{ordinal}"
            _clip_to_box(root, node, clip_id, box)


# ---------------------------------------------------------------------------
# Video sources: timeline mapping and frame extraction
# ---------------------------------------------------------------------------

# Extensions treated as video. A `<image>` pointing at one of these cannot be
# rasterized by ThorVG (it is an SVG/Lottie engine), so the media pre-pass
# replaces it with an extracted frame before baking.
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpeg", ".mpg")

_FRAME_PREFIX = "f_"
_DONE = ".complete"


class MediaError(RuntimeError):
    """Raised when a video-backed ``<image>`` cannot be prepared for a render."""


def is_video(path: str | None) -> bool:
    """Whether a source path names a video container (by extension)."""
    return bool(path) and os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


def has_tool(name: str) -> bool:
    """Whether an external tool is on PATH."""
    return shutil.which(name) is not None


def probe_duration(path: str) -> float | None:
    """A video's duration in seconds (ffprobe), or ``None`` when unknown."""
    if not has_tool("ffprobe"):
        return None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True)
    except OSError:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def time_mapping(t: float, clip_start: float, anchor: float, speed: float,
                 duration: float | None = None, loop: bool = False) -> float:
    """Composition time -> source-media time.

    ``src_t = anchor + (t - clip_start) * speed``, then wrapped modulo the
    source duration under ``data-loop`` or clamped into ``[0, duration]``
    otherwise (a still frame holds). A pure function of the frame time, like
    ``timeline.seek`` — which is what keeps the frame cache, the draft scale and
    ``debug`` working on video-backed compositions unchanged.
    """
    src_t = anchor + (t - clip_start) * speed
    if duration and duration > 0:
        if loop:
            return src_t % duration
        return min(max(src_t, 0.0), duration)
    return max(0.0, src_t)


@dataclass
class MediaSpec:
    """A video-backed ``<image>``: its source and how it maps onto the timeline."""

    source: str
    clip_start: float
    duration: float
    anchor: float = 0.0
    speed: float = 1.0
    loop: bool = False

    def source_time(self, t: float, video_duration: float | None = None) -> float:
        return time_mapping(t, self.clip_start, self.anchor, self.speed,
                            video_duration, self.loop)


_MEDIA_NUMBER_ATTRS = ("data-anchor", "data-speed", "data-start", "data-duration")


def _number(node, name: str, default: float) -> float:
    raw = node.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def media_attribute_problems(node) -> list[str]:
    """``data-*`` media attributes that are present but not numeric."""
    problems = []
    for name in _MEDIA_NUMBER_ATTRS:
        raw = node.get(name)
        if raw is None or raw == "":
            continue
        try:
            float(raw)
        except (TypeError, ValueError):
            problems.append(f"{name}={raw!r} is not a number")
    return problems


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def parse_media(node, base_dir: str | None, comp_duration: float) -> MediaSpec | None:
    """The media spec for an ``<image>``, or ``None`` when it is not a video."""
    source = resolve_source(node, base_dir)
    if not is_video(source):
        return None
    return MediaSpec(
        source=source,
        clip_start=_number(node, "data-start", 0.0),
        duration=_number(node, "data-duration", comp_duration),
        anchor=_number(node, "data-anchor", 0.0),
        speed=_number(node, "data-speed", 1.0),
        loop=_truthy(node.get("data-loop")),
    )


def video_specs(doc) -> list[MediaSpec]:
    """Every video-backed ``<image>`` in a document."""
    comp_duration = doc.composition.duration
    specs = []
    for node in refs.iter_images(doc.root):
        spec = parse_media(node, doc.base_dir, comp_duration)
        if spec is not None:
            specs.append(spec)
    return specs


def has_video_source(doc) -> bool:
    """Whether a document needs the video pre-pass at all."""
    comp_duration = doc.composition.duration
    return any(parse_media(node, doc.base_dir, comp_duration) is not None
               for node in refs.iter_images(doc.root))


def _dir_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(root, name))
    return total


class MediaCache:
    """Extracted video frames: one directory per (source content, fps, scale).

    Same philosophy as the frame cache — the payload directory is the source of
    truth, and a marker file says a sequence is complete, so a crashed
    extraction is redone rather than half-used. Frames are extracted *at the
    render scale*, which is where the draft speedup comes from: ThorVG resamples
    every picture into its destination rect on every frame, so a small source is
    what makes a draft draft.
    """

    def __init__(self, cache_dir: str = ".nanoframes-cache"):
        self.root = os.path.join(os.path.abspath(cache_dir), "media")

    def key(self, source: str, fps: int, scale: float) -> str:
        raw = f"{refs.file_digest(source)}:{fps:d}:{scale:.4f}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def path_for(self, source: str, fps: int, scale: float) -> str:
        key = self.key(source, fps, scale)
        return os.path.join(self.root, key[:2], key)

    def frames(self, source: str, fps: int, scale: float) -> str | None:
        """The extracted frame directory for this source, or ``None`` if absent."""
        directory = self.path_for(source, fps, scale)
        return directory if os.path.exists(os.path.join(directory, _DONE)) else None

    def extract(self, source: str, fps: int, scale: float) -> str:
        """Extract (or reuse) the frame sequence at ``fps``/``scale``; returns its dir."""
        cached = self.frames(source, fps, scale)
        if cached is not None:
            return cached
        if not has_tool("ffmpeg"):
            raise MediaError(
                "ffmpeg is required to render a video-backed <image> "
                f"({os.path.basename(source)}) and was not found on PATH")
        os.makedirs(self.root, exist_ok=True)
        staging = tempfile.mkdtemp(dir=self.root, prefix=".tmp-")
        try:
            _extract(source, fps, scale, staging)
            with open(os.path.join(staging, _DONE), "w", encoding="utf-8") as fh:
                fh.write(f"{source}\n{fps}\n{scale}\n")
            final = self.path_for(source, fps, scale)
            os.makedirs(os.path.dirname(final), exist_ok=True)
            shutil.rmtree(final, ignore_errors=True)  # an incomplete earlier attempt
            os.replace(staging, final)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return final

    @staticmethod
    def frame_count(directory: str) -> int:
        return sum(1 for name in os.listdir(directory) if name.endswith(".png"))

    def stats(self) -> tuple:
        """``(sequences, bytes)`` of the extracted media."""
        if not os.path.isdir(self.root):
            return 0, 0
        sequences = 0
        total = 0
        for entry in os.scandir(self.root):
            if entry.is_dir() and not entry.name.startswith(".tmp-"):
                sequences += 1
                total += _dir_bytes(entry.path)
        return sequences, total


def _extract(source: str, fps: int, scale: float, out_dir: str) -> None:
    """Run ffmpeg once, resampling the source to ``fps`` and (optionally) ``scale``."""
    filters = [f"fps={fps}"]
    if scale and abs(scale - 1.0) > 1e-9:
        filters.append(f"scale=iw*{scale:.6f}:ih*{scale:.6f}")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", source,
           "-vf", ",".join(filters), "-start_number", "0",
           os.path.join(out_dir, f"{_FRAME_PREFIX}%05d.png")]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise MediaError(f"could not run ffmpeg: {exc}") from exc
    if proc.returncode != 0:
        raise MediaError(
            f"ffmpeg could not extract frames from {source}: {proc.stderr.strip()[:300]}")


class MediaResolver:
    """Prepares video sources for a render and rewrites them per frame.

    ``prepare`` extracts every distinct video once, before the frame loop.
    ``apply`` rewrites each video image's href to the frame its composition time
    maps to. ``apply`` runs on the *baked copy*, never on the authored tree, so
    the document's identity — and with it the frame cache key — always describes
    the source rather than a generated frame.
    """

    def __init__(self, cache: MediaCache, fps: int, scale: float = 1.0):
        self.cache = cache
        self.fps = max(1, int(fps))
        self.scale = scale
        self._frames: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._durations: dict[str, float | None] = {}

    def prepare(self, doc) -> list[str]:
        """Extract frame sequences for the document's videos; returns warnings."""
        warnings: list[str] = []
        for spec in video_specs(doc):
            if spec.source in self._frames:
                continue
            try:
                directory = self.cache.extract(spec.source, self.fps, self.scale)
            except MediaError as exc:
                warnings.append(str(exc))
                continue
            frames = self.cache.frame_count(directory)
            if frames <= 0:
                warnings.append(f"no frames extracted from {spec.source}")
                continue
            self._frames[spec.source] = directory
            self._counts[spec.source] = frames
            self._durations[spec.source] = probe_duration(spec.source)
        return warnings

    def prepared(self, source: str) -> bool:
        """Whether a source was successfully extracted and can be drawn."""
        return source in self._frames

    def frame_index(self, spec: MediaSpec, t: float) -> int:
        """The extracted-frame index a composition time maps to (clamped)."""
        count = self._counts.get(spec.source, 0)
        if count <= 0:
            return 0
        src_t = spec.source_time(t, self._durations.get(spec.source))
        return min(max(int(round(src_t * self.fps)), 0), count - 1)

    def apply(self, root, t: float, comp_duration: float, base_dir: str | None) -> None:
        """Point every video ``<image>`` at the frame for time ``t``."""
        for node in refs.iter_images(root):
            spec = parse_media(node, base_dir, comp_duration)
            if spec is None or not self.prepared(spec.source):
                continue
            directory = self._frames[spec.source]
            frame = os.path.join(directory, f"{_FRAME_PREFIX}{self.frame_index(spec, t):05d}.png")
            if not os.path.exists(frame):
                continue
            attr = next((a for a in refs.IMAGE_REF_ATTRS if node.get(a) is not None), "href")
            node.set(attr, frame)

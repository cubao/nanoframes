"""Answer "where did my drawing go?" for a composition.

``nanoframes check`` proves a composition is well-formed. This module answers
the next question, the one a frame full of nothing poses: *which* element was
supposed to draw, *where* its geometry landed, and *when* it was even visible.

Most of it is arithmetic over the baked tree (``bounds``) plus one raster pass
for the pixel-level questions (how much of the frame is covered, how far apart a
loop's two seam frames are). ``--pixels`` adds one raster pass *per element*, to
answer the question arithmetic cannot: whether anything of it survived to the
picture once everything else had drawn. That is the only reading that catches an
element painted over by a later sibling, which passes every box-based check.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from nanoframes import bake, bounds, timeline
from nanoframes.parse import Document

# Cap on the frames a clip scan inspects (see timeline.sample_times).
SCAN_SAMPLES = 24


@dataclass
class ElementBox:
    """One element's placed geometry in one frame."""

    path: tuple
    depth: int
    label: str
    box: bounds.Box | None
    status: str  # on-canvas | clipped | off-canvas | unmeasured
    painted: bool  # this frame actually draws from it (clip window + opacity)
    complete: bool = True
    named: bool = False  # has an id, or sits at the top level
    has_id: bool = False  # author gave it an id — what `covered` reports on
    contributes: bool | None = None  # None unless pixels were probed

    @property
    def blank(self) -> bool:
        """Painted, fully measured, and yet nowhere near the canvas."""
        return self.painted and self.complete and self.status == "off-canvas"

    @property
    def covered(self) -> bool:
        """On the canvas by its box, and contributing nothing to the picture.

        The failure no arithmetic can find: something drawn later covered it.
        Only meaningful once ``contributes`` has been probed, and reported only
        for elements the author **named** — a background rectangle is buried by
        anything full-bleed drawn after it, and saying so every time would train
        the reader to ignore the line. Naming an element is how it opts into
        being checked.
        """
        return (self.has_id and self.contributes is False
                and self.status in ("on-canvas", "clipped"))

    def status_line(self) -> str:
        if not self.painted:
            return "(hidden here: outside its clip window, or opacity 0)"
        if self.box is None:
            return "no geometry measured (nothing to place)"
        note = "" if self.complete else "  (partly unmeasured)"
        if self.status == "off-canvas":
            note += "  <-- draws nothing here"
        if self.covered:
            note += "  <-- on the canvas, but buried: nothing of it reaches the picture"
        elif self.contributes:
            note += "  (reaches the picture)"
        return f"{format_box(self.box):<30}{self.status}{note}"

    def to_dict(self) -> dict:
        """One element's placement, machine-readable (``debug --json``)."""
        return {
            "path": list(self.path),
            "depth": self.depth,
            "label": self.label,
            "box": _box_list(self.box),
            "status": self.status,
            "painted": self.painted,
            "complete": self.complete,
            "named": self.named,
            "has_id": self.has_id,
            "blank": self.blank,
            "covered": self.covered,
            "contributes": self.contributes,
        }


def format_box(box: bounds.Box) -> str:
    return f"[{box.x0:.0f},{box.y0:.0f} .. {box.x1:.0f},{box.y1:.0f}]"


def _box_list(box: bounds.Box | None) -> list[float] | None:
    """A box as ``[x0, y0, x1, y1]`` for the JSON report (``None`` when unmeasured)."""
    if box is None:
        return None
    return [round(box.x0, 2), round(box.y0, 2), round(box.x1, 2), round(box.y1, 2)]


@dataclass
class FrameReport:
    t: float
    width: int
    height: int
    frame_index: int
    elements: list[ElementBox] = field(default_factory=list)
    coverage: float | None = None  # fraction of canvas pixels with any color

    @property
    def blanks(self) -> list[ElementBox]:
        return [e for e in self.elements if e.blank]

    @property
    def covered(self) -> list[ElementBox]:
        """Elements whose geometry is on the canvas and whose pixels are not.

        Empty unless ``pixels`` was probed.
        """
        return [e for e in self.elements if e.covered]

    def to_dict(self) -> dict:
        return {
            "t": self.t,
            "width": self.width,
            "height": self.height,
            "frame_index": self.frame_index,
            "coverage": self.coverage,
            "elements": [e.to_dict() for e in self.elements],
            "blanks": [e.label for e in self.blanks],
            "covered": [e.label for e in self.covered],
        }


@dataclass
class ElementFrames:
    """One element across a clip scan."""

    path: tuple
    label: str
    painted_frames: int = 0
    on_canvas_frames: int = 0
    first_off_at: float | None = None
    complete: bool = True
    named: bool = False  # has an id, or sits at the top level

    @property
    def never_visible(self) -> bool:
        return self.complete and self.painted_frames > 0 and self.on_canvas_frames == 0

    @property
    def interesting(self) -> bool:
        """Worth a line in the report: authored element, or a geometry problem."""
        return self.named or self.never_visible or self.first_off_at is not None

    def to_dict(self) -> dict:
        out = {
            "path": list(self.path),
            "label": self.label,
            "painted_frames": self.painted_frames,
            "on_canvas_frames": self.on_canvas_frames,
            "complete": self.complete,
            "named": self.named,
            "never_visible": self.never_visible,
        }
        if self.first_off_at is not None:
            out["first_off_at"] = self.first_off_at
        return out


@dataclass
class ClipScan:
    times: list[float]
    frame_count: int
    elements: list[ElementFrames] = field(default_factory=list)

    @property
    def sampled(self) -> int:
        return len(self.times)

    @property
    def never_visible(self) -> list[ElementFrames]:
        return [e for e in self.elements if e.never_visible]

    def reported(self) -> list[ElementFrames]:
        """Elements that earn a line: authored ones, plus anything misbehaving."""
        return [e for e in self.elements if e.interesting]

    def to_dict(self) -> dict:
        return {
            "sampled": self.sampled,
            "frame_count": self.frame_count,
            "times": self.times,
            "elements": [e.to_dict() for e in self.reported()],
            "never_visible": [e.label for e in self.never_visible],
        }


@dataclass
class SeamReport:
    """How far the clip's first and last frames are apart (a loop's seam)."""

    first_t: float
    last_t: float
    differing_fraction: float
    max_channel_delta: int

    @property
    def closed(self) -> bool:
        return self.differing_fraction == 0.0

    def to_dict(self) -> dict:
        return {
            "first_t": self.first_t,
            "last_t": self.last_t,
            "differing_fraction": self.differing_fraction,
            "max_channel_delta": self.max_channel_delta,
            "closed": self.closed,
        }


def frame_report(doc: Document, t: float, measurer=None, coverage: bool = True,
                 pixels: bool = False, threads: int = 1) -> FrameReport:
    """Per-element boxes for the frame at ``t``, plus its canvas coverage.

    ``pixels`` adds the contribution probe: one extra raster per reported
    element, answering whether hiding it would change the frame at all. Off by
    default because a report without it costs one frame.
    """
    comp = doc.composition
    canvas = bounds.canvas_box(comp.width, comp.height)
    root = bake.bake_tree(doc, t, measurer=measurer)
    report = FrameReport(t=t, width=comp.width, height=comp.height,
                         frame_index=round(t * comp.fps))
    probed: list[tuple[ElementBox, object]] = []
    for path, node, ancestors in bounds.iter_renderable(root):
        painted, box, complete = bounds.placed(node, ancestors, measurer)
        record = ElementBox(
            path=path,
            depth=len(path) - 1,
            label=bounds.label(node),  # the baked node: auto-layout may have added nodes
            box=box,
            status=bounds.classify(box, canvas) if box is not None and complete
            else "unmeasured",
            painted=painted,
            complete=complete,
            named=bool(node.get("id")) or len(path) == 1,
            has_id=bool(node.get("id")),
        )
        if record.named or record.blank:
            report.elements.append(record)
            probed.append((record, node))
    if coverage:
        report.coverage = _coverage(doc, t)
    if pixels:
        _probe_contribution(root, comp.width, comp.height, probed, threads)
    return report


def _probe_contribution(root, width: int, height: int, probed, threads: int) -> None:
    """Fill in ``contributes``: does hiding this node change the frame?

    Arithmetic says where a box landed; it cannot say whether any of it survived
    to the picture. An element can sit on the canvas by every box measure and
    contribute nothing, because a later sibling painted over it — and that
    passes every box-based reading there is.

    Each variant is **the same frame with one node hidden**, never the node
    drawn on its own. Isolating a node changes what it is composited against,
    which is enough to measure a plainly visible element as invisible: a pixel
    test can only see a node against some backdrop, and the isolated backdrop is
    not the one the composition has.

    ``display="none"`` is the hide that works — probed, not assumed.
    ``visibility="hidden"`` is silently ignored by this ThorVG build, and
    ``opacity="0"`` works but leaves the node in the tree to be composited.
    """
    from nanoframes.render import render_svg

    def draw() -> object:
        return render_svg(ET.tostring(root, encoding="unicode"), width, height,
                          threads=threads)

    baseline = draw()
    for record, node in probed:
        # Only "not painted" is a reason to skip: a node its clip window or a
        # zero opacity kept out of the frame cannot contribute, and needs no
        # render to say so. An unmeasured box is NOT a reason — the pixel answer
        # does not depend on the box, only the claim about where it landed does.
        if not record.painted:
            continue
        previous = node.get("display")
        node.set("display", "none")
        try:
            differing, _ = frame_distance(baseline, draw())
        finally:
            if previous is None:
                node.attrib.pop("display", None)
            else:
                node.set("display", previous)
        record.contributes = differing > 0.0


def frame_distance(a, b) -> tuple[float, int]:
    """Fraction of pixels that differ between two frames, and the largest channel delta."""
    from PIL import ImageChops

    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    max_delta = max(channel[1] for channel in diff.getextrema())
    histogram = diff.convert("L").histogram()
    total = diff.width * diff.height
    return (sum(histogram[1:]) / total if total else 0.0), max_delta


def _coverage(doc: Document, t: float) -> float:
    """Fraction of the rendered frame that has any alpha (1.0 = nothing transparent)."""
    from nanoframes.render import render_frame

    img = render_frame(doc, t, cache=None).convert("RGBA")
    alpha = img.getchannel("A")
    total = alpha.width * alpha.height
    if not total:
        return 0.0
    histogram = alpha.histogram()
    return (total - histogram[0]) / total


def scan_clip(doc: Document, measurer=None, samples: int = SCAN_SAMPLES) -> ClipScan:
    """Track every element across sampled frames of the whole clip."""
    comp = doc.composition
    canvas = bounds.canvas_box(comp.width, comp.height)
    scan = ClipScan(times=timeline.sample_times(comp, cap=samples), frame_count=comp.frame_count)
    tracked: dict[tuple, ElementFrames] = {}
    for t in scan.times:
        root = bake.bake_tree(doc, t, measurer=measurer)
        for path, node, ancestors in bounds.iter_renderable(root):
            painted, box, complete = bounds.placed(node, ancestors, measurer)
            entry = tracked.get(path)
            if entry is None:
                entry = ElementFrames(path=path, label=bounds.label(node),
                                      named=bool(node.get("id")) or len(path) == 1)
                tracked[path] = entry
            entry.complete = entry.complete and complete
            if not painted:
                continue
            entry.painted_frames += 1
            if box is None:
                continue
            if box.intersects(canvas):
                entry.on_canvas_frames += 1
            elif entry.first_off_at is None:
                entry.first_off_at = t
    scan.elements = [tracked[path] for path in sorted(tracked)]
    return scan


def loop_seam(doc: Document, scale: float = 1.0) -> SeamReport:
    """Compare the clip's first and last rendered frames.

    A seamless loop plays last frame -> frame 0, so those two frames are the
    seam. Rendering ends at ``duration - 1/fps`` (see ``timeline.last_frame_time``),
    which is easy to miss when authoring: closing the motion at ``duration``
    instead leaves a visible jump here.
    """
    from nanoframes.render import render_frame

    comp = doc.composition
    first_t = 0.0
    last_t = timeline.last_frame_time(comp)
    differing, max_delta = frame_distance(
        render_frame(doc, first_t, cache=None, scale=scale),
        render_frame(doc, last_t, cache=None, scale=scale),
    )
    return SeamReport(first_t=first_t, last_t=last_t,
                      differing_fraction=differing, max_channel_delta=max_delta)

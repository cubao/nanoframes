"""Answer "where did my drawing go?" for a composition.

``nanoframes check`` proves a composition is well-formed. This module answers
the next question, the one a frame full of nothing poses: *which* element was
supposed to draw, *where* its geometry landed, and *when* it was even visible.

Most of it is arithmetic over the baked tree (``bounds``) plus one raster pass
for the pixel-level questions (how much of the frame is covered, how far apart a
loop's two seam frames are). ``--pixels`` adds one raster pass *per element*, to
answer the question arithmetic cannot: whether anything of it survived to the
picture once everything else had drawn. That is the only reading that catches an
element painted over by a later sibling, which passes every box-based check — and
it reports the *fact* rather than a cause it cannot see: a pixel test cannot tell
an occlusion from a fade, so only a cause the arithmetic can measure is named.
"""

from __future__ import annotations

import contextlib
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
    painted: bool  # this frame draws from it (inside its clip window, measurable)
    complete: bool = True
    named: bool = False  # has an id, or sits at the top level
    has_id: bool = False  # author gave it an id — what `invisible` reports on
    contributes: bool | None = None  # None unless pixels were probed
    why: str = ""  # the cause, only where the arithmetic supports one

    @property
    def blank(self) -> bool:
        """Painted, fully measured, and yet nowhere near the canvas."""
        return self.painted and self.complete and self.status == "off-canvas"

    @property
    def hidden_but_drawn(self) -> bool:
        """Bake hid it and the rasterizer drew it anyway.

        A renderer that ignores the hiding attribute makes the whole arithmetic
        model wrong for that node: the clip window, the fade, and everything
        `lint` concluded from them. Only the pixels can see it.
        """
        return self.has_id and not self.painted and self.contributes is True

    @property
    def invisible(self) -> bool:
        """On the canvas by its box, and contributing no pixel to the picture.

        The failure no box can find: on the canvas by every measure, and nothing
        of it in the frame. Only meaningful once ``contributes`` has been probed,
        and reported only for elements the author **named** — a background
        rectangle is covered by anything full-bleed drawn after it, and a line
        that fires on that every time is a line the reader learns to ignore.
        Naming an element is how it opts into being checked.

        What this does NOT claim is *why*. A pixel test can see that nothing
        survived; it cannot tell a later sibling painting over the node from a
        fade that has it at zero, because both leave the same evidence. ``why``
        carries the one cause the arithmetic can support, and stays empty when
        there is none.
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
        if self.invisible:
            note += f"  <-- on the canvas, contributing no pixel ({self.why})" \
                if self.why else "  <-- on the canvas, contributing no pixel"
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
            "invisible": self.invisible,
            "hidden_but_drawn": self.hidden_but_drawn,
            "why": self.why,
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
    def invisible(self) -> list[ElementBox]:
        """Elements whose geometry is on the canvas and whose pixels are not.

        Empty unless ``pixels`` was probed.
        """
        return [e for e in self.elements if e.invisible]

    @property
    def hidden_but_drawn(self) -> list[ElementBox]:
        """Elements bake hid that the rasterizer drew anyway (see ElementBox)."""
        return [e for e in self.elements if e.hidden_but_drawn]

    def to_dict(self) -> dict:
        return {
            "t": self.t,
            "width": self.width,
            "height": self.height,
            "frame_index": self.frame_index,
            "coverage": self.coverage,
            "elements": [e.to_dict() for e in self.elements],
            "blanks": [e.label for e in self.blanks],
            "invisible": [e.label for e in self.invisible],
            "hidden_but_drawn": [e.label for e in self.hidden_but_drawn],
            "why": {e.label: e.why for e in self.invisible if e.why},
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
    for path, node, ancestors, line in bounds.iter_renderable(root):
        painted, box, complete = bounds.placed(node, ancestors, measurer, line)
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

    The node is **removed from the tree** rather than hidden with an attribute.
    Probed, ThorVG honours ``display="none"`` and ``opacity="0"`` on shapes and
    groups and **ignores both on text-bearing nodes**: hiding by attribute
    reported every visible text element as contributing nothing — a false
    positive on the element type this check most exists for (a buried caption is
    a caption), arriving with no symptom. bake works around the same gap by
    wrapping a `<text>` or `<image>` in a `<g>`, but a `<tspan>` cannot be
    wrapped, so the attribute is still not a reliable way to hide a node here.
    Detaching is unambiguous and works for every type; the tree is restored by
    re-inserting at the same index, before anything else can observe it.
    """
    from nanoframes.render import render_svg

    def draw() -> object:
        return render_svg(ET.tostring(root, encoding="unicode"), width, height,
                          threads=threads)

    baseline = draw()
    for record, node in probed:
        # Every node is probed, including the ones bake marked hidden. That is
        # not wasted work: it is how a node the renderer draws *anyway* is found.
        # `display="none"` is how bake materializes a clip window, and a
        # renderer that ignores it draws the element regardless — the `<tspan>`
        # case is live today, and it is invisible to every arithmetic reading and
        # to any check that trusts the attribute.
        parent, index = _detach(root, record.path)
        try:
            differing, _ = frame_distance(baseline, draw())
        finally:
            parent.insert(index, node)
        record.contributes = differing > 0.0
        if not record.contributes:
            record.why = _invisibility_reason(root, record.path)


def assemble(report: "FrameReport", scan: "ClipScan | None" = None,
             seam: "SeamReport | None" = None, doc: Document | None = None,
             pops: "PopScan | None" = None) -> dict:
    """The ``debug --json`` object, from reports that have already been computed.

    A pure assembler: the text path needs the objects themselves, so this takes
    them rather than recomputing, and `verify` gets the same object by the same
    code.
    """
    # `ok` is True whenever the reading was produced, because this section is a
    # reading and not a gate: an element off the canvas is reported, and a
    # report is not a failure. `verify` counts the findings as warnings; only
    # `--strict` turns them into an exit code.
    payload: dict = {"ok": True, "frame": report.to_dict()}
    if doc is not None:
        payload["identity"] = {"digest": doc.identity,
                               "components": doc.identity_components()}
    if scan is not None:
        payload["scan"] = scan.to_dict()
    if seam is not None:
        payload["loop_seam"] = seam.to_dict()
    if pops is not None:
        payload["pops"] = pops.to_dict()
    return payload


def debug_payload(doc: Document, t: float, *, measurer=None, samples: int = SCAN_SAMPLES,
                  pixels: bool = False, threads: int = 4, scan: bool = True,
                  loop: bool = False) -> dict:
    """The ``debug --json`` object — and the ``debug`` section of ``verify``."""
    report = frame_report(doc, t, measurer=measurer, pixels=pixels, threads=threads)
    scanned = scan_clip(doc, measurer=measurer, samples=max(2, samples)) if scan else None
    seam = loop_seam(doc) if loop else None
    return assemble(report, scan=scanned, seam=seam, doc=doc)


def _detach(root, path):
    """Take one node out of the baked tree; return what re-inserting it needs.

    ``path`` is the child-index chain from ``root`` (what `bounds.iter_renderable`
    yields), which also gives the parent and the index to restore at.
    """
    parent = root
    for index in path[:-1]:
        parent = list(parent)[index]
    parent.remove(list(parent)[path[-1]])
    return parent, path[-1]


# Below this, an element draws nothing anyone can see, and the probe's answer is
# explained by the fade rather than by anything drawn later.
_TRANSPARENT_EPSILON = 1e-3

_INVISIBLE_REASONS = ("a later sibling drawing over it",
                      "an ancestor's clip or mask excluding its pixels")


def effective_opacity(root, path) -> float:
    """The product of ``opacity`` down a baked path: what this node draws at.

    `bounds.placed` answers *where* a node would draw and not how strongly: a
    node at opacity 0 still measures, so the probe has to ask this separately to
    avoid blaming a sibling for a fade.
    """
    value = 1.0
    node = root
    for index in path:
        children = list(node)
        if index >= len(children):
            return value
        node = children[index]
        raw = node.get("opacity")
        if raw is None:
            continue
        with contextlib.suppress(ValueError):
            value *= float(raw)
    return value


def _invisibility_reason(root, path) -> str:
    """The cause the arithmetic can support — and nothing more.

    A pixel test sees that no pixel survived. It cannot see *why*: a node painted
    over by a later sibling and a node faded to zero leave identical evidence.
    Opacity is the one cause that is separately measurable, so it is the one that
    gets named; otherwise the report lists the candidates rather than picking one.
    """
    if effective_opacity(root, path) <= _TRANSPARENT_EPSILON:
        return "fully transparent at this time (a fade or an opacity of 0)"
    return "no pixel of it survives — " + ", or ".join(_INVISIBLE_REASONS)


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
        for path, node, ancestors, line in bounds.iter_renderable(root):
            painted, box, complete = bounds.placed(node, ancestors, measurer, line)
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


# ---------------------------------------------------------------------------
# Pops: a change between two *still* frames
# ---------------------------------------------------------------------------


@dataclass
class Pop:
    """A region that changed in one frame between two frames that held."""

    frame: int
    t: float
    box: tuple
    changed: float            # fraction of the frame that moved
    how: str                  # "appeared", "vanished" or "jumped"
    declared: bool = False    # a clip boundary lands on this frame
    declared_at: float | None = None


@dataclass
class PopScan:
    frames: int
    threshold: float
    pops: list = field(default_factory=list)

    @property
    def undeclared(self) -> list:
        """The ones nothing in the composition explains."""
        return [p for p in self.pops if not p.declared]

    @property
    def quiet(self) -> bool:
        return not self.pops

    def to_dict(self) -> dict:
        return {
            "frames": self.frames,
            "threshold": self.threshold,
            "pops": [
                {"frame": p.frame, "t": p.t, "box": list(p.box),
                 "changed": p.changed, "how": p.how,
                 "declared": p.declared, "declared_at": p.declared_at}
                for p in self.pops
            ],
        }


def _declared_boundaries(doc: Document) -> list:
    """Every clip start and end the composition declares, in seconds."""
    out = []
    for el in doc.composition.elements:
        out.append(el.clip_start)
        out.append(el.clip_start + (el.clip_duration or doc.composition.duration))
    return out


def scan_pops(doc: Document, *, scale: float = 0.25, threshold: float = 0.02,
              stillness: float = 0.004, max_pops: int = 24, render=None) -> PopScan:
    """Find parts of the picture that change in one frame between still frames.

    The failure this catches has no other symptom: an element is *there* and
    then, one frame later, *there* — a keyframe pair with nothing interpolated
    between them, a `data-start` on a moving element, a selector that flips.
    Each frame on its own is a perfectly good picture, so `check` (which reads
    declarations) and `strip` (which samples the clip) both miss it.

    The criterion is **stillness, change, stillness** — a frame that differs a
    lot from its neighbour while both neighbours differ from *their* neighbours
    by almost nothing. That is what separates a pop from fast-but-continuous
    motion: an ease-out entrance moves a great deal in its first frames, and
    keeps moving, so it fails the "and then it stopped" half. A hard
    `data-start` cut passes, which is correct: it *is* a change in one frame,
    and the author may or may not have meant it.

    So each hit says whether a **declared clip boundary lands on that frame**.
    `declared: true` means the composition asked for it (`data-start` /
    `data-duration`); `declared: false` means nothing in the markup does, and
    that is the one worth chasing.

    Frames are compared at ``scale`` (a quarter by default): the question is
    "did this region change", not "by how much". A quarter-size grey frame of a
    1080p clip is ~130 KB, so a 900-frame clip holds ~120 MB of them — the
    reason the scale is a parameter and the default is not 1.0.
    """
    import numpy as np

    from nanoframes.render import render_frame

    comp = doc.composition
    rate = comp.fps or 1
    count = comp.frame_count
    scan = PopScan(frames=count, threshold=threshold)
    if count < 3:
        return scan

    boundaries = _declared_boundaries(doc)

    def small(i: int):
        img = (render or render_frame)(doc, i / rate, cache=None, scale=scale,
                                       warn_blank=False)
        return np.asarray(img.convert("L"), dtype=np.int16)

    # Two passes, because the two halves of the criterion want different
    # neighbours: "changed a lot" is a property of one delta, "was still before
    # and after" is a property of the deltas on either side of the *event*.
    frames = [small(0)]
    deltas = [0.0]                      # deltas[i] = change from frame i-1 to i
    for i in range(1, count):
        frames.append(small(i))
        deltas.append(float((np.abs(frames[-1] - frames[-2]) > 8).mean()))

    # A one-frame move lights up one or two consecutive deltas (the moving
    # element's old and new positions can both straddle a frame), so an *event*
    # is a run of deltas above the threshold, not a single one.
    events: list[tuple] = []
    index = 1
    while index < len(deltas):
        if deltas[index] <= threshold:
            index += 1
            continue
        start = index
        peak = deltas[index]
        while index + 1 < len(deltas) and deltas[index + 1] > threshold:
            index += 1
            peak = max(peak, deltas[index])
        events.append((start, index, peak))
        index += 1

    for start, end, peak in events:
        before = deltas[start - 1] if start >= 1 else 0.0
        after = deltas[end + 1] if end + 1 < len(deltas) else 0.0
        # Stillness on **both** sides. This is the whole discrimination: an
        # ease-out entrance changes a lot and keeps changing, an element that
        # pops is surrounded by identical frames. Relaxing it to "either side"
        # was measured to report 13 regions on a clean badge (entrance ramps),
        # which is how a check stops being read.
        if before > stillness or after > stillness:
            continue
        # The event's *last* delta end is the first frame that shows the new
        # picture (delta[i] compares i-1 with i), so that is the frame to
        # report: it is the one a reader should look at, and the one whose
        # before/after tells appeared from vanished.
        previous, current = frames[end - 1], frames[end]
        moved = np.abs(current - previous) > 8
        ys, xs = np.nonzero(moved)
        if not len(xs):
            continue
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
        box = (int(xs.min() / scale), int(ys.min() / scale),
               int(xs.max() / scale), int(ys.max() / scale))
        # "Blank" is *the background*, which is white in most compositions:
        # testing for darkness called a black rect appearing on a white plate
        # a vanish (measured). So compare against the frame's own corner pixel
        # — the one place a change in the middle cannot move.
        background = int(previous[0, 0])
        tolerance = 8
        was_blank = float((np.abs(previous[y0:y1, x0:x1] - background) <= tolerance).mean())
        now_blank = float((np.abs(current[y0:y1, x0:x1] - background) <= tolerance).mean())
        if was_blank > 0.6 and now_blank < 0.4:
            how = "appeared"
        elif now_blank > 0.6 and was_blank < 0.4:
            how = "vanished"
        else:
            how = "jumped"
        t = end / rate
        landings = [b for b in boundaries if abs(b - t) <= 1.5 / rate + 1e-9]
        scan.pops.append(Pop(frame=end, t=t, box=box, changed=peak, how=how,
                             declared=bool(landings),
                             declared_at=landings[0] if landings else None))
        if len(scan.pops) >= max_pops:
            break
    return scan

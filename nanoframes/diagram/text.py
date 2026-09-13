"""Text measurement and tracking for diagrams.

Everything here is measured through ``nanoframes.measure.Measurer``, i.e. the
same ThorVG rasterization path that draws the final frame — so a node box that
fits its label in the layout pass also fits it in the render.

Two ThorVG behaviors shape this module:

* ``letter-spacing`` is accepted and ignored, so tracked text (eyebrows, zone
  labels, tags — the source's mono-uppercase register) is one ``<text>`` whose
  measured width carries the advance a CSS tracking factor would give.
* ``rgba()`` colors paint solid black, so masks are ``paper`` hex at full
  opacity (never a translucent plate).

A ``measurer`` is any object with ``ink(text, family, weight, size_px) ->
InkMetrics``; passing ``None`` falls back to a deterministic width estimate
(``size * 0.6`` per character), which is what unit tests use to keep layout
math independent of host fonts.
"""

from __future__ import annotations

from dataclasses import dataclass

from nanoframes.diagram import geometry as geo

_MONO_USER = ("mono", "monospace", "sarasa", "tofu", "等宽", "console", "fixedsys", "courier")


@dataclass(frozen=True)
class Metrics:
    """Ink box of a text run, anchored at its ``<text> x`` (baseline)."""

    width: float
    left: float
    top: float      # negative: ink rises above the baseline
    bottom: float   # positive: descenders below it

    @property
    def height(self) -> float:
        return self.bottom - self.top


def is_mono(family: str) -> bool:
    """Whether a font stack must be treated as monospaced (width budget rule)."""
    if "sarasa" in family.lower():
        return True               # the bundled mono CJK face
    return any(h in family.lower() for h in _MONO_USER)


def measure(measurer, text: str, family: str, weight: str, size: float,
            tracking_em: float = 0.0) -> Metrics:
    """Ink metrics for ``text``; deterministic estimate when unmeasured.

    ``tracking_em`` is the CSS letter-spacing the source specifies (0.18em for
    eyebrows, 0.06em for arrow labels). The estimate adds it per character, so a
    tracked run is never under-sized even without an engine.
    """
    if measurer is not None:
        ink = measurer.ink(text, family, weight, size)
        return Metrics(ink.w, ink.left_dx, ink.top, ink.bottom)
    per_char = size * (0.62 if is_mono(family) else 0.60) + tracking_em * size
    return Metrics(max(size * 0.5, len(text) * per_char), 1.0, -size * 0.72, size * 0.20)


def visual_width(measurer, text: str, family: str, weight: str, size: float,
                 tracking_em: float, tracking_px: float) -> float:
    """Width of a run as *drawn*, tracking included.

    Compares the tracked and untracked ink widths (both measured through the
    renderer), so the widening a browser would apply via ``letter-spacing`` is
    reproduced exactly where the engine ignores the attribute.
    """
    plain = measure(measurer, text, family, weight, size)
    if not tracking_px:
        return plain.width
    tracked = measure_with_tracking(measurer, text, family, weight, size, tracking_px)
    if measurer is not None:
        return max(tracked.width, plain.width + tracking_px)
    return tracked.width


def measure_with_tracking(measurer, text: str, family: str, weight: str,
                          size: float, tracking_px: float) -> Metrics:
    """Measure a run with the per-character tracking the emitter will draw."""
    if measurer is None:
        per_char = size * (0.62 if is_mono(family) else 0.60) + tracking_px
        return Metrics(max(size * 0.5, len(text) * per_char), 1.0, -size * 0.72, size * 0.20)
    ink = measurer.ink(text, family, weight, size, letter_spacing=tracking_px)
    return Metrics(ink.w, ink.left_dx, ink.top, ink.bottom)


# ---------------------------------------------------------------------------
# Node boxes
# ---------------------------------------------------------------------------

PAD_X = 12.0
PAD_Y = 10.0
LABEL_SUB_GAP = 4.0
TAG_W = 28.0
TAG_H = 12.0
TAG_INSET_X = 8.0
TAG_INSET_Y = 6.0


def tag_reserve(tag: str, ramp: dict) -> float:
    """Vertical space a corner type-tag takes from the label cluster.

    The tag occupies the box's top-left corner; the centred label must clear it
    (the source's node pattern puts the tag above the name, not through it), so
    a tagged box grows by this much and its text block drops by half of it.
    """
    return (TAG_INSET_Y + TAG_H + 4.0) if tag else 0.0


def box_size(measurer, label: str, sub: str, tag: str, ramp: dict,
             font_label: str, font_sub: str) -> tuple[float, float]:
    """Auto-sized node box ``(w, h)``, on the 4px grid.

    Width = max(label, sub, tag) ink + padding. Height = the measured ink block
    of the label plus its optional sublabel, with the 4px-grid gap between them
    — the box grows to fit the face it will actually render with, rather than
    assuming a point-size conversion.
    """
    label_m = measure(measurer, label, font_label, "600", ramp["label"]) if label \
        else Metrics(0.0, 0.0, 0.0, 0.0)
    sub_m = measure(measurer, sub, font_sub, "400", ramp["sub"]) if sub \
        else Metrics(0.0, 0.0, 0.0, 0.0)
    tag_m = measure(measurer, tag, font_sub, "400", ramp["tag"]) if tag \
        else Metrics(0.0, 0.0, 0.0, 0.0)
    w = max(label_m.width, sub_m.width,
            (TAG_INSET_X + TAG_W + TAG_INSET_X) if tag else 0.0, tag_m.width + 2 * PAD_X)
    # The two lines straddle the box centre: label ink above, sublabel ink below
    # (see node_texts, which spends the same budget).
    half = label_m.bottom + LABEL_SUB_GAP + (-sub_m.top) / 2.0
    tall = (-label_m.top) + 2 * half + sub_m.bottom if sub else label_m.height
    h = tall + 2 * PAD_Y + tag_reserve(tag, ramp)
    return float(max(80.0, geo.ceil4(w))), float(max(ramp["min_box_h"], geo.ceil4(h)))


def node_texts(measurer, x: float, y: float, w: float, h: float, label: str,
               sub: str, tag: str, ramp: dict, font_label: str, font_sub: str,
               ink: str, muted: str, soft: str, accent: str,
               focal: bool = False) -> list:
    """The text runs inside a node box, positioned per the source's node pattern.

    The label's baseline sits so its measured descent clears the sublabel's ink
    by ``LABEL_SUB_GAP``; the pair straddles the box's vertical centre. Descent
    is *measured* (not assumed from the point size), because this renderer's
    faces carry very different descender depths.
    """
    from nanoframes.diagram.scene import Text

    out = []
    cx = x + w / 2.0
    reserved = tag_reserve(tag, ramp)
    label_y0 = y + reserved / 2.0
    label_h = h - reserved / 2.0
    has_sub = bool(sub)
    label_metrics = measure(measurer, label, font_label, "600", ramp["label"])
    if has_sub:
        sub_metrics = measure(measurer, sub, font_sub, "400", ramp["sub"])
        half = label_metrics.bottom + LABEL_SUB_GAP + (-sub_metrics.top) / 2.0
        label_baseline = label_y0 + label_h / 2.0 - half
        sub_baseline = label_y0 + label_h / 2.0 + half
    else:
        label_baseline = (label_y0 + label_h / 2.0
                          - (label_metrics.top + label_metrics.bottom) / 2.0)
        sub_baseline = label_baseline
    out.append(Text(x=cx, y=round(label_baseline, 1), content=label,
                    size=ramp["label"], fill=accent if focal else ink,
                    family=font_label, anchor="middle", kind="label"))
    if has_sub:
        out.append(Text(x=cx, y=round(sub_baseline, 1), content=sub,
                        size=ramp["sub"], fill=muted, family=font_sub,
                        anchor="middle", kind="sub"))
    if tag:
        tag_m = measure(measurer, tag.upper(), font_sub, "400", ramp["tag"])
        chip_x, chip_y = x + TAG_INSET_X, y + TAG_INSET_Y
        out.append(Text(x=chip_x + TAG_W / 2.0,
                        y=chip_y + (TAG_H + (-tag_m.top) - tag_m.bottom) / 2.0,
                        content=tag.upper(), size=ramp["tag"],
                        fill=soft, family=font_sub, anchor="middle", kind="tag"))
    return out


def tag_chip(x: float, y: float, name: str, stroke: str, rough: bool = False) -> list:
    """The type tag's chip outline at ``(x, y)`` — a rect, or hand-drawn strokes.

    Emitted by the same module that lays out the tag's text, from the same
    constants, so the outline cannot drift from the text. A caller that wants the
    sketchy register gets the right outline on the first pass, instead of
    finding and replacing a rect in the assembled group.
    """
    from nanoframes.diagram.scene import Path, Rect

    chip_x, chip_y = x + TAG_INSET_X, y + TAG_INSET_Y
    if not rough:
        return [Rect(x=chip_x, y=chip_y, w=TAG_W, h=TAG_H, rx=2, fill="none",
                     stroke=stroke, stroke_opacity=0.4, stroke_width=0.8,
                     weight="chip")]
    from nanoframes.diagram import sketchy

    return [Path(d=d, stroke=stroke, stroke_width=1.4, opacity=0.4)
            for d in sketchy.rough_rect(chip_x, chip_y, TAG_W, TAG_H, name)]


# ---------------------------------------------------------------------------
# Mask plates
# ---------------------------------------------------------------------------

MASK_PAD_X = 6.0
MASK_PAD_Y = 4.0


def text_box(run, measurer) -> tuple:
    """``(x, y, w, h)`` of a text run's opaque plate.

    Arrow labels and zone eyebrows sit on a paper-colored mask so a connector
    never bleeds through the glyphs (source §6). The plate is sized from the
    *measured* ink plus padding, so it can never clip the text it protects.
    """
    if run.tracking:
        width = run.size * len(run.content) * 0.62 + run.tracking * len(run.content)
        left = 0.0
    else:
        metrics = measure(measurer, run.content, run.family, "400", run.size)
        width = metrics.width
        left = metrics.left
    if run.anchor == "middle":
        x = run.x - width / 2.0 - MASK_PAD_X
    elif run.anchor == "end":
        x = run.x - width - MASK_PAD_X
    else:
        x = run.x + left - MASK_PAD_X
    metrics = measure(measurer, run.content, run.family, "400", run.size)
    height = metrics.height + 2 * MASK_PAD_Y
    y = run.y + metrics.top - MASK_PAD_Y
    return (round(x, 1), round(y, 1), round(width + 2 * MASK_PAD_X, 1), round(height, 1))


# ---------------------------------------------------------------------------
# Tracked (letter-spaced) runs
# ---------------------------------------------------------------------------


def tracked_run(x: float, y: float, content: str, size: float, fill: str,
                family: str, tracking_px: float, anchor: str,
                kind: str, mask: bool = False, opacity: float = 1.0):
    """One tracked ``Text`` run (zone eyebrows, type tags).

    ``tracking_px`` is the px a browser would add per character; the emitter
    folds it into the run's width. It stays a single ``<text>`` so the run
    cannot drift or overlap — the estimate is what the layout is *shown* to be,
    not what the glyphs are individually placed at.
    """
    from nanoframes.diagram.scene import Text

    return Text(x=x, y=y, content=content.upper(), size=size, fill=fill,
                family=family, anchor=anchor, kind=kind, tracking=tracking_px,
                mask=mask, opacity=opacity)

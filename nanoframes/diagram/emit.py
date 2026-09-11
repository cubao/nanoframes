"""Scene → ``.nf.svg``: the emitter.

Output is a plain nanoframes composition — a valid SVG with per-group
``data-start`` / ``data-duration`` / ``data-fade`` and nothing else — so
``nanoframes check``, ``render``, ``video`` and ``debug`` all work on it
unchanged. Emitted content stays inside the SVG Tiny 1.2 subset ThorVG
rasterizes: no CSS, no ``<marker>``, no ``rgba()`` (see ``tokens``).
"""

from __future__ import annotations

from nanoframes.diagram import text as txt
from nanoframes.diagram.scene import Group, Path, Rect, Scene, Text
from nanoframes.diagram.text import text_box


_MASK_PAD_Y = 4.0


def _fmt(value: float) -> str:
    return f"{round(value, 2):g}"


def _esc(content: str) -> str:
    return (content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _attrs(pairs: list) -> str:
    return " ".join(f'{k}="{v}"' for k, v in pairs if v is not None)


def _rect_attrs(rect: Rect) -> str:
    pairs = [
        ("x", _fmt(rect.x)), ("y", _fmt(rect.y)),
        ("width", _fmt(rect.w)), ("height", _fmt(rect.h)),
        ("fill", rect.fill),
    ]
    if rect.fill_opacity < 1.0:
        pairs.append(("fill-opacity", _fmt(rect.fill_opacity)))
    if rect.stroke:
        pairs.append(("stroke", rect.stroke))
        pairs.append(("stroke-width", _fmt(rect.stroke_width)))
        if rect.stroke_opacity < 1.0:
            pairs.append(("stroke-opacity", _fmt(rect.stroke_opacity)))
        if rect.dash:
            pairs.append(("stroke-dasharray", rect.dash))
    if rect.rx:
        pairs.append(("rx", _fmt(rect.rx)))
    if rect.opacity < 1.0:
        pairs.append(("opacity", _fmt(rect.opacity)))
    return _attrs(pairs)


def _path_attrs(path: Path) -> str:
    pairs = [("d", path.d), ("fill", "none"), ("stroke", path.stroke),
             ("stroke-width", _fmt(path.stroke_width))]
    if path.dash:
        pairs.append(("stroke-dasharray", path.dash))
    return _attrs(pairs)


def _head_markup(path: Path) -> str:
    if not path.head:
        return ""
    if path.head_fill:
        return f'<polygon points="{path.head}" fill="{path.head_fill}"/>'
    return (f'<polyline points="{path.head}" fill="none" stroke="{path.stroke}"'
            ' stroke-width="1.2"/>')


def _run_markup(run: Text, x: float, anchor: str) -> str:
    pairs = [
        ("x", _fmt(x)), ("y", _fmt(run.y)),
        ("font-family", run.family), ("font-size", _fmt(run.size)),
        ("fill", run.fill),
    ]
    if anchor != "start":
        pairs.append(("text-anchor", anchor))
    if run.opacity < 1.0:
        pairs.append(("opacity", _fmt(run.opacity)))
    pairs.append(("xml:space", "preserve"))
    return f'<text {_attrs(pairs)}>{_esc(run.content)}</text>'


def _text_markup(run: Text, measurer) -> str:
    """One run's markup.

    ThorVG ignores ``text-anchor``: this build left-aligns *every* run at its
    ``x``, whatever the attribute says. A centred run is therefore emitted as
    one ``<text>`` per glyph, each placed by its measured advance — the same
    trick tracked text needs, and the anchor the node-box system is built on
    (boxes are sized to centred labels, so left-aligned text overflows them).
    """
    if run.anchor == "middle" and measurer is not None and len(run.content) > 1:
        return _centred_markup(run, measurer)
    return _run_markup(run, run.x, run.anchor)


def _centred_markup(run: Text, measurer) -> str:
    """Per-glyph placement so the run is visually centred on ``run.x``.

    Advances come from calibration minus each glyph's left side bearing (its ink
    offset), which keeps the drawn extent equal to the measured box.
    """
    advance = (run.size * 0.62 + run.tracking) if run.tracking else _advance(run, measurer)
    glyphs = list(run.content)
    lefts = [txt.measure(measurer, glyph, run.family, "400", run.size).left
             for glyph in glyphs]
    cursor = run.x - (advance * len(glyphs)) / 2.0
    out = []
    for glyph, left in zip(glyphs, lefts):
        out.append(_run_markup(_glyph_run(run, glyph), cursor - left, "start"))
        cursor += advance
    return "".join(out)


def _advance(run: Text, measurer) -> float:
    """The run's per-glyph advance, calibrated against the renderer.

    A single glyph's *ink* width is not its advance (right side bearings are
    wide on round letters), so this measures a repeating string and divides —
    exact for the mono faces this system uses, close enough for proportional
    ones. Deliberately uncached here: the result depends on *which* measurer
    asked (a fake one for tests, the ThorVG one for real), and the underlying
    measurement is already cached by the measurer itself.
    """
    return txt.measure(measurer, "H" * 8, run.family, "400", run.size).width / 8.0


def _glyph_run(run: Text, content: str) -> Text:
    return Text(x=run.x, y=run.y, content=content, size=run.size, fill=run.fill,
                family=run.family, anchor="start", kind=run.kind, tracking=run.tracking,
                mask=False, opacity=run.opacity)


def _group_markup(group: Group, reveal: bool, measurer, paper: str,
                  duration: float) -> str:
    timing = ""
    if reveal and group.fade > 0:
        # The clip window is [start, start + duration]: ending it at the
        # composition's duration is what keeps the reveal (and `nanoframes
        # check`) free of out-of-range warnings.
        remaining = max(0.0, duration - group.start)
        timing = (f' data-start="{_fmt(group.start)}"'
                  f' data-duration="{_fmt(remaining)}"'
                  f' data-fade="{_fmt(min(group.fade, remaining))}"')
    body = []
    for part in group.parts:
        if isinstance(part, Rect):
            body.append(f"<rect {_rect_attrs(part)}/>")
        elif isinstance(part, Path):
            body.append(f'<path {_path_attrs(part)}/>')
            head = _head_markup(part)
            if head:
                body.append(head)
    # A mask plate is emitted for a run that asked for one but did not bring its
    # own: the builder may have laid out the plate itself (an id the run belongs
    # to), and re-emitting it here would paint over the text.
    runs = [p for p in group.parts if isinstance(p, Text)]
    has_plate = any(isinstance(part, Rect) and part.weight == "chip" for part in group.parts)
    for run in [p for p in runs if p.mask and not has_plate]:
        x, y, w, h = text_box(run, measurer)
        body.append(f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}"'
                    f' height="{_fmt(h)}" rx="2" fill="{paper}"/>')
    for run in runs:
        body.append(_text_markup(run, measurer))
    if not body:
        return ""
    ident = f' id="{_esc(group.name)}"' if group.name else ""
    return f"<g{ident}{timing}>" + "".join(body) + "</g>"


def render(scene: Scene, reveal: bool | None = None, composition_id: str | None = None,
           measurer=None) -> str:
    """Serialize a scene to an ``.nf.svg`` composition string."""
    if reveal is None:
        reveal = scene.duration > 1.0 or any(g.fade > 0 for g in scene.groups)
    head = _attrs([
        ("xmlns", "http://www.w3.org/2000/svg"),
        ("data-width", _fmt(scene.width)), ("data-height", _fmt(scene.height)),
        ("data-fps", scene.fps), ("data-duration", _fmt(scene.duration)),
        ("data-composition-id", composition_id),
        ("width", _fmt(scene.width)), ("height", _fmt(scene.height)),
    ])
    parts = [f"<svg {head}>"]
    parts.append(f'<rect id="bg" width="{_fmt(scene.width)}" height="{_fmt(scene.height)}"'
                 f' fill="{scene.background}"/>')
    for group in scene.groups:
        if any(isinstance(p, Rect) and p.weight == "background" for p in group.parts):
            continue  # the paper plate renders as #bg above
        markup = _group_markup(group, reveal, measurer, scene.background,
                               scene.duration)
        if markup:
            parts.append(markup)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"

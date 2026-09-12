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
    """One run's markup, with the position ThorVG actually honours.

    ThorVG ignores ``text-anchor``: every run is left-aligned at its ``x``. It
    also resolves *every* family to the one loaded face, which is monospaced in
    this engine — so a run's drawn width is its measured ink width, and a
    "centred" run is exactly one ``<text>`` at
    ``x - ink_w/2 + left_bearing``. (Earlier versions emitted one ``<text>`` per
    glyph to work around the ignored anchor; a single element is exact *and*
    cannot drift, overlap, or lose its spacing.)

    ``tracking`` widens the run: the advance a browser would add per character
    is folded into the width, and the offset is derived from the same number, so
    the run stays centred on its anchor.
    """
    if measurer is None or (run.anchor == "start" and not run.tracking):
        return _run_markup(run, run.x, run.anchor)
    ink = txt.measure(measurer, run.content, run.family, "400", run.size)
    width = ink.width
    if run.tracking:
        width = txt.visual_width(measurer, run.content, run.family, "400", run.size,
                                 0.0, run.tracking)
    if run.anchor == "middle":
        x = run.x - width / 2.0 + ink.left
    elif run.anchor == "end":
        x = run.x - width + ink.left
    else:
        x = run.x
    return _run_markup(run, x, "start")


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

"""Bake-time text auto-layout: measured background chips, line wrapping, and
text-along-curve.

Runs on the already-baked per-frame tree (animated props materialized) and uses
a ``Measurer`` (renderer-exact pixel measurement) to place geometry:

* ``data-bg``           draw a rounded background rect sized to the glyph ink.
* ``data-wrap``         break long text into stacked lines that fit a width.
* ``data-curve-d="/``
  ``data-curve-circle`` place each character along a sampled curve, rotated to
                        follow the tangent (ThorVG has no ``<textPath>``).

If no ``Measurer`` is supplied the pass is a no-op, so plain compositions bake
exactly as before.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from nanoframes.model import qname
from nanoframes.measure import InkMetrics, Measurer
from nanoframes.parse import _local


def apply_text_autoflow(root: ET.Element, measurer: Measurer | None) -> None:
    if measurer is None:
        return
    for node in [n for n in root.iter() if _local(n.tag) == "text"]:
        bg = node.get("data-bg")
        wrap = node.get("data-wrap")
        curve_d = node.get("data-curve-d")
        curve_circle = node.get("data-curve-circle")
        if bg is None and wrap is None and curve_d is None and curve_circle is None:
            continue
        style = _style(node)
        content = node.text or ""
        parent = _find_parent(root, node)

        if curve_d or curve_circle:
            _expand_curve(parent, node, content, style, measurer,
                          _curve_spec(curve_d, curve_circle))
            continue

        if wrap is not None:
            _expand_wrap(parent, node, content, style, measurer, bg, float(wrap))
            continue

        # single-line background chip
        m = measurer.ink(content, style["family"], style["weight"], style["size"],
                         style["letter_spacing"])
        idx = list(parent).index(node)
        parent.insert(idx, _chip_rect(m, style["x"], style["y"], bg, _bg_opt(node),
                                      _style_fill(node)))


# ---------------------------------------------------------------------------
# curve
# ---------------------------------------------------------------------------

def _curve_spec(d, circle) -> str:
    if circle:
        return "circle " + circle.strip().replace(",", " ")
    return d


def _expand_curve(parent, node, content, style, measurer, spec) -> None:
    from nanoframes.curve import PathSampler

    if spec.startswith("circle"):
        tokens = spec.split()
        sampler = PathSampler.circle(float(tokens[1]), float(tokens[2]),
                                     float(tokens[3]), float(tokens[4]) if len(tokens) > 4 else -90.0)
    else:
        sampler = PathSampler(spec)

    g = ET.Element(qname("g"))
    _carry(g, node)
    idx = list(parent).index(node)
    parent.remove(node)
    parent.insert(idx, g)

    adv = 0.0
    for ch in content:
        m = measurer.ink(ch, style["family"], style["weight"], style["size"],
                         style["letter_spacing"])
        p = adv + m.center_dx
        px, py = sampler.point(p)
        ang = sampler.angle(p)
        glyph = ET.Element(qname("text"))
        glyph.set("x", f"{px - m.center_dx:g}")
        glyph.set("y", f"{py - (m.top + m.h / 2):g}")
        glyph.set("transform", f"rotate({ang:g} {px:g} {py:g})")
        for k, v in style["font"].items():
            glyph.set(k, v)
        for k, v in _style_fill(node).items():
            glyph.set(k, v)
        glyph.text = ch
        g.append(glyph)
        adv += m.w + style["letter_spacing"]


# ---------------------------------------------------------------------------
# wrap (+ optional block chip)
# ---------------------------------------------------------------------------

def _expand_wrap(parent, node, content, style, measurer, bg_color, max_width) -> None:
    step = style["size"] * 1.2
    lines = _wrap(content, style, max_width, measurer)
    if bg_color:
        block = _block_box(lines, style["y"], step)
        chip = _chip_rect(block, style["x"], style["y"], bg_color, _bg_opt(node),
                          _style_fill(node), block_mode=True)

    g = ET.Element(qname("g"))
    _carry(g, node)
    first_id = node.get("id")
    parent_node = list(parent)
    idx = parent_node.index(node)
    parent.remove(node)
    for i, (line_text, m) in enumerate(lines):
        line = ET.Element(qname("text"))
        line.set("x", f"{style['x']:g}")
        line.set("y", f"{style['y'] + i * step:g}")
        for k, v in style["font"].items():
            line.set(k, v)
        for k, v in _style_fill(node).items():
            line.set(k, v)
        if i == 0 and first_id:
            line.set("id", first_id)
        elif first_id:
            line.set("id", f"{first_id}-l{i}")
        line.text = line_text
        g.append(line)
    if bg_color:
        parent.insert(idx, chip)
        idx += 1
    parent.insert(idx, g)


def _wrap(content, style, max_width, measurer) -> list[tuple[str, InkMetrics]]:
    tokens = _tokens(content)
    lines: list[tuple[str, InkMetrics]] = []
    cur: list[str] = []
    for tok in tokens:
        trial = (" ".join(cur + [tok]) if cur else tok)
        m = measurer.ink(trial, style["family"], style["weight"], style["size"],
                         style["letter_spacing"])
        w = m.right_dx - m.left_dx + 1
        if cur and w > max_width:
            lines.append(_meas(" ".join(cur), style, measurer))
            cur = [tok]
        else:
            cur.append(tok)
    if cur:
        lines.append(_meas(" ".join(cur), style, measurer))
    if not lines:
        lines.append(_meas(content, style, measurer))
    return lines


def _meas(text, style, measurer) -> tuple[str, InkMetrics]:
    m = measurer.ink(text, style["family"], style["weight"], style["size"],
                     style["letter_spacing"])
    return text, m


def _block_box(lines, style_y: float, step: float) -> InkMetrics:
    top = min(style_y + i * step + m.top for i, (_, m) in enumerate(lines))
    bottom = max(style_y + i * step + m.bottom for i, (_, m) in enumerate(lines))
    w = max(m.w for _, m in lines)
    return InkMetrics(0.0, w, top - style_y, bottom - style_y, w, bottom - top)


def _tokens(text: str) -> list[str]:
    import unicodedata as u
    out, buf = [], []
    for ch in text:
        if u.east_asian_width(ch) in ("W", "F"):
            if buf:
                out.append("".join(buf)); buf = []
            out.append(ch)
        elif ch.isspace():
            if buf:
                out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out or [text]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bg_opt(node: ET.Element) -> dict:
    return {
        "rx": _f(node.get("data-bg-rx"), 10.0),
        "pad_x": _f(node.get("data-bg-pad-x"), 12.0),
        "pad_y": _f(node.get("data-bg-pad-y"), 8.0),
    }


def _chip_rect(m: InkMetrics, anchor_x: float, baseline_y: float, color: str,
               opt: dict, fill: dict, block_mode: bool = False) -> ET.Element:
    pad_x, pad_y = opt["pad_x"], opt["pad_y"]
    rect = ET.Element(qname("rect"))
    if block_mode:
        rect.set("x", f"{anchor_x - pad_x:g}")
    else:
        rect.set("x", f"{anchor_x + m.center_dx - (m.w / 2 + pad_x):g}")
    rect.set("y", f"{baseline_y + m.top - pad_y:g}")
    rect.set("width", f"{m.w + 2 * pad_x:g}")
    rect.set("height", f"{m.h + 2 * pad_y:g}")
    rect.set("rx", f"{opt['rx']:g}")
    rect.set("fill", color)
    return rect


def _style(node: ET.Element) -> dict:
    family = node.get("font-family") or "Arial"
    weight = node.get("font-weight") or "normal"
    size = _f(node.get("font-size"), 16.0)
    font = {}
    for attr in ("font-family", "font-weight", "font-style"):
        v = node.get(attr)
        if v:
            font[attr] = v
    if "font-family" not in font:
        font["font-family"] = family
    return {
        "x": _f(node.get("x"), 0.0),
        "y": _f(node.get("y"), 0.0),
        "size": size,
        "family": family,
        "weight": weight,
        "font": font,
        "letter_spacing": _f(node.get("letter-spacing"), 0.0),
    }


def _style_fill(node: ET.Element) -> dict:
    out = {}
    for attr in ("fill", "fill-opacity"):
        v = node.get(attr)
        if v:
            out[attr] = v
    return out


def _carry(g: ET.Element, node: ET.Element) -> None:
    for attr in ("transform", "opacity"):
        v = node.get(attr)
        if v:
            g.set(attr, v)


def _f(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _find_parent(root: ET.Element, node: ET.Element):
    for p in root.iter():
        if node in list(p):
            return p
    raise RuntimeError("orphan text node during autoflow")
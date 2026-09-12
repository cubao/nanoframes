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

from nanoframes.measure import InkMetrics, Measurer
from nanoframes.xmlutil import find_parent, float_attr, local_name, qname


def apply_text_autoflow(root: ET.Element, measurer: Measurer | None) -> None:
    if measurer is None:
        return
    for node in [n for n in root.iter() if local_name(n.tag) == "text"]:
        bg = node.get("data-bg")
        wrap = node.get("data-wrap")
        curve_d = node.get("data-curve-d")
        curve_circle = node.get("data-curve-circle")
        fit = node.get("data-fit")
        if bg is None and wrap is None and curve_d is None and curve_circle is None and fit is None:
            continue
        style = _style(node)
        content = node.text or ""
        parent = find_parent(root, node)
        if parent is None:
            raise RuntimeError("orphan text node during autoflow")

        # auto-shrink font-size until the text fits on one line (no wrap/curve)
        if fit is not None and wrap is None and curve_d is None and curve_circle is None:
            fitted = _fit_font_size(content, style, float(fit), measurer)
            if fitted and fitted != style["size"]:
                node.set("font-size", f"{fitted:g}")
                style = _style(node)

        if curve_d or curve_circle:
            _expand_curve(parent, node, content, style, measurer,
                          _curve_spec(curve_d, curve_circle))
            continue

        if wrap is not None:
            _expand_wrap(parent, node, content, style, measurer, bg, float(wrap))
            continue

        # single-line background chip (+ optional fit already applied)
        if bg is not None:
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
    for i, (line_text, _metrics) in enumerate(lines):
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
    items, seps = _tokens(content)
    items, seps = _explode(items, seps, max_width, style, measurer)
    measure = _line_measure(style, measurer)

    lines: list[str] = []
    cur: list[int] = []
    for j in range(len(items)):
        if cur and measure(_join(items, seps, cur + [j])) > max_width:
            # 追い出し: rather than leave an offender that may not begin a line
            # (行頭禁則) at the head of the next one, or a character that may not
            # end one (行末禁則) at the tail of this one, send the previous unit
            # down with it — but only when the pair actually fits, or the box
            # would lose to the rule it is supposed to obey.
            if (_break_blocked(items, cur, j) and len(cur) > 1
                    and measure(_join(items, seps, cur[-1:] + [j])) <= max_width):
                moved = [cur.pop(), j]
                lines.append(_join(items, seps, cur))
                cur = moved
                continue
            lines.append(_join(items, seps, cur))
            cur = [j]
            continue
        cur.append(j)
    if cur:
        lines.append(_join(items, seps, cur))
    if not lines:
        lines.append(content)
    return [_meas(text, style, measurer) for text in lines]


def _meas(text, style, measurer) -> tuple[str, InkMetrics]:
    m = measurer.ink(text, style["family"], style["weight"], style["size"],
                     style["letter_spacing"])
    return text, m


def _block_box(lines, style_y: float, step: float) -> InkMetrics:
    top = min(style_y + i * step + m.top for i, (_, m) in enumerate(lines))
    bottom = max(style_y + i * step + m.bottom for i, (_, m) in enumerate(lines))
    w = max(m.w for _, m in lines)
    return InkMetrics(0.0, w, top - style_y, bottom - style_y, w, bottom - top)


# Characters that may not begin a line (行頭禁則). A wrapped CJK paragraph whose
# second line opens on 。or ，is the tell that it was broken by arithmetic alone.
_NO_START = set(",.;:!?)]}%、。，．！？：；）］｝〕〉》」』】〙〗〞”’»›・ー…‥")
# Their mirror: characters that may not end a line (行末禁則).
_NO_END = set("([{（［｛〔〈《「『【〘〖〝“‘«‹")


def _break_blocked(items: list[str], cur: list[int], j: int) -> bool:
    """Is breaking before ``items[j]`` forbidden by the 禁則 sets?"""
    previous = items[cur[-1]]
    return bool(items[j]) and (items[j][0] in _NO_START or previous[-1] in _NO_END)


def _tokens(text: str) -> tuple[list[str], list[str]]:
    """Split ``text`` into line-break units, plus the whitespace before each.

    CJK ideographs and fullwidth forms are units on their own: there is no space
    to break on, so every boundary between them is a legal break. A Latin run
    stays whole. Whitespace is never a unit — it is recorded as the separator of
    the unit that follows, so a separator that lands on a break is dropped
    instead of drawn. Keeping the two apart is what stops CJK being re-joined
    with spaces: joining the units with ``" "`` put a space between every pair
    of ideographs, so a wrapped Chinese line rendered as 确 定 性.
    """
    import unicodedata as u

    items: list[str] = []
    seps: list[str] = []
    buf: list[str] = []
    gap = ""

    def flush() -> None:
        if buf:
            items.append("".join(buf))
            seps.append(gap)
            buf.clear()

    for ch in text:
        if ch.isspace():
            flush()
            gap = " "
        elif u.east_asian_width(ch) in ("W", "F"):
            flush()
            items.append(ch)
            seps.append(gap)
            gap = ""
        else:
            buf.append(ch)
    flush()
    if not items:
        return [text], [""]
    return items, seps


def _join(items: list[str], seps: list[str], idx: list[int]) -> str:
    """Text of the units ``idx`` as one line; the separator before the first is
    dropped, because it is the one that landed on the break."""
    out = [items[idx[0]]]
    for k in idx[1:]:
        out.append(seps[k])
        out.append(items[k])
    return "".join(out)


def _line_measure(style: dict, measurer):
    """Cached ink-width measurement of a candidate line.

    The widths are compared against the box, so ink — not the pen advance — is
    the right quantity: trailing side bearing that draws nothing cannot overflow
    a box. Every candidate is measured as the joined string because pair
    adjustments live between glyphs; a sum of unit widths is a different number.
    """
    cache: dict[str, float] = {}

    def measure(text: str) -> float:
        hit = cache.get(text)
        if hit is None:
            m = measurer.ink(text, style["family"], style["weight"], style["size"],
                             style["letter_spacing"])
            hit = m.right_dx - m.left_dx + 1
            cache[text] = hit
        return hit

    return measure


def _explode(items: list[str], seps: list[str], max_width: float, style: dict,
             measurer) -> tuple[list[str], list[str]]:
    """Split any unit wider than the box into per-character units.

    Without this a single long word ("screenshot" at 38px in a 200px box) has no
    legal break inside it and is placed whole, silently wider than the box it
    was told to fit. A box narrower than one glyph still cannot be satisfied;
    that corner puts the glyph on a line of its own and lets the box lose.
    """
    measure = _line_measure(style, measurer)
    out_items: list[str] = []
    out_seps: list[str] = []
    for item, sep in zip(items, seps):
        if len(item) > 1 and measure(item) > max_width:
            for k, ch in enumerate(item):
                out_items.append(ch)
                out_seps.append(sep if k == 0 else "")
        else:
            out_items.append(item)
            out_seps.append(sep)
    return out_items, out_seps


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bg_opt(node: ET.Element) -> dict:
    return {
        "rx": float_attr(node, "data-bg-rx", 10.0),
        "pad_x": float_attr(node, "data-bg-pad-x", 12.0),
        "pad_y": float_attr(node, "data-bg-pad-y", 8.0),
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
    size = float_attr(node, "font-size", 16.0)
    font = {}
    for attr in ("font-family", "font-weight", "font-style"):
        v = node.get(attr)
        if v:
            font[attr] = v
    if "font-family" not in font:
        font["font-family"] = family
    return {
        "x": float_attr(node, "x", 0.0),
        "y": float_attr(node, "y", 0.0),
        "size": size,
        "family": family,
        "weight": weight,
        "font": font,
        "fit_min": float_attr(node, "data-fit-min", 9.0),
        "letter_spacing": float_attr(node, "letter-spacing", 0.0),
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


def _fit_font_size(content: str, style: dict, max_w: float, measurer) -> float | None:
    """Largest font size <= current that fits ``content`` on one line in max_w px.

    Binary search over font size using the renderer-exact Measurer. Falls back
    to a floor (default 9px) with no fit guarantee if the text can't shrink
    enough."""
    lo = style["fit_min"]
    hi = style["size"]
    if hi <= lo:
        return hi
    # quick: does the declared size already fit?
    if _width_ok(content, style, hi, max_w, measurer):
        return hi
    best = lo
    while lo <= hi:
        mid = (lo + hi) / 2.0
        if _width_ok(content, style, mid, max_w, measurer):
            best = mid
            lo = mid + 0.25
        else:
            hi = mid - 0.25
    return round(best, 2)


def _width_ok(content: str, style: dict, size: float, max_w: float, measurer) -> bool:
    m = measurer.ink(content, style["family"], style["weight"], size,
                     style.get("letter_spacing", 0.0))
    return (m.right_dx - m.left_dx + 1) <= max_w

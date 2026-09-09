"""CJK-capable font discovery and registration.

ThorVG's SVG loader only rasterizes ``<text>`` through fonts explicitly loaded
with ``font_load``, and on macOS almost every CJK face ships as a ``.ttc`` that
this ThorVG build **cannot load** (``font_load`` returns 1 and the text falls
back to a dim built-in face). The reliable approach is to auto-discover a real
CJK ``.ttf``/``.otf`` on the host (or in a vendored directory), load it, and let
authors use its exact family name in ``font-family``.

This module finds such fonts and reports their family names. It is what lets
Chinese labels render *solidly* and with *correct width* (the width the glyphs
actually have), and it prefers a **monospace** face when one is present so each
CJK character is exactly ``font-size`` px wide — making measured chips
perfectly predictable.
"""

from __future__ import annotations

import os

# Directories searched (system + project-vendored + user cache) for CJK fonts.
_SEARCH_DIRS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts"),  # bundled package fonts/
    os.path.expanduser("~/.local/share/nanoframes/fonts"),
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    "/usr/share/fonts",
    "/usr/share/fonts/truetype",
    "/usr/local/share/fonts",
    r"C:\Windows\Fonts",
]

# A font considered "probably has CJK" if its family name mentions any of these.
_CJK_HINTS = (
    "cjk", "hei", "hei", "song", "sung", "kai", "pingfang", "yahei", "gothic",
    "noto sans sc", "noto serif sc", "noto sans mono cjk", "wqy", "wenquanyi",
    "sarasa", "tofu", "ming", "gothic", "zen hei", "hua kang", "han", "cn",
    "simsun", "simhei", "msyahei", "dengxian", "microsof",
)
_MONO_HINTS = ("mono", "monospace", "sarasa", "tofu", "等宽", "console", "fixedsys")

# Fonts that are Apple's CJK faces but ship as .ttc (which ThorVG can't load) —
# explicitly skipped so we don't advertise a family that won't render.
_TTC_UNSUPPORTED = True  # ThorVG in this build fails to load .ttc collections


class FontInfo:
    __slots__ = ("path", "family", "style", "mono", "cjk")

    def __init__(self, path: str, family: str, style: str, mono: bool, cjk: bool):
        self.path = path
        self.family = family
        self.style = style
        self.mono = mono
        self.cjk = cjk

    def __repr__(self) -> str:
        return (f"FontInfo({self.family!r} {self.style!r}, "
                f"cjk={self.cjk} mono={self.mono} {os.path.basename(self.path)})")


def _name_table(text: bytes) -> tuple[str, str]:
    """Parse ``family`` / ``style`` from a TTF/OTF ``name`` table without deps."""
    import struct

    try:
        if text[:4] == b"ttcf":
            # .ttc collection: grab the first face
            ver, nfonts = struct.unpack(">II", text[4:12])
            offset = struct.unpack(">I", text[12:16])[0]
            head = text[offset:]
        else:
            head = text
        num_tables = struct.unpack(">H", head[4:6])[0]
        for i in range(num_tables):
            rec = head[12 + 16 * i: 12 + 16 * (i + 1)]
            tag, check, off, length = struct.unpack(">4sIII", rec)
            if tag == b"name":
                tbl = text[off:off + length]
                return _parse_name(tbl)
    except Exception:
        pass
    return "", ""


def _parse_name(tbl: bytes) -> tuple[str, str]:
    import struct

    family = style = ""
    fmt = struct.unpack(">H", tbl[0:2])[0]
    if fmt != 0:
        return "", ""
    count = struct.unpack(">H", tbl[2:4])[0]
    str_off = struct.unpack(">H", tbl[4:6])[0]
    for i in range(count):
        rec = tbl[6 + 12 * i: 6 + 12 * (i + 1)]
        pid, eid, lid, nid, lng, ln = struct.unpack(">HHHHHH", rec)
        # IDs: 1=family, 2=subfamily; prefer english (pid1/eid0/3/1)
        if nid == 1 and (pid == 1 and eid in (0, 3) or pid == 3):
            family = _decode(tbl, str_off + lng, ln, pid, eid)
        elif nid == 2 and (pid == 1 and eid in (0, 3) or pid == 3):
            style = _decode(tbl, str_off + lng, ln, pid, eid)
    return family, style


def _decode(tbl: bytes, off: int, n: int, pid: int, eid: int) -> str:
    data = tbl[off:off + n]
    if eid == 1:  # mac roman (approx latin1)
        return data.decode("latin-1", "replace")
    try:
        return data.decode("utf-16-be")  # platform 3, eid 1/0/2
    except Exception:
        try:
            return data.decode("latin-1", "replace")
        except Exception:
            return ""


def family_name(path: str) -> tuple[str, str]:
    """Return ``(family, style)`` for a font file.

    Uses Pillow when available (accurate, handles .ttc) and falls back to a
    minimal built-in TTF/OTF ``name``-table parser otherwise.
    """
    try:
        from PIL import ImageFont  # noqa: PLC0415
        f = ImageFont.truetype(path, 16)
        return f.getname()
    except Exception:
        pass
    try:
        with open(path, "rb") as fh:
            data = fh.read(64 * 1024)
        return _name_table(data)
    except Exception:
        pass
    return os.path.splitext(os.path.basename(path))[0], ""


def _looks_cjk(family: str) -> bool:
    fl = family.lower()
    return any(h in fl for h in _CJK_HINTS)


def _looks_mono(family: str) -> bool:
    fl = family.lower()
    return any(h in fl for h in _MONO_HINTS)


def discover_fonts(search_dirs: list[str] | None = None) -> list[FontInfo]:
    """Find loadable ``.ttf``/``.otf`` fonts (never ``.ttc``) across dirs."""
    import random  # noqa: F401

    seen: set[str] = set()
    out: list[FontInfo] = []
    dirs = search_dirs if search_dirs is not None else _SEARCH_DIRS
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            low = n.lower()
            if not (low.endswith(".ttf") or low.endswith(".otf")):
                continue
            if low.endswith(".ttc"):
                continue
            path = os.path.join(d, n)
            if path in seen:
                continue
            seen.add(path)
            family, style = family_name(path)
            if not family:
                continue
            cjk = _cjk_positive(path)
            out.append(FontInfo(
                path, family, style,
                mono=_looks_mono(family),
                cjk=cjk,
            ))
    return out


def _cjk_positive(path: str) -> bool:
    """True if the font is CJK-capable (by cmap coverage or well-known face)."""
    if _cmap_cjk(path):
        return True
    fam, _ = family_name(path)
    return fam in _KNOWN_CJK_FAMILIES


# Well-known CJK face family names (tolerated even when a quick cmap scan misses
# them, e.g. some Korean/style variants that still carry Han glyphs).
_KNOWN_CJK_FAMILIES = {
    "AppleGothic", "Heiti TC", "Heiti SC", "Songti SC", "Songti TC",
    "Hiragino Sans GB", "Hiragino Mincho ProN", "PingFang SC", "PingFang HK",
    "Microsoft YaHei", "Microsoft YaHei UI", "SimHei", "SimSun", "NSimSun",
    "DengXian", "KaiTi", "FangSong", "Noto Sans CJK SC", "Noto Serif CJK SC",
    "Noto Sans Mono CJK SC", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
    "Sarasa Mono SC", "Sarasa Gothic SC", "Source Han Sans SC",
    "Source Han Serif SC", "LXGW WenKai", "MiSans", "HarmonyOS Sans SC",
}


def _cmap_cjk(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except Exception:
        return False
    if data[:4] == b"ttcf":
        return False
    try:
        import struct
        num = struct.unpack(">H", data[4:6])[0]
        for i in range(num):
            tag, check, off, length = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            if tag != b"cmap":
                continue
            n = struct.unpack(">H", data[off + 2:off + 4])[0]
            for j in range(n):
                sub = struct.unpack(">I", data[off + 8 + 8 * j: off + 12 + 8 * j])[0]
                s = data[off + sub: off + sub + 4000]
                if _cmap_has(s, 0x4E2D):
                    return True
    except Exception:
        pass
    return False


def _cmap_has(sub: bytes, cp: int) -> bool:
    import struct
    try:
        fmt = struct.unpack(">H", sub[0:2])[0]
        if fmt == 4:
            segX2 = struct.unpack(">H", sub[6:8])[0]
            nseg = segX2 // 2
            end = [struct.unpack(">H", sub[14 + 2 * i:16 + 2 * i])[0] for i in range(nseg)]
            start_off = 14 + segX2 + 2
            start = [struct.unpack(">H", sub[start_off + 2 * i:start_off + 2 * i + 2])[0]
                     for i in range(nseg)]
            # binary search
            lo, hi = 0, nseg - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if cp < start[mid]:
                    hi = mid - 1
                elif cp > end[mid]:
                    lo = mid + 1
                else:
                    return True
        elif fmt == 12:
            ngroups = struct.unpack(">I", sub[12:16])[0]
            for g in range(ngroups):
                sc, ec, so = struct.unpack(">III", sub[16 + 12 * g:28 + 12 * g])
                if sc <= cp <= ec:
                    return True
    except Exception:
        pass
    return False


def best_cjk_font(search_dirs: list[str] | None = None) -> FontInfo | None:
    """Pick the best available CJK font by static markers (mono first).

    IMPORTANT: this build of ThorVG can crash at teardown when some fonts are
    loaded (e.g. AppleGothic), so we do NOT auto-register here. Use this only as
    an authoring hint; the CLI ``nanoframes fonts verify`` checks load-safety in
    an isolated subprocess.
    """
    fonts = [f for f in discover_fonts(search_dirs) if f.cjk]

    def rank(f: FontInfo) -> tuple:
        return (0 if f.mono else 1, 0 if f.path.lower().endswith(".otf") else 1,
                f.family.lower())
    return min(fonts, key=rank) if fonts else None


def register_extra_fonts(search_dirs: list[str] | None = None) -> list[str]:
    """(Unused by the renderer.) Return the best discovered CJK font path.

    Kept for compatibility/diagnostics. The renderer deliberately does not call
    this because loading arbitrary discovered fonts can crash this ThorVG build;
    see ``nanoframes.fonts`` module docstring and ``fonts verify``.
    """
    best = best_cjk_font(search_dirs)
    return [best.path] if best else []

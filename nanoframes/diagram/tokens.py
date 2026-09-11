"""Editorial diagram design tokens.

Adapted from [diagram-design](https://github.com/cathrynlavery/diagram-design)
(`skills/diagram-design/references/style-guide.md`, MIT, (c) 2025 Cathryn
Lavery) into roles a headless renderer can actually draw.

Two adaptations are load-bearing, because ThorVG's SVG loader does not accept
the browser idioms the source uses:

* **No ``rgba()`` colors.** This ThorVG build parses ``rgba(45,49,66,0.05)``
  as *solid black* — it does not raise, it just paints the wrong thing. Every
  token here is an opaque ``#hex`` plus a separate ``fill-opacity`` /
  ``stroke-opacity``.
* **No CSS custom properties, no per-character letter-spacing.** Tokens resolve
  to hex values at build time; tracked text is emitted as one ``<text>`` per
  character (see ``nanoframes.diagram.text``).
"""

from __future__ import annotations

from dataclasses import dataclass

# The shipped default skin, read left-to-right as in the source style guide.
_DEFAULT_LIGHT = {
    "paper": "#f5f5f5",
    "paper_2": "#ececec",
    "ink": "#2d3142",
    "muted": "#4f5d75",
    "soft": "#7a8399",
    "rule": "#2d3142",
    "rule_solid": "#bfc0c0",
    "accent": "#eb6c36",
    "link": "#2e5aa8",
}
_DEFAULT_DARK = {
    "paper": "#2d3142",
    "paper_2": "#393e53",
    "ink": "#f5f5f5",
    "muted": "#bfc0c0",
    "soft": "#8e98ac",
    "rule": "#f5f5f5",
    "rule_solid": "#bfc0c0",
    "accent": "#f08a59",
    "link": "#6a95d8",
}

# Offline font stacks. The browser skin uses Instrument Serif / Geist / Geist
# Mono web fonts; a headless render only has fonts registered on the ThorVG
# engine (see `nanoframes fonts`), so the stacks name what can actually load and
# everything unknown falls back to the bundled mono CJK face.
FONT_SANS = "Arial, 'DejaVu Sans', sans-serif"
FONT_MONO = "'Sarasa Mono SC', monospace"
FONT_SERIF = "'Times New Roman', 'DejaVu Serif', serif"

# Type ramp by size class (px), from the source output spec §2.
RAMP = {
    "standard": {"title": 28, "label": 12, "sub": 9, "tag": 8, "arrow": 8,
                 "gap": 24, "min_box_h": 48},
    "presentation": {"title": 40, "label": 16, "sub": 12, "tag": 8, "arrow": 12,
                     "gap": 40, "min_box_h": 64},
    "print": {"title": 32, "label": 12, "sub": 9, "tag": 8, "arrow": 8,
              "gap": 24, "min_box_h": 48},
}

# Canvas presets (viewBox width x height), from the source output spec §2.
PRESETS = {
    "doc-inline": (960, 600, "standard"),
    "doc-wide": (1280, 720, "standard"),
    "slide-16x9": (1280, 720, "presentation"),
    "slide-4x3": (1024, 768, "presentation"),
    "social-og": (1200, 632, "presentation"),
    "social-square": (1080, 1080, "presentation"),
    "print-a4-landscape": (1120, 792, "print"),
    "print-letter-landscape": (1056, 816, "print"),
}


@dataclass(frozen=True)
class Tokens:
    """Resolved colors for one skin, plus the active type ramp."""

    skin: str            # "light" | "dark" | "terminal"
    paper: str
    paper_2: str
    ink: str
    muted: str
    soft: str
    rule: str
    rule_solid: str
    accent: str
    link: str
    ramp: dict

    # -- role helpers ---------------------------------------------------------
    @property
    def rule_ink(self) -> tuple[str, float]:
        """Hairline border color: ``rule`` at the source's 12% opacity."""
        return self.rule, 0.12

    @property
    def rule_soft(self) -> tuple[str, float]:
        return self.rule, 0.20

    @property
    def zone_fill(self) -> tuple[str, float]:
        return self.ink, 0.02

    @property
    def zone_stroke(self) -> tuple[str, float]:
        return self.ink, 0.10

    def node_style(self, ntype: str) -> dict:
        """Fill/stroke/dash treatment for a semantic node type.

        Roles and values mirror the source style guide's ``Node type →
        treatment`` table; every float is an opacity, never an rgba string.
        """
        t = self
        table = {
            "focal": dict(fill=t.accent, fill_opacity=0.08,
                          stroke=t.accent, stroke_opacity=1.0, dash=None),
            "backend": dict(fill="#ffffff" if t.skin == "light" else t.paper_2,
                            fill_opacity=1.0, stroke=t.ink, stroke_opacity=1.0, dash=None),
            "store": dict(fill=t.ink, fill_opacity=0.05,
                          stroke=t.muted, stroke_opacity=1.0, dash=None),
            "external": dict(fill=t.ink, fill_opacity=0.03,
                             stroke=t.ink, stroke_opacity=0.30, dash=None),
            "input": dict(fill=t.muted, fill_opacity=0.10,
                          stroke=t.soft, stroke_opacity=1.0, dash=None),
            "optional": dict(fill=t.ink, fill_opacity=0.02,
                             stroke=t.ink, stroke_opacity=0.20, dash="4,3"),
            "security": dict(fill=t.accent, fill_opacity=0.05,
                             stroke=t.accent, stroke_opacity=0.50, dash="4,4"),
        }
        return dict(table.get(ntype, table["backend"]))

    def edge_style(self, style: str) -> dict:
        """Stroke + arrowhead treatment for a connector style."""
        t = self
        table = {
            "default": dict(stroke=t.muted, width=1.2, dash=None, head="filled"),
            "accent": dict(stroke=t.accent, width=1.2, dash=None, head="filled"),
            "link": dict(stroke=t.link, width=1.2, dash=None, head="filled"),
            "dashed": dict(stroke=t.muted, width=1.0, dash="5,4", head="filled"),
            "async": dict(stroke=t.muted, width=1.0, dash="5,4", head="open"),
            "return": dict(stroke=t.soft, width=1.0, dash="4,3", head="filled"),
        }
        return dict(table.get(style, table["default"]))


def resolve(skin: str = "light", preset: str | None = None, size: str = "standard") -> Tokens:
    """Build the token set for a skin.

    ``skin`` is ``light`` / ``dark`` (the source's two default skins) or
    ``terminal`` (the CLI-chrome alternate). ``preset`` names a canvas size
    class and picks the matching type ramp unless ``size`` overrides it.
    """
    if preset:
        if preset not in PRESETS:
            raise ValueError(
                f"unknown preset {preset!r}; known: {', '.join(sorted(PRESETS))}"
            )
        size = PRESETS[preset][2]
    if size not in RAMP:
        raise ValueError(f"unknown size class {size!r}; known: {', '.join(sorted(RAMP))}")
    if skin in ("light", "dark"):
        base = dict(_DEFAULT_LIGHT if skin == "light" else _DEFAULT_DARK)
    elif skin == "terminal":
        # Fixed alternate skin (the source's CLI-window register).
        base = {
            "paper": "#0a0a0a", "paper_2": "#141414", "ink": "#f5f5f5",
            "muted": "#9a9a9a", "soft": "#5c5c5c", "rule": "#2b2b2b",
            "rule_solid": "#2b2b2b", "accent": "#ff5a36", "link": "#5c5c5c",
        }
    else:
        raise ValueError(f"unknown skin {skin!r}; known: light, dark, terminal")
    return Tokens(skin=skin, ramp=dict(RAMP[size]), **base)

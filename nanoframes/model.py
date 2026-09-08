"""Core data model for a nanoframes composition.

A composition is a single `.nf.svg` document (valid SVG) with:

- root `<svg>` carrying canvas metadata via `data-*` attributes,
- per-element presence/timing via `data-start` / `data-duration` / `data-fade`,
- an embedded `<script type="application/nanoframes+json">` animation timeline.

The model is plain dataclasses so it is free of parser/XML concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
SCRIPT_TYPE = "application/nanoframes+json"


def qname(local: str) -> str:
    """Qualified ElementTree tag for an SVG element name."""
    return f"{{{SVG_NAMESPACE}}}{local}"


# ---------------------------------------------------------------------------
# Animation timeline
# ---------------------------------------------------------------------------


@dataclass
class Keyframe:
    """One key in an animation. ``props`` maps property -> value (opaque; see timeline.py)."""

    t: float
    props: dict[str, Any] = field(default_factory=dict)
    ease: str = "linear"  # linear | ease-in | ease-out | ease-in-out


@dataclass
class Animation:
    """An animated property timeline targeting one CSS selector."""

    target: str  # CSS selector, e.g. "#title" or ".slide"
    keyframes: list[Keyframe] = field(default_factory=list)

    @property
    def sorted(self) -> list[Keyframe]:
        return sorted(self.keyframes, key=lambda k: k.t)


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


@dataclass
class Element:
    """A parsed SVG element plus its clip presence/timing metadata."""

    element_id: str | None
    tag: str
    classes: list[str] = field(default_factory=list)
    track: int = 0
    clip_start: float = 0.0
    clip_duration: float | None = None  # None -> inherit composition duration
    fade_in: float = 0.0
    fade_out: float = 0.0

    def matches(self, selector: str) -> bool:
        """Match a simple CSS selector of the forms ``#id`` or ``.class``."""
        if selector.startswith("#"):
            return self.element_id == selector[1:]
        if selector.startswith("."):
            return selector[1:] in self.classes
        return self.tag == selector


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


@dataclass
class Composition:
    """A parsed nanoframes composition."""

    width: int
    height: int
    fps: int = 30
    duration: float = 1.0
    composition_id: str | None = None
    elements: list[Element] = field(default_factory=list)
    animations: list[Animation] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return max(1, round(self.duration * self.fps))

    def frames(self) -> list[int]:
        """Frame indices 0..frame_count-1 (used for batch rendering)."""
        return list(range(self.frame_count))
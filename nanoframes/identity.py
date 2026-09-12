"""What a frame depends on, in one place.

A frame is a pure function of its inputs, so every input that can move a pixel
has to be an input to the identity the frame cache keys on. Three were missing
and one did not belong:

* **The fonts.** ThorVG shapes glyphs from the faces loaded on the engine, so
  replacing the bundled CJK face moves every advance, every measured chip and
  every wrapped line with it. Left out, a font swap served the frames drawn
  with the old face.
* **The toolchain.** ``thorvg-python`` rasterizes the picture, and the
  package's own modules decide what it is asked to draw. Neither is visible in
  the composition's bytes, so an upgrade — or an edit to ``bake.py`` — used to
  keep serving the previous code's frames.
* **Check-only attributes** (``data-safe-margin``, ``data-palette-budget``).
  These are read by ``lint`` and by nothing that draws, so they must *not* be
  inputs: tuning a budget used to invalidate every frame of the composition
  that declared it, at zero pixel of change.

The identity is a hash over a **canonical projection** of the tree rather than
over the source bytes. Two consequences follow, and both are wanted: a
check-only attribute is not an input, and reindenting a composition no longer
throws its frames away.

Paths inside fingerprints are relative where they can be, because the same
bytes under a different checkout are the same render — an identity recorded on
one machine has to mean something on another.
"""

from __future__ import annotations

import hashlib
import os

from nanoframes import refs
from nanoframes.fonts import DEFAULT_FONT_CANDIDATES
from nanoframes.xmlutil import local_name

# Attributes only a check reads. They are stripped from the projection, so
# editing one cannot change the identity of anything.
CHECK_ONLY_ATTRS = ("data-safe-margin", "data-palette-budget")

# Field separator for the canonical projection. \x1f cannot appear in XML text,
# so a value containing a space cannot be confused with two fields.
_SEP = "\x1f"
_NUL = b"\x00"


def _canonical(node) -> str:
    """Recursive text form of a tree, attrs sorted and check-only ones dropped."""
    tag = local_name(node.tag)
    parts = [tag]
    for key in sorted(node.attrib):
        if local_name(key) in CHECK_ONLY_ATTRS:
            continue
        parts.append(f"{key}={node.attrib[key]}")
    if node.text and node.text.strip():
        parts.append(node.text.strip())
    parts.append("[" + "".join(_canonical(child) for child in node) + "]")
    return _SEP.join(parts)


def projection_hash(root) -> str:
    """Digest of the tree as the render reads it, minus what only a check reads.

    Deterministic under reindentation and attribute reordering, because neither
    changes what is drawn.
    """
    return hashlib.sha256(_canonical(root).encode("utf-8")).hexdigest()


_FONTS: str | None = None
_TOOLCHAIN: str | None = None


def _font_digest(paths) -> str:
    """Digest over the font files that exist, keyed by basename.

    Named by basename rather than by full path so the same face installed in a
    different place hashes the same. A candidate that is absent is skipped: it
    cannot have drawn anything, and a machine without Arial must not claim to be
    one that has it.
    """
    digest = hashlib.sha256()
    for path in paths:
        if not os.path.exists(path):
            continue
        digest.update(os.path.basename(path).encode("utf-8"))
        digest.update(_NUL)
        digest.update(refs.file_digest(path).encode("ascii"))
        digest.update(_NUL)
    return digest.hexdigest()


def font_fingerprint(extra_paths=()) -> str:
    """Digest over the fonts the renderer registers.

    Memoised: the default set is 25 MB on disk and does not change within a
    process, while a render loop asks for the identity once per frame.
    """
    global _FONTS
    if extra_paths:
        return _font_digest(tuple(DEFAULT_FONT_CANDIDATES) + tuple(extra_paths))
    if _FONTS is None:
        _FONTS = _font_digest(DEFAULT_FONT_CANDIDATES)
    return _FONTS


def _package_digest() -> str:
    """Content digest of the package's own modules.

    The renderer is the largest input nobody declares. A version number covers a
    release but not a working tree: editing ``bake.py`` and re-rendering an
    unchanged composition used to serve the previous code's frames, which is a
    wrong picture arriving with no symptom. The package is a few hundred KB, so
    hashing it is cheaper than the text measurement of a single frame.

    It over-invalidates — a docstring edit costs a re-render — and that is the
    direction to err in: a wasted frame is free to reproduce, a stale one is not.
    """
    package = os.path.dirname(os.path.abspath(__file__))
    digest = hashlib.sha256()
    for root, dirs, files in os.walk(package):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            digest.update(os.path.relpath(path, package).encode("utf-8"))
            digest.update(_NUL)
            digest.update(refs.file_digest(path).encode("ascii"))
            digest.update(_NUL)
    return digest.hexdigest()


def toolchain_fingerprint() -> str:
    """What rasterized the frame, and what decided how to ask it.

    ffmpeg is deliberately absent: it muxes after the frames are hashed and
    cannot move a pixel of them. A sound mix is outside the frame identity for
    the same reason.
    """
    global _TOOLCHAIN
    if _TOOLCHAIN is None:
        digest = hashlib.sha256()
        digest.update(f"thorvg-python={dist_version('thorvg-python')}".encode("utf-8"))
        digest.update(_SEP.encode("ascii"))
        from nanoframes import __version__

        digest.update(f"nanoframes={__version__}".encode("utf-8"))
        digest.update(_SEP.encode("ascii"))
        digest.update(_package_digest().encode("ascii"))
        _TOOLCHAIN = digest.hexdigest()
    return _TOOLCHAIN


def dist_version(name: str) -> str:
    """Installed version of a distribution, or a marker when it is not one.

    A source checkout with no distribution metadata is a real state (``pip
    install -e`` variants, a vendored tree), and it must not read as "version
    unknown" and hash the same as every other such state.
    """
    try:
        import importlib.metadata as md

        return md.version(name)
    except Exception:
        return "uninstalled"


def components(root, base_dir: str | None = None) -> dict[str, str]:
    """The named inputs behind one identity.

    Returned so a report can say *which* input moved instead of handing back a
    digest that changed and leaving the reader to bisect their own tree.
    """
    media = refs.media_fingerprint(root, base_dir)
    return {
        "source": projection_hash(root),
        "media": media or "none",
        "fonts": font_fingerprint(),
        "toolchain": toolchain_fingerprint(),
    }


def digest(parts: dict[str, str]) -> str:
    """One digest over named components, order-independent and unambiguous."""
    text = "\n".join(f"{key}={parts[key]}" for key in sorted(parts))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frame_identity(root, base_dir: str | None = None) -> str:
    """The identity a frame cache keys on."""
    return digest(components(root, base_dir))

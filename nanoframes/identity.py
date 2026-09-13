"""What a frame depends on, in one place.

A frame is a pure function of its inputs, so every input that can move a pixel
has to be an input to the identity the frame cache keys on. Three were missing
and one did not belong:

* **The fonts.** ThorVG shapes glyphs from the faces loaded on the engine, so
  replacing the bundled CJK face moves every advance, every measured chip and
  every wrapped line with it. Left out, a font swap served the frames drawn
  with the old face. What is covered is the faces a composition's runs *resolve
  to*, not the faces the machine happens to have — the latter is a property of
  the machine and made every cross-machine comparison read as a font change.
* **The toolchain.** ``thorvg-python`` rasterizes the picture, and the
  package's own modules decide what it is asked to draw. Neither is visible in
  the composition's bytes, so an upgrade — or an edit to ``bake.py`` — used to
  keep serving the previous code's frames. The rasterizer's *build* is in here
  too, not just its version: each platform wheel carries its own libthorvg, and
  that is where a cross-machine pixel difference actually comes from.
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

from nanoframes import fonts, refs
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
_FACE_NAMES: tuple | None = None
_TOOLCHAIN: str | None = None


def _font_digest(paths) -> str:
    """Digest over a set of font files, keyed by basename.

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


def _candidate_names(paths) -> list:
    """``[(path, the font-family values that select it)]`` for the loadable faces.

    Memoised per candidate tuple, because reading a name table opens the font:
    the tuple is the key rather than a flag, so a caller that swaps the
    candidates (a test, a vendored set) gets a fresh table.
    """
    global _FACE_NAMES
    if _FACE_NAMES is None or _FACE_NAMES[0] != tuple(paths):
        _FACE_NAMES = (tuple(paths),
                       [(p, fonts.face_names(p)) for p in paths])
    return _FACE_NAMES[1]


def _resolve_face(family: str, table: list) -> str | None:
    """The font file a ``font-family`` value draws with — the loader's own rule.

    An exact match against the faces that were loaded, else the **first** loaded
    face (docs/composition.md, "Known ThorVG behaviors"). ``family`` empty means
    the run declared none, which is the same miss.
    """
    if family:
        for path, names in table:
            if family in names:
                return path
    return table[0][0] if table else None


def used_faces(root, extra_paths=()) -> tuple[str, ...]:
    """The font files this composition's runs actually draw with, in document order.

    A run's face is *resolved*, not enumerated: the fingerprint used to cover
    every face present on the machine, which differs by construction between two
    machines (macOS ships Arial, Linux ships DejaVu) and so made every
    cross-machine comparison report `fonts changed` whatever the pixels did. What
    can move a pixel here is narrower and machine-independent in the common case:
    when a composition declares no family — or a CSS stack, which matches nothing
    and falls back — every machine draws it with the same bundled face.

    A composition with no `<text>` at all draws no glyphs, so it has no faces and
    a font swap cannot have moved a frame of it.
    """
    paths = [p for p in (*DEFAULT_FONT_CANDIDATES, *extra_paths) if os.path.exists(p)]
    table = _candidate_names(paths)
    faces: list[str] = []
    for node in root.iter():
        if local_name(node.tag) != "text":
            continue
        path = _resolve_face((node.get("font-family") or "").strip(), table)
        if path is not None and path not in faces:
            faces.append(path)
    return tuple(faces)


def font_fingerprint(extra_paths=(), root=None) -> str:
    """Digest over the fonts a render depends on.

    With a tree, that is the faces its runs resolve to (``used_faces``). With no
    tree, it is every loadable candidate — the conservative reading, and what a
    caller asking "what could this machine draw with" wants.

    Memoised for the no-tree case: the default set is tens of MB on disk and does
    not change within a process. The tree case is computed per call, which is
    once per parse, not once per frame.
    """
    global _FONTS
    if root is not None:
        return _font_digest(used_faces(root, extra_paths))
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


def _rasterizer_digest() -> str:
    """Content digest of the rasterizer the installed ``thorvg-python`` carries.

    A version is not a build. Every platform wheel ships its own ``libthorvg-1``
    and ThorVG statically links FreeType, so two machines with the same pinned
    ``thorvg-python`` version rasterize with **different bytes** — which is what
    the cross-architecture run measured, as 9 pixels inside one glyph on
    `text-measure` that no declared input could name. Hashing the library moves
    that difference into the identity, where it reads as `toolchain changed`, a
    diagnosis, instead of arriving as `fonts changed`, which it never was.

    A layout this does not recognise reports which, rather than hashing the same
    as every other unrecognised one.
    """
    try:
        import thorvg_python
    except Exception:
        return "thorvg-python-not-importable"
    root = os.path.dirname(os.path.abspath(thorvg_python.__file__))
    try:
        libraries = sorted(name for name in os.listdir(root)
                           if name.startswith("libthorvg"))
    except OSError:
        return "libthorvg-not-listable"
    if not libraries:
        return "libthorvg-not-found"
    digest = hashlib.sha256()
    for name in libraries:
        digest.update(name.encode("utf-8"))
        digest.update(_NUL)
        digest.update(refs.file_digest(os.path.join(root, name)).encode("ascii"))
        digest.update(_NUL)
    return digest.hexdigest()


def toolchain_fingerprint() -> str:
    """What rasterized the frame, and what decided how to ask it.

    Four inputs: the ``thorvg-python`` version, that package's rasterizer build,
    this package's version, and a digest of this package's own modules.

    ffmpeg is deliberately absent: it muxes after the frames are hashed and
    cannot move a pixel of them. A sound mix is outside the frame identity for
    the same reason. The Python interpreter and Pillow/NumPy are absent too, and
    stay absent: they decode images and measure glyph ink, and everything they
    decide reaches the frame through a value that *is* in the identity or
    through the rasterizer, which is now covered. See docs/determinism.md.
    """
    global _TOOLCHAIN
    if _TOOLCHAIN is None:
        digest = hashlib.sha256()
        digest.update(f"thorvg-python={dist_version('thorvg-python')}".encode("utf-8"))
        digest.update(_SEP.encode("ascii"))
        digest.update(_rasterizer_digest().encode("ascii"))
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
        "fonts": font_fingerprint(root=root),
        "toolchain": toolchain_fingerprint(),
    }


def digest(parts: dict[str, str]) -> str:
    """One digest over named components, order-independent and unambiguous."""
    text = "\n".join(f"{key}={parts[key]}" for key in sorted(parts))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frame_identity(root, base_dir: str | None = None) -> str:
    """The identity a frame cache keys on."""
    return digest(components(root, base_dir))

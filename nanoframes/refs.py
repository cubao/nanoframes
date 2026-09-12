"""Where a composition's external references live, in one place.

Three passes need the same knowledge: ``bake`` dereferences local ``<image>``
hrefs so ThorVG can resolve them, ``lint`` warns about assets that are not
there, and the frame cache folds their *content* into its key. They used to
carry private copies of the attribute names and the "not local" scheme list,
which drifted apart the moment either changed.
"""

from __future__ import annotations

import hashlib
import os

from nanoframes.xmlutil import XLINK_NAMESPACE

# Every attribute an ``<image>`` may carry its source in.
IMAGE_REF_ATTRS = ("href", f"{{{XLINK_NAMESPACE}}}href", "src")

# Schemes a local pass must leave alone (absolute, remote or inlined).
REMOTE_SCHEMES = ("http:", "https:", "data:")

# Streaming read size for content digests — large enough to keep the syscall
# count low on a multi-megabyte asset, small enough to stay off the disk's
# radar for a thumbnail.
_CHUNK = 1 << 20


def iter_images(root):
    """Every ``<image>`` node in a tree (in document order)."""
    from nanoframes.xmlutil import local_name

    for node in root.iter():
        if local_name(node.tag) == "image":
            yield node


def image_ref(node) -> str | None:
    """The source an ``<image>`` node points at, whichever attribute carries it."""
    for attr in IMAGE_REF_ATTRS:
        ref = node.get(attr)
        if ref:
            return ref
    return None


def is_local(ref: str | None) -> bool:
    """Whether a ref names a file this machine can resolve (not a URL or data URI)."""
    return bool(ref) and not ref.startswith(REMOTE_SCHEMES)


def local_image_paths(root, base_dir: str | None) -> list[str]:
    """Absolute paths of every local ``<image>`` source, sorted.

    A relative ref needs ``base_dir``; a string-parsed document has none, so
    its relative refs are unresolvable and simply skipped (an absolute ref
    still resolves). Sorted so the result is a stable cache-key input.
    """
    found = set()
    for node in iter_images(root):
        ref = image_ref(node)
        if not is_local(ref):
            continue
        if os.path.isabs(ref):
            found.add(os.path.normpath(ref))
        elif base_dir:
            found.add(os.path.normpath(os.path.join(base_dir, ref)))
    return sorted(found)


def file_digest(path: str) -> str:
    """Streaming content digest of a file, or a stable marker when it is unreadable."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                digest.update(chunk)
    except OSError:
        return "missing"
    return digest.hexdigest()


def file_label(path: str, base_dir: str | None = None) -> str:
    """How a file is named inside a fingerprint.

    Relative to the composition where it can be: the same asset under a
    different checkout is the same asset, and a digest that moves with the
    operator's home directory is a fact about the operator, not the render.
    An absolute ref outside ``base_dir`` has no shorter name and keeps its own.
    """
    if not base_dir:
        return path
    try:
        rel = os.path.relpath(path, base_dir)
    except ValueError:  # different drive on Windows
        return path
    return path if rel.startswith("..") else rel


def media_fingerprint(root, base_dir: str | None) -> str:
    """Digest over the local media a composition references; ``""`` when it has none.

    A frame is a pure function of the composition *and its assets*, but the
    composition's own bytes say nothing about a referenced PNG: swapping the
    file under an unchanged ``href`` would otherwise serve stale cached frames.
    Folding this into the render identity is what makes an asset edit invalidate
    the frames that drew it.
    """
    paths = local_image_paths(root, base_dir)
    if not paths:
        return ""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(file_label(path, base_dir).encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()

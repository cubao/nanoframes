"""A per-frame digest ledger, so a changed number says *why* it changed.

`tests/snapshots/` already guards the picture: a PNG baseline, compared byte
for byte. What it cannot say is which of two very different events occurred —
the composition changed, or the rasterizer did. Both show up as the same red
test, and the first is a normal edit while the second is a picture that moved
under a composition nobody touched.

This holds the two apart. A ledger entry records the frame digest **and the
identity it was taken under** (`nanoframes.identity`), so a comparison against a
fresh render can name the input that moved:

- the digest differs and ``source``/``media`` differ — the composition changed;
- the digest differs and ``fonts``/``toolchain`` differ — the renderer changed,
  and the same composition would draw the same way on the machine that recorded
  it;
- the digest differs and **every input is identical** — the same declared inputs
  produced different pixels. That is the alarming one, and the reason the ledger
  is keyed this way rather than on the file.

Cross-architecture checking is what this is for and what it cannot do by itself:
digests recorded on macOS/ARM are re-checked by running ``digest --check`` on
another machine, which is work for a CI job this repository does not have yet.
The ledger is the half that can exist locally; `docs/determinism.md` says what
the other half needs.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
from dataclasses import dataclass, field

from nanoframes.parse import Document

LEDGER = os.path.join("tests", "digests.json")

# A full-clip digest is the honest unit: a sample is a subset of the film, and
# an entry that covered three frames must not read as one that covered three
# hundred. Entries record how many frames they saw.
FULL = 0

# JSON is written to be read by a person as well as by `--check`: sorted keys and
# a trailing newline, so a re-record that changed one line diffs as one line.
_INDENT = 2


def frame_digest(image) -> str:
    """SHA-256 of one frame's pixels, taken before any encoder sees them.

    Not the PNG bytes, and not the MP4: those drag in the encoder's build, which
    cannot move a pixel — a Bun upgrade upstream broke 54 PNG goldens whose
    pixels were identical. Mode and size are folded in so a frame that changed
    shape cannot hash as one that merely changed content.
    """
    digest = hashlib.sha256()
    digest.update(f"{image.mode} {image.size[0]}x{image.size[1]}".encode("ascii"))
    digest.update(b"\0")
    digest.update(image.tobytes())
    return digest.hexdigest()


def sequence_digest(hashes: list[str]) -> str:
    """One digest over an ordered frame sequence.

    Frame order is part of the identity of a film, so the hashes are joined in
    order rather than sorted. An empty sequence hashes as the empty string's
    digest, which is a real answer for a zero-frame composition and is why the
    caller records a frame count beside it.
    """
    return hashlib.sha256("\n".join(hashes).encode("ascii")).hexdigest()


@dataclass
class Reading:
    """A composition's digest, and what it was taken under."""

    frames: int
    digest: str
    identity: dict[str, str] = field(default_factory=dict)
    sampled: bool = False

    def to_dict(self) -> dict:
        return {
            "frames": self.frames,
            "digest": self.digest,
            "sampled": self.sampled,
            "identity": dict(sorted(self.identity.items())),
        }


def read(doc: Document, *, samples: int = FULL, threads: int = 4,
         render=None) -> Reading:
    """Render the clip and digest every frame (or ``samples`` of them).

    ``samples`` of 0 means every frame. A sampled reading is marked ``sampled``
    so a fast check can never be mistaken in the ledger for a full one.
    """
    from nanoframes.render import render_frame
    from nanoframes.timeline import sample_times

    comp = doc.composition
    if samples and samples < comp.frame_count:
        times = sample_times(comp, cap=samples)
        sampled = True
    else:
        times = [i / comp.fps for i in range(comp.frame_count)]
        sampled = False

    hashes = []
    for t in times:
        owner = render or render_frame
        hashes.append(frame_digest(owner(doc, t, cache=None, threads=threads, warn_blank=False)))
    return Reading(frames=len(hashes), digest=sequence_digest(hashes),
                   identity=doc.identity_components(), sampled=sampled)


def load(path: str = LEDGER) -> dict:
    """The ledger as recorded, or an empty one when there is no file yet."""
    if not os.path.exists(path):
        return {"version": 1, "compositions": {}}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("compositions", {})
    return data


def save(path: str, ledger: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=_INDENT, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def entry_key(path: str, root: str | None = None) -> str:
    """How a composition is named in the ledger: relative, so it is portable."""
    if root:
        try:
            rel = os.path.relpath(os.path.abspath(path), root)
            if not rel.startswith(".."):
                return rel
        except ValueError:
            pass
    return path


def compare(recorded: dict, fresh: Reading) -> tuple[str, list[str]]:
    """``(status, reasons)`` for a fresh reading against a recorded entry.

    The status is what a caller branches on; the reasons are what a person
    reads. "changed" is not a synonym for "wrong" — an edited composition is
    supposed to move the number, and the point of comparing the recorded inputs
    is to say so rather than leave the reader to diff their own tree.
    """
    if recorded.get("digest") == fresh.digest:
        return "match", []
    reasons = []
    for key in ("source", "media", "fonts", "toolchain"):
        was = (recorded.get("identity") or {}).get(key)
        now = fresh.identity.get(key)
        if was is not None and now is not None and was != now:
            reasons.append(f"{key} changed")
    if not reasons:
        reasons.append("every declared input is identical, so the same inputs"
                       " produced a different frame")
    if recorded.get("frames") != fresh.frames:
        reasons.append(f"frame count changed: {recorded.get('frames')} -> {fresh.frames}")
    status = "regression" if reasons and reasons[0].startswith("every declared") else "changed"
    return status, reasons


def sweep(pattern: str = os.path.join("examples", "*.nf.svg")) -> list[str]:
    """Every composition a sweep covers, in a stable order."""
    return sorted(glob.glob(pattern))

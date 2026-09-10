"""Regenerate the visual snapshot baselines in ``tests/snapshots/``.

Run from a repository checkout::

    python3 -m nanoframes.scripts.snapshots

Every ``<stem>_t<time>.png`` baseline is re-rendered from
``examples/<stem>.svg`` at ``<time>``. Baselines are the visual regression net
for intentional changes: render the clip, look at it, then regenerate — never
regenerate to make a failure go away.
"""

from __future__ import annotations

import os
import re
import sys

_PATTERN = re.compile(r"^(?P<stem>.+?)_t(?P<t>[0-9.]+)\.png$")


def repo_root(start: str | None = None) -> str | None:
    """Walk up from ``start`` to a checkout containing examples/ and tests/snapshots/."""
    current = os.path.abspath(start or os.getcwd())
    while True:
        if (os.path.isdir(os.path.join(current, "examples"))
                and os.path.isdir(os.path.join(current, "tests", "snapshots"))):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def main(argv: list[str] | None = None) -> int:
    root = repo_root()
    if root is None:
        print("snapshots: no repo checkout here (need examples/ and tests/snapshots/)",
              file=sys.stderr)
        return 2

    sys.path.insert(0, root)
    from nanoframes.parse import parse_file
    from nanoframes.render import render_frame

    snapshot_dir = os.path.join(root, "tests", "snapshots")
    written = 0
    for name in sorted(os.listdir(snapshot_dir)):
        match = _PATTERN.match(name)
        if not match:
            continue
        comp = os.path.join(root, "examples", match.group("stem") + ".svg")
        if not os.path.exists(comp):
            print(f"snapshots: no composition for {name} (expected {comp})", file=sys.stderr)
            return 2
        t = float(match.group("t"))
        dst = os.path.join(snapshot_dir, name)
        render_frame(parse_file(comp), t, out_path=dst)
        written += 1
        print(f"wrote {os.path.relpath(dst, root)}")
    print(f"snapshots: {written} baseline(s) regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

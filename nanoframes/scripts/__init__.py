"""Regenerate the visual snapshot baselines.

Usage:
    python3 -m nanoframes.scripts.snapshots           # all examples at fixed times
    python3 -m nanoframes.scripts.snapshots --times 0.2 2.5

Run this after an intentional visual change so test_snapshots.py sees the new
expected output.
"""

from __future__ import annotations

import argparse
import os
import sys

from nanoframes.parse import parse_file
from nanoframes.render import render_frame

DEFAULT_TIMES = (0.1, 1.0, 2.0, 3.5)
SNAPSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tests",
    "snapshots",
)
EXAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "examples",
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="regenerate nanoframes snapshot baselines")
    p.add_argument("--times", type=float, nargs="*", default=None,
                   help="times (seconds) to render per example (default %s)" % (DEFAULT_TIMES,))
    p.add_argument("comps", nargs="*", default=None, help="specific compositions under examples/")
    args = p.parse_args(argv)

    times = args.times or list(DEFAULT_TIMES)
    if args.comps:
        comps = [c if os.path.isabs(c) else os.path.join(EXAMPLES, c) for c in args.comps]
    elif not os.path.isdir(EXAMPLES):
        print("no examples/ next to this install — snapshot baselines are a "
              "repo-checkout tool", file=sys.stderr)
        comps = []
    else:
        comps = sorted(
            os.path.join(EXAMPLES, f) for f in os.listdir(EXAMPLES)
            if f.endswith(".nf.svg")
        )

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    wrote = 0
    for comp in comps:
        if not os.path.exists(comp):
            print(f"skip missing: {comp}", file=sys.stderr)
            continue
        doc = parse_file(comp)
        stem = os.path.splitext(os.path.basename(comp))[0]
        for t in times:
            dst = os.path.join(SNAPSHOT_DIR, f"{stem}_t{t:g}.png")
            render_frame(doc, t=t, out_path=dst)
            wrote += 1
            print("wrote", dst)
    print(f"regenerated {wrote} snapshots -> {SNAPSHOT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

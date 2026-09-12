"""Visual snapshot regression tests.

Each baseline PNG in ``tests/snapshots/`` is a committed render of an example
composition at a specific time. If a render stops matching its baseline (or one
is missing), the test fails -- preventing silent visual regressions.

Regenerate baselines after an intentional visual change:
    python3 -m nanoframes.scripts.snapshots
"""

import os
import re

import pytest

from nanoframes.parse import parse_file
from nanoframes.render import render_frame

SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")

_PATTERN = re.compile(r"^(?P<stem>.+?)_t(?P<t>[0-9.]+)\.png$")


def _cases():
    cases = []
    if not os.path.isdir(SNAPSHOT_DIR):
        return cases
    for fname in sorted(os.listdir(SNAPSHOT_DIR)):
        m = _PATTERN.match(fname)
        if not m:
            continue
        comp = os.path.join(EXAMPLES_DIR, m.group("stem") + ".svg")
        if not os.path.exists(comp):
            continue
        cases.append((comp, float(m.group("t")), os.path.join(SNAPSHOT_DIR, fname)))
    return cases


CASES = _cases()


@pytest.mark.parametrize("comp,t,baseline", CASES, ids=[os.path.basename(b) for _, _, b in CASES])
def test_snapshot_matches_baseline(comp, t, baseline):
    from PIL import Image

    doc = parse_file(comp)
    img = render_frame(doc, t=t).convert("RGB")
    ref = Image.open(baseline).convert("RGB")
    assert img.size == ref.size, f"size mismatch for {os.path.basename(baseline)}"
    assert img.tobytes() == ref.tobytes(), (
        f"visual regression: {os.path.basename(baseline)} (t={t}); regenerate "
        f"baselines with `python3 -m nanoframes.scripts.snapshots` if intentional"
    )


def test_snapshot_baselines_exist():
    assert CASES, "no snapshot baselines found under tests/snapshots/"

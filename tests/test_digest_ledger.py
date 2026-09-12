"""The committed ledger's shape — cheap, and separate from running it.

`digest --all --check` is the real determinism gate: it renders every example and
compares. It is a ledger operation (seconds, and it re-renders 750 frames), so it
is not run by `pytest`; `docs/determinism.md` says so and says why.

What *is* cheap is the part of the invariant a rendering run cannot express: a
composition with no ledger entry is not "passing", it is unmeasured, and a
ledger entry for a file that no longer exists hides that. There is no CI here
yet, so this file is the only thing standing between the ledger and quiet decay.
"""

import glob
import json
import os

import pytest

from nanoframes import digest as digest_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, digest_mod.LEDGER)
EXAMPLES = os.path.join(ROOT, "examples", "*.nf.svg")


@pytest.fixture(scope="module")
def ledger():
    if not os.path.exists(LEDGER):
        pytest.skip(f"no ledger at {LEDGER}; record one with `nanoframes digest --all --record`")
    with open(LEDGER, encoding="utf-8") as fh:
        return json.load(fh)


def _examples():
    return sorted(os.path.relpath(p, ROOT) for p in glob.glob(EXAMPLES))


def test_every_example_is_measured(ledger):
    """An unmeasured composition is not a passing one."""
    missing = [name for name in _examples() if name not in ledger["compositions"]]
    assert not missing, (
        f"no digest recorded for {missing} — run `nanoframes digest --all --record`")


def test_no_entry_outlives_the_file_it_measured(ledger):
    """An orphan entry keeps a stale number on the books."""
    orphans = [name for name in ledger["compositions"] if not os.path.exists(os.path.join(ROOT, name))]
    assert not orphans, f"ledger entries with no composition: {orphans}"


def test_every_entry_carries_the_identity_it_was_taken_under(ledger):
    """Without the inputs, a changed digest cannot say which side moved."""
    for name, entry in ledger["compositions"].items():
        assert set(entry) >= {"digest", "frames", "sampled", "identity"}, name
        assert len(entry["digest"]) == 64, name
        assert entry["frames"] > 0, name
        assert set(entry["identity"]) == {"source", "media", "fonts", "toolchain"}, name


def test_the_ledger_was_recorded_in_one_pass(ledger):
    """Every entry shares one toolchain, so the ledger has a single expiry date.

    Re-recording one composition after the renderer moved would leave the ledger
    mixing two toolchains, where a `--check` verdict depends on which entry the
    reader happened to look at. Freshness itself is not asserted here: a code
    edit legitimately moves the toolchain, and `digest --all --check` reports
    exactly that as `changed — toolchain changed`. A gate that is red from the
    day it lands is not a gate.
    """
    toolchains = {entry["identity"]["toolchain"] for entry in ledger["compositions"].values()}
    assert len(toolchains) == 1, (
        f"the ledger mixes {len(toolchains)} toolchains; re-record it in one pass with"
        f" `nanoframes digest --all --record`")

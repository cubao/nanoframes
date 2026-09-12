"""The digest ledger: a changed number has to say which input moved.

A PNG baseline answers "is the picture the same". It cannot answer "and if not,
was that me or the tool", which is the question a digest that moved actually
raises. These tests are mostly about that distinction — the three outcomes have
to be distinguishable, and the alarming one has to be unmistakable.
"""

import contextlib
import io
import json
import os

import pytest
from PIL import Image

from nanoframes import digest as digest_mod
from nanoframes.cli import main
from nanoframes.parse import parse_string

TINY = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="64" data-height="36"'
        ' data-fps="10" data-duration="0.3">'
        '<rect id="r" width="64" height="36" fill="#101820"/></svg>')


def _src(tmp_path, text=TINY, name="c.nf.svg"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _img(color=(255, 0, 0, 255), size=(4, 4)):
    return Image.new("RGBA", size, color)


# --- the primitives ---------------------------------------------------------

def test_frame_digest_is_stable_and_pixel_sensitive():
    assert digest_mod.frame_digest(_img()) == digest_mod.frame_digest(_img())
    other = digest_mod.frame_digest(_img(color=(0, 0, 255, 255)))
    assert other != digest_mod.frame_digest(_img())


def test_frame_digest_covers_shape_and_mode():
    """A frame that changed shape must not hash as one that changed content."""
    assert digest_mod.frame_digest(_img(size=(4, 4))) != digest_mod.frame_digest(_img(size=(8, 2)))
    assert digest_mod.frame_digest(_img()) != digest_mod.frame_digest(_img().convert("RGB"))


def test_sequence_digest_is_order_sensitive():
    """Frame order is part of a film's identity, so it cannot be sorted away."""
    a, b = "aa", "bb"
    assert digest_mod.sequence_digest([a, b]) != digest_mod.sequence_digest([b, a])
    assert digest_mod.sequence_digest([a, b]) == digest_mod.sequence_digest([a, b])


# --- reading ----------------------------------------------------------------

def test_a_reading_covers_every_frame_by_default():
    doc = parse_string(TINY)
    reading = digest_mod.read(doc)
    assert reading.frames == 3 and not reading.sampled
    assert reading.identity["source"]


def test_a_sampled_reading_says_so():
    """A three-frame sample must never read as a whole-film guarantee."""
    doc = parse_string(TINY)
    reading = digest_mod.read(doc, samples=2)
    assert reading.frames == 2 and reading.sampled


def test_the_reading_carries_the_identity_it_was_taken_under():
    reading = digest_mod.read(parse_string(TINY))
    assert set(reading.identity) == {"source", "media", "fonts", "toolchain"}


# --- comparing --------------------------------------------------------------

def test_an_unchanged_composition_matches():
    reading = digest_mod.read(parse_string(TINY))
    assert digest_mod.compare(reading.to_dict(), reading) == ("match", [])


def test_an_edited_composition_reports_that_it_changed():
    """An edit is supposed to move the number; say which input moved."""
    before = digest_mod.read(parse_string(TINY))
    after = digest_mod.read(parse_string(TINY.replace("#101820", "#ff0000")))
    status, reasons = digest_mod.compare(before.to_dict(), after)
    assert status == "changed"
    assert reasons == ["source changed"]


def test_a_renderer_change_is_not_reported_as_a_regression():
    """The whole reason the entry records its inputs."""
    fresh = digest_mod.read(parse_string(TINY))
    recorded = fresh.to_dict() | {"digest": "0" * 64}
    recorded["identity"] = dict(fresh.identity, toolchain="deadbeef")
    status, reasons = digest_mod.compare(recorded, fresh)
    assert status == "changed"
    assert reasons == ["toolchain changed"]


def test_a_font_swap_is_reported_as_a_font_change():
    fresh = digest_mod.read(parse_string(TINY))
    recorded = fresh.to_dict() | {"digest": "0" * 64}
    recorded["identity"] = dict(fresh.identity, fonts="deadbeef")
    status, reasons = digest_mod.compare(recorded, fresh)
    assert status == "changed" and reasons == ["fonts changed"]


def test_identical_inputs_with_different_pixels_is_the_alarming_case():
    """Same declared inputs, different picture. That is what the ledger is for."""
    fresh = digest_mod.read(parse_string(TINY))
    recorded = fresh.to_dict() | {"digest": "0" * 64}
    status, reasons = digest_mod.compare(recorded, fresh)
    assert status == "regression"
    assert "identical" in reasons[0] and "different frame" in reasons[0]


def test_a_changed_frame_count_is_named_even_when_an_input_moved_too():
    fresh = digest_mod.read(parse_string(TINY))
    recorded = fresh.to_dict() | {"digest": "0" * 64, "frames": 99}
    recorded["identity"] = dict(fresh.identity, source="deadbeef")
    _, reasons = digest_mod.compare(recorded, fresh)
    assert reasons == ["source changed", "frame count changed: 99 -> 3"]


# --- the ledger -------------------------------------------------------------

def test_a_missing_ledger_reads_as_empty_rather_than_failing(tmp_path):
    assert digest_mod.load(str(tmp_path / "nope.json"))["compositions"] == {}


def test_entries_are_named_relative_to_the_root_so_the_ledger_is_portable(tmp_path):
    inside = str(tmp_path / "examples" / "a.nf.svg")
    assert digest_mod.entry_key(inside, str(tmp_path)) == os.path.join("examples", "a.nf.svg")
    outside = str(tmp_path.parent / "elsewhere" / "a.nf.svg")
    assert digest_mod.entry_key(outside, str(tmp_path)) == outside


def test_save_writes_sorted_json_a_person_can_diff(tmp_path):
    path = str(tmp_path / "ledger.json")
    digest_mod.save(path, {"version": 1, "compositions": {"b": {"digest": "x"},
                                                          "a": {"digest": "y"}}})
    text = open(path, encoding="utf-8").read()
    assert text.endswith("\n")
    assert list(json.loads(text)["compositions"]) == ["a", "b"]


# --- the command ------------------------------------------------------------

def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


def test_cli_records_then_checks_a_match(tmp_path):
    src = _src(tmp_path)
    ledger = str(tmp_path / "ledger.json")
    code, text = _run(["digest", src, "--record", "--ledger", ledger])
    assert code == 0 and "recorded" in text

    code, text = _run(["digest", src, "--check", "--ledger", ledger])
    assert code == 0 and text.startswith("ok")


def test_cli_check_fails_after_an_edit_and_says_why(tmp_path):
    src = _src(tmp_path)
    ledger = str(tmp_path / "ledger.json")
    _run(["digest", src, "--record", "--ledger", ledger])

    open(src, "w", encoding="utf-8").write(TINY.replace("#101820", "#ff0000"))
    code, text = _run(["digest", src, "--check", "--ledger", ledger])
    assert code == 1
    assert "CHANGED" in text and "source changed" in text


def test_cli_reports_an_unrecorded_composition_without_calling_it_wrong(tmp_path):
    """Unrecorded is not a verdict; `--check` has nothing to compare against."""
    src = _src(tmp_path)
    code, text = _run(["digest", src, "--check", "--ledger", str(tmp_path / "none.json")])
    assert code == 0
    assert "not in" in text


def test_cli_json_always_exits_zero(tmp_path):
    src = _src(tmp_path)
    ledger = str(tmp_path / "ledger.json")
    _run(["digest", src, "--record", "--ledger", ledger])
    open(src, "w", encoding="utf-8").write(TINY.replace("#101820", "#ff0000"))

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["digest", src, "--check", "--ledger", ledger, "--json"])
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    # `entry_key` keeps a path outside the checkout absolute rather than
    # inventing a ../.. name for it.
    entry = payload["compositions"][src]
    assert entry["status"] == "changed" and entry["reasons"] == ["source changed"]


def test_cli_digest_needs_a_target(tmp_path):
    code, _ = _run(["digest", "--ledger", str(tmp_path / "l.json")])
    assert code == 2


def test_cli_digest_reports_a_missing_file_as_a_usage_error(tmp_path):
    code, _ = _run(["digest", str(tmp_path / "nope.nf.svg")])
    assert code == 2


def test_cli_all_sweeps_the_examples_glob(tmp_path):
    (tmp_path / "examples").mkdir()
    for name in ("a", "b"):
        (tmp_path / "examples" / f"{name}.nf.svg").write_text(TINY, encoding="utf-8")
    ledger = str(tmp_path / "ledger.json")
    code, text = _run(["digest", "--all", "--examples", str(tmp_path / "examples" / "*.nf.svg"),
                       "--record", "--ledger", ledger])
    assert code == 0
    assert len(json.loads(open(ledger, encoding="utf-8").read())["compositions"]) == 2


def test_the_default_ledger_lives_at_the_checkout_root():
    from nanoframes.cli import digest_default_ledger
    from nanoframes.envelope import repo_root

    root = repo_root()
    if root:
        assert digest_default_ledger().startswith(root)


@pytest.mark.parametrize("bad", ["<svg", ""])
def test_cli_digest_treats_an_unparseable_composition_as_a_usage_error(tmp_path, bad):
    src = _src(tmp_path, bad, name="bad.nf.svg")
    code, _ = _run(["digest", src])
    assert code == 2

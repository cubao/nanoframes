"""The `--json` contract: one object, redacted paths, a run id, three exit codes.

Each of these is a rule a reader branches on. They are cheap to state and were
each violated by at least one command before they had a home.
"""

import io
import json
import os

from nanoframes import envelope


def test_exit_codes_are_three_distinct_events():
    assert (envelope.EXIT_OK, envelope.EXIT_FAIL, envelope.EXIT_USAGE) == (0, 1, 2)


def test_redact_replaces_the_checkout_and_the_home_directory(tmp_path, windows_agnostic=""):
    root = str(tmp_path)
    home = str(tmp_path.parent)
    payload = {
        "under_root": f"{root}/examples/a.nf.svg",
        "under_home": f"{home}/.config/thing",
        "elsewhere": "/opt/homebrew/bin/ffmpeg",
        "nested": [{"path": f"{root}/x"}],
    }
    out = envelope.redact(payload, root=root, home=home)
    assert out["under_root"] == "$REPO/examples/a.nf.svg"
    assert out["under_home"] == "$HOME/.config/thing"
    assert out["elsewhere"] == "/opt/homebrew/bin/ffmpeg", "not ours to rewrite"
    assert out["nested"][0]["path"] == "$REPO/x"


def test_the_checkout_wins_over_the_home_directory(tmp_path):
    """A checkout almost always sits under home; home-first loses the better answer."""
    root = os.path.join(str(tmp_path), "code", "nanoframes")
    out = envelope.redact({"p": f"{root}/out.png"}, root=root, home=str(tmp_path))
    assert out["p"] == "$REPO/out.png"


def test_redact_reaches_into_keys_too():
    out = envelope.redact({"/home/someone/repo": 1}, root="/home/someone/repo", home="/home/someone")
    assert out == {"$REPO": 1}


def test_redact_leaves_non_strings_alone():
    out = envelope.redact({"n": 3, "ok": True, "none": None, "f": 1.5}, root="/r", home="/h")
    assert out == {"n": 3, "ok": True, "none": None, "f": 1.5}


def test_emit_writes_exactly_one_object_and_echoes_the_run_id(monkeypatch):
    monkeypatch.setenv(envelope.RUN_ID_ENV, "turn-7")
    out = io.StringIO()
    envelope.emit({"ok": True, "n": 1}, stream=out)
    text = out.getvalue()
    assert text.endswith("\n") and text.count("\n") == 1, "one object, one line"
    assert json.loads(text) == {"ok": True, "n": 1, "runId": "turn-7"}


def test_emit_omits_the_run_id_when_the_caller_did_not_set_one(monkeypatch):
    monkeypatch.delenv(envelope.RUN_ID_ENV, raising=False)
    out = io.StringIO()
    envelope.emit({"ok": True}, stream=out)
    assert "runId" not in json.loads(out.getvalue())


def test_emit_does_not_overwrite_a_payload_that_carries_its_own_run_id(monkeypatch):
    monkeypatch.setenv(envelope.RUN_ID_ENV, "from-the-environment")
    out = io.StringIO()
    envelope.emit({"ok": True, "runId": "explicit"}, stream=out)
    assert json.loads(out.getvalue())["runId"] == "explicit"


def test_emit_flushes(monkeypatch):
    """A truncated envelope only shows up under a pipe, which is where agents read."""
    flushed = []
    stream = io.StringIO()
    monkeypatch.setattr(stream, "flush", lambda: flushed.append(True))
    envelope.emit({"ok": True}, stream=stream)
    assert flushed == [True]

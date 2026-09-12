"""`nanoframes doctor`: the preconditions, and what each failure tells you to run.

The contract that matters is not that the checks pass on a working machine — it
is that a *failing* check is actionable. An unmet precondition that reports only
what is wrong sends the reader to guess at five things; each one has to name the
command that fixes it.
"""

import contextlib
import io
import json

from nanoframes import doctor
from nanoframes.cli import main


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_report_covers_the_preconditions_that_can_bite():
    report = doctor.report()
    assert [c.name for c in report.checks] == ["thorvg", "ffmpeg", "ffprobe", "fonts", "disk"]


def test_every_failing_check_names_a_fix(monkeypatch):
    """The whole point of the command. Force every failure and read the fixes."""
    monkeypatch.setattr(doctor, "has_tool", lambda name: False)
    monkeypatch.setattr(doctor.identity, "dist_version", lambda name: "1.0.0")
    monkeypatch.setattr(doctor, "DEFAULT_FONT_CANDIDATES", ("/nonexistent/face.ttf",))
    monkeypatch.setattr(doctor, "TIGHT_DISK_BYTES", 1 << 62)
    monkeypatch.setattr(doctor.shutil, "disk_usage",
                        lambda path: type("U", (), {"free": 1})(), raising=True)

    report = doctor.report()
    assert not report.ok
    assert len(report.failed) == 5
    for check in report.failed:
        assert check.fix, f"{check.name} failed without naming a fix"
        assert "\n" not in check.fix, "a fix has to be one pasteable line"


def test_thorvg_below_the_floor_is_a_failure(monkeypatch):
    monkeypatch.setattr(doctor.identity, "dist_version", lambda name: "1.1.2")
    check = doctor.check_thorvg()
    assert not check.ok
    assert "1.1.3" in check.detail and "thorvg-python" in check.fix


def test_thorvg_at_or_above_the_floor_passes(monkeypatch):
    monkeypatch.setattr(doctor.identity, "dist_version", lambda name: "1.2.0")
    assert doctor.check_thorvg().ok


def test_a_source_install_is_not_reported_as_a_failure(monkeypatch):
    """A vendored install has no distribution metadata, which is not a fault."""
    monkeypatch.setattr(doctor.identity, "dist_version", lambda name: "uninstalled")
    check = doctor.check_thorvg()
    assert check.ok and "unverified" in check.detail


def test_missing_bundled_face_still_passes_when_a_system_face_exists(monkeypatch, tmp_path):
    """A system face being absent is a fact about the machine, not a fault.

    The one case worth reporting is a host with *no* loadable face at all, where
    `<text>` silently draws nothing.
    """
    system = tmp_path / "Arial.ttf"
    system.write_bytes(b"x")
    monkeypatch.setattr(doctor, "DEFAULT_FONT_CANDIDATES", (str(system), str(tmp_path / "gone.ttf")))
    check = doctor.check_fonts()
    assert check.ok
    assert "bundled CJK face" in check.detail and check.fix


def test_no_face_at_all_is_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "DEFAULT_FONT_CANDIDATES", (str(tmp_path / "gone.ttf"),))
    check = doctor.check_fonts()
    assert not check.ok
    assert "reinstall" in check.fix


def test_tight_disk_names_the_cache_as_the_thing_to_reclaim(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "disk_usage",
                        lambda path: type("U", (), {"free": 1024})())
    check = doctor.check_disk(".nanoframes-cache")
    assert not check.ok
    assert check.fix == "nanoframes cache --clear"


def test_json_exits_zero_even_when_a_check_fails(monkeypatch):
    """A non-zero exit makes a shell pipeline discard the payload."""
    monkeypatch.setattr(doctor, "has_tool", lambda name: False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["doctor", "--json"])
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    assert payload["failed"] == ["ffmpeg", "ffprobe"]
    assert all(set(c) == {"name", "ok", "detail", "fix"} for c in payload["checks"])


def test_human_mode_exits_one_when_a_check_fails(monkeypatch):
    monkeypatch.setattr(doctor, "has_tool", lambda name: False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["doctor"])
    assert code == 1
    text = out.getvalue()
    assert "FAIL ffmpeg" in text
    assert "fix: " in text


def test_human_mode_exits_zero_on_a_working_machine():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["doctor"])
    if doctor.report().ok:
        assert code == 0
        assert "Every precondition is satisfied" in out.getvalue()

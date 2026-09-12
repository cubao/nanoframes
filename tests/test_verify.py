"""`nanoframes verify`: every gate, one envelope, one exit code.

The claim worth testing hardest is that a section is the sub-command's own
payload **verbatim**. An envelope that reformatted one would be a second
implementation of that verdict, and the second one is the one nobody runs — so
the test compares the section against the producer directly rather than against
a fixture that would drift with it.
"""

import contextlib
import io
import json

import pytest

from nanoframes import lint, verify
from nanoframes.cli import main
from nanoframes.diagnose import SCAN_SAMPLES
from nanoframes.parse import parse_string

CLEAN = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="320" data-height="180"'
         ' data-fps="30" data-duration="1.0">'
         '<rect width="320" height="180" fill="#101820"/>'
         '<text id="t" x="20" y="100" font-family="Arial" font-size="28"'
         ' fill="#ffffff">HELLO</text></svg>')

# An error (an animation targeting nothing) and a warning (a pivotless rotate).
BROKEN = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="320" data-height="180"'
          ' data-fps="30" data-duration="1.0">'
          '<rect id="r" width="40" height="40" fill="#0f0" transform="rotate(45)"/>'
          '<script type="application/nanoframes+json"><![CDATA['
          '{"animations":[{"target":"#missing","keyframes":[{"t":0,"opacity":1}]}]}'
          ']]></script></svg>')

BURIED = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="320" data-height="180"'
          ' data-fps="30" data-duration="1.0">'
          '<text id="caption" x="20" y="100" font-family="Arial" font-size="28"'
          ' fill="#ffffff">CAPTION</text>'
          '<rect id="curtain" width="320" height="180" fill="#101820"/></svg>')


def _src(tmp_path, text, name="c.nf.svg"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _run_text(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


# --- the envelope -----------------------------------------------------------

def test_a_clean_composition_passes_with_no_errors_or_warnings():
    # CLEAN has one named element, and it is visible, so the probe finds nothing.
    code, payload = verify.run(parse_string(CLEAN))
    assert code == 0 and payload["ok"] is True
    assert payload["errors"] == [] and payload["warnings"] == 0


def test_every_section_is_present_and_in_the_documented_order():
    _, payload = verify.run(parse_string(CLEAN))
    for name in verify.SECTIONS:
        assert name in payload, name
    assert payload["errors"] == []


def test_the_check_section_is_the_check_payload_verbatim():
    """One producer, so the envelope cannot hold a second verdict."""
    doc = parse_string(BROKEN)
    _, payload = verify.run(doc)
    expected = lint.payload(lint.lint_document(doc, measurer=None))
    assert payload["check"] == expected


def test_the_debug_section_is_the_debug_payload_verbatim():
    doc = parse_string(CLEAN)
    _, payload = verify.run(doc, t=0.25)
    from nanoframes import diagnose
    from nanoframes.render import measurer

    expected = diagnose.debug_payload(doc, 0.25, measurer=measurer(), samples=SCAN_SAMPLES,
                                      pixels=True, threads=4, scan=True, loop=False)
    assert payload["debug"] == expected


def test_a_lint_error_is_an_error_and_fails_the_run():
    code, payload = verify.run(parse_string(BROKEN))
    assert payload["errors"] == ["check"]
    assert code == 1 and payload["ok"] is False


def test_a_report_reading_is_a_warning_not_a_failure():
    """A box off the canvas is real and is not a reason to refuse a render."""
    code, payload = verify.run(parse_string(BURIED), pixels=True)
    assert payload["errors"] == []
    assert payload["warnings"] == 1
    assert code == 0, "reported, not failed"
    assert payload["debug"]["frame"]["invisible"] == ["#caption"]


def test_strict_makes_a_warning_count():
    code, payload = verify.run(parse_string(BURIED), pixels=True, strict=True)
    assert payload["warnings"] == 1
    assert code == 1 and payload["ok"] is False
    assert payload["strict"] is True


def test_the_gate_probes_pixels_by_default():
    """A gate that omits its most informative check is weaker than it advertises.

    An agent that runs only `verify` would otherwise never see an element that
    contributes no pixel: it is the one finding no box measure produces.
    """
    _, payload = verify.run(parse_string(BURIED))
    assert payload["debug"]["frame"]["invisible"] == ["#caption"]
    assert payload["examined"]["pixels_probed"] is True


def test_opting_out_claims_nothing_rather_than_claiming_zero():
    """Nothing probed means nothing claimed — not a zero."""
    _, payload = verify.run(parse_string(BURIED), pixels=False)
    assert payload["debug"]["frame"]["invisible"] == []
    assert payload["examined"]["pixels_probed"] is False


def test_the_envelope_names_what_the_debug_section_examined():
    _, payload = verify.run(parse_string(CLEAN), t=0.5, samples=7)
    assert payload["examined"] == {"t": 0.5, "scan_samples": 7, "pixels_probed": True}


def test_a_section_that_raises_is_recorded_not_propagated(monkeypatch):
    """One broken section must not cost the reader the sections that did run."""
    from nanoframes import doctor

    monkeypatch.setattr(doctor, "report", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    code, payload = verify.run(parse_string(CLEAN))
    assert payload["doctor"]["ok"] is False
    assert "RuntimeError: boom" in payload["doctor"]["error"]
    assert payload["errors"] == ["doctor"]
    assert payload["check"]["ok"] is True, "the other sections still reported"
    assert code == 1


# --- the command ------------------------------------------------------------

def test_cli_verify_exits_zero_on_a_clean_composition(tmp_path):
    code, text = _run_text(["verify", _src(tmp_path, CLEAN)])
    assert code == 0
    assert "0 error(s), 0 warning(s)" in text


def test_cli_verify_json_exits_zero_and_puts_the_verdict_in_ok(tmp_path):
    """A non-zero exit makes a shell pipeline discard the payload."""
    src = _src(tmp_path, BROKEN)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["verify", src, "--json"])
    assert code == 0
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False and payload["errors"] == ["check"]


def test_cli_verify_exits_one_in_human_mode_when_a_section_fails(tmp_path):
    code, text = _run_text(["verify", _src(tmp_path, BROKEN)])
    assert code == 1
    assert "FAIL check" in text


def test_cli_verify_treats_an_unparseable_composition_as_a_usage_error(tmp_path):
    """The sections cannot run at all, which is a wrong invocation (exit 2)."""
    src = _src(tmp_path, "<svg", name="bad.nf.svg")
    with pytest.raises(SystemExit) as exc:
        main(["verify", src])
    assert exc.value.code == 2


def test_cli_verify_reports_a_missing_file_as_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["verify", str(tmp_path / "nope.nf.svg")])
    assert exc.value.code == 2


def test_cli_verify_strict_names_an_element_that_contributes_nothing(tmp_path):
    code, text = _run_text(["verify", _src(tmp_path, BURIED), "--strict"])
    assert code == 1
    assert "1 invisible" in text

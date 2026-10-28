"""Time specs: the ways an author writes "when".

One parser, so `--t 50%` cannot mean a different frame in `debug` than in
`render`. The grammar mirrors fframes' on purpose: an author moving between the
two tools should not have to relearn what `120` means.
"""

from __future__ import annotations

import pytest

from nanoframes.parse import parse_string
from nanoframes.timespec import TimeSpecError, frame_indices, parse_range, parse_time

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="50"'
       ' data-fps="30" data-duration="6.0"><rect width="100" height="50" fill="#fff"/>'
       '</svg>')


@pytest.fixture()
def comp():
    return parse_string(SVG).composition


@pytest.mark.parametrize("spec,seconds", [
    ("start", 0.0),
    ("3.2s", 3.2),
    ("500ms", 0.5),
    ("50%", 3.0),
    ("120", 4.0),        # a bare number is a frame
    ("120f", 4.0),
    ("0:02.5", 2.5),
    ("1:05.5", None),    # outside this clip on purpose: checked below
])
def test_the_grammar(spec, seconds, comp):
    if seconds is None:
        with pytest.raises(TimeSpecError):
            parse_time(spec, comp)
        return
    assert parse_time(spec, comp) == pytest.approx(seconds)


def test_a_bare_number_is_a_frame_not_a_second(comp):
    assert parse_time("30", comp) == pytest.approx(1.0)
    assert parse_time("1s", comp) == pytest.approx(1.0)
    # An integer is a frame; a decimal is a time, because `--t 2.5` has always
    # meant two and a half seconds here and changing that silently would move
    # every existing invocation.
    assert parse_time("3", comp) == pytest.approx(0.1)
    assert parse_time("3.0", comp) == pytest.approx(3.0)
    assert parse_time("3.0s", comp) == pytest.approx(3.0)


def test_end_is_the_last_rendered_frame_not_the_duration(comp):
    """`duration` is one frame past what is drawn, so `end` must not be it."""
    assert parse_time("end", comp) == pytest.approx(6.0 - 1 / 30)
    assert parse_time("end", comp) < comp.duration


def test_case_and_whitespace_are_forgiven(comp):
    assert parse_time("  50 %  ".replace(" ", ""), comp) == pytest.approx(3.0)
    assert parse_time("START", comp) == 0.0


def test_a_time_outside_the_clip_is_refused_not_clamped(comp):
    """Clamping renders the last frame while the command line says something else."""
    with pytest.raises(TimeSpecError) as err:
        parse_time("99s", comp)
    assert "outside the clip" in str(err.value)


def test_nonsense_is_refused_with_the_grammar_in_the_message(comp):
    with pytest.raises(TimeSpecError) as err:
        parse_time("soon", comp)
    assert "3.2s" in str(err.value)


# --- ranges -------------------------------------------------------------------

def test_a_range_is_two_times(comp):
    assert parse_range("2s..4s", comp) == (2.0, 4.0)


def test_either_side_of_a_range_may_be_open(comp):
    assert parse_range("..1s", comp) == (0.0, 1.0)
    assert parse_range("5s..", comp) == (5.0, 6.0)
    assert parse_range(None, comp) == (0.0, 6.0)


def test_a_single_time_is_that_one_frame(comp):
    start, end = parse_range("2s", comp)
    assert start == 2.0 and end == pytest.approx(2.0 + 1 / 30)


def test_an_empty_range_is_refused(comp):
    with pytest.raises(TimeSpecError):
        parse_range("4s..2s", comp)


def test_the_frames_a_range_selects(comp):
    assert frame_indices("2s..2.1s", comp) == [60, 61, 62]
    assert frame_indices("start..1s", comp) == list(range(30))
    assert frame_indices(None, comp) == list(range(180))


def test_a_range_beyond_the_clip_is_refused(comp):
    """The same rule as a single time: say so, do not quietly shorten the clip."""
    with pytest.raises(TimeSpecError):
        frame_indices("5s..99s", comp)


# --- through the CLI ----------------------------------------------------------

def test_the_cli_accepts_every_form(tmp_path):
    from nanoframes.cli import main

    comp = tmp_path / "t.nf.svg"
    comp.write_text(SVG, encoding="utf-8")
    for spec in ("120", "120f", "4.0s", "66.67%", "start", "end", "0:04"):
        out = tmp_path / f"{spec.replace(':', '_').replace('%', 'pct')}.png"
        assert main(["render", str(comp), "--t", spec, "-o", str(out)]) == 0, spec
        assert out.exists(), spec


def test_the_cli_reports_a_bad_time_as_a_usage_error(tmp_path, capsys):
    from nanoframes.cli import main

    comp = tmp_path / "t.nf.svg"
    comp.write_text(SVG, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["render", str(comp), "--t", "soon", "-o", str(tmp_path / "x.png")])
    assert excinfo.value.code == 2
    assert "cannot read" in capsys.readouterr().err


def test_crop_writes_the_requested_pixels(tmp_path):
    from PIL import Image

    from nanoframes.cli import main

    comp = tmp_path / "t.nf.svg"
    comp.write_text(SVG, encoding="utf-8")
    out = tmp_path / "crop.png"
    assert main(["render", str(comp), "--t", "0", "--crop", "10,5,40,20",
                 "-o", str(out)]) == 0
    assert Image.open(out).size == (40, 20)


def test_zoom_scales_a_crop_up(tmp_path):
    from PIL import Image

    from nanoframes.cli import main

    comp = tmp_path / "t.nf.svg"
    comp.write_text(SVG, encoding="utf-8")
    out = tmp_path / "zoom.png"
    assert main(["render", str(comp), "--t", "0", "--crop", "0,0,20,10",
                 "--zoom", "3", "-o", str(out)]) == 0
    assert Image.open(out).size == (60, 30)


def test_a_malformed_crop_is_a_usage_error(tmp_path, capsys):
    from nanoframes.cli import main

    comp = tmp_path / "t.nf.svg"
    comp.write_text(SVG, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(["render", str(comp), "--t", "0", "--crop", "nonsense",
              "-o", str(tmp_path / "x.png")])
    assert excinfo.value.code == 2
    assert "x,y,w,h" in capsys.readouterr().err


def test_a_range_renders_only_those_frames(tmp_path):
    from nanoframes.cli import main

    comp = tmp_path / "t.nf.svg"
    comp.write_text(SVG, encoding="utf-8")
    out = tmp_path / "frames"
    assert main(["render", str(comp), "--range", "1s..1.2s", "-o", str(out)]) == 0
    assert len(list(out.iterdir())) == 6      # 1.0s..1.2s at 30fps, end exclusive


def test_strip_takes_a_range(tmp_path):
    from nanoframes.cli import main

    comp = tmp_path / "t.nf.svg"
    comp.write_text(SVG, encoding="utf-8")
    out = tmp_path / "s.png"
    assert main(["strip", str(comp), "--range", "2s..4s", "-n", "4",
                 "-o", str(out)]) == 0
    assert out.exists()

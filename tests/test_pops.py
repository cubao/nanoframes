"""Pops: a change in one frame between two frames that held.

The detector exists for the one failure nothing else sees. `check` reads
declarations and `strip` samples the clip; an element that is *there* and then,
one frame later, *there* passes both. Each frame is a good picture.
"""

from __future__ import annotations

from nanoframes.diagnose import scan_pops
from nanoframes.parse import parse_string

HEAD = """<svg xmlns="http://www.w3.org/2000/svg" data-width="320" data-height="180"
 data-fps="30" data-duration="1.0" data-composition-id="p">
 <rect width="320" height="180" fill="#ffffff" data-duration="1.0"/>
 <rect id="b" x="10" y="60" width="40" height="40" fill="#0000ff" data-duration="1.0"/>
"""
TAIL = " ]]></script></svg>"


def _anim(keyframes: str) -> str:
    body = ('<script type="application/nanoframes+json"><![CDATA[\n'
            f'{{"animations":[{{"target":"#b","keyframes":[{keyframes}]}}]}}'
            + TAIL)
    return HEAD + body


#: Holds, then teleports in one frame, then holds. The motion a `pop` is.
POP = _anim('{"t":0.0,"transform":{"translate":[0,0]}},'
            '{"t":0.4,"transform":{"translate":[0,0]}},'
            '{"t":0.46,"transform":{"translate":[190,0]}},'
            '{"t":1.0,"transform":{"translate":[190,0]}}')

#: The same endpoints, moving the whole time.
SMOOTH = _anim('{"t":0.0,"transform":{"translate":[0,0]}},'
               '{"t":0.9,"transform":{"translate":[190,0]},"ease":"ease-in-out"}')


def test_a_teleport_is_reported():
    scan = scan_pops(parse_string(POP))
    assert scan.pops, "the box jumps 190px in one frame and was not reported"
    pop = scan.pops[0]
    assert 11 <= pop.frame <= 15
    assert pop.changed > 0.02
    assert pop.how in ("jumped", "vanished")


def test_continuous_motion_is_not():
    """An ease-in-out over the whole clip is fast in the middle and still not a pop."""
    assert scan_pops(parse_string(SMOOTH)).pops == []


def test_the_box_is_in_canvas_pixels():
    scan = scan_pops(parse_string(POP))
    x0, y0, x1, y1 = scan.pops[0].box
    assert 0 <= x0 < x1 <= 320
    assert 0 <= y0 < y1 <= 180


def test_an_element_that_appears_is_named_appeared():
    """A `data-start` with no fade is a change in one frame; what kind matters."""
    svg = (HEAD + '<rect id="late" x="120" y="60" width="60" height="60"'
                  ' fill="#000000" data-start="0.5" data-duration="0.5"/></svg>')
    scan = scan_pops(parse_string(svg))
    kinds = [p.how for p in scan.pops]
    assert "appeared" in kinds or "jumped" in kinds


def test_a_declared_cut_is_marked_as_the_authors_choice():
    """`data-start` is exactly what a cut is; the report must not cry wolf."""
    svg = HEAD + ('<rect id="late" x="120" y="60" width="60" height="60" fill="#000000"'
                  ' data-start="0.5" data-duration="0.5"/></svg>')
    scan = scan_pops(parse_string(svg))
    assert scan.pops
    assert all(p.declared for p in scan.pops), [p.to_dict() for p in scan.pops]
    assert scan.undeclared == []


def test_an_undeclared_jump_is_not_marked():
    scan = scan_pops(parse_string(POP))
    assert scan.pops and not scan.pops[0].declared
    assert scan.undeclared == scan.pops


def test_a_clip_too_short_to_have_a_neighbour_is_not_scanned():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="50"'
           ' data-fps="30" data-duration="0.06"><rect width="100" height="50" fill="#fff"/>'
           '</svg>')
    scan = scan_pops(parse_string(svg))
    assert scan.frames == 2 and scan.pops == []


def test_the_threshold_is_the_caller_s():
    """A high threshold is how a caller asks for "only the enormous ones"."""
    assert scan_pops(parse_string(POP), threshold=0.9).pops == []


def test_the_scan_is_deterministic():
    a = scan_pops(parse_string(POP)).to_dict()
    b = scan_pops(parse_string(POP)).to_dict()
    assert a == b


def test_debug_pops_reports_and_json_carries_it(tmp_path, capsys):
    from nanoframes.cli import main

    comp = tmp_path / "pop.nf.svg"
    comp.write_text(POP, encoding="utf-8")
    assert main(["debug", str(comp), "--pops", "--no-scan"]) == 0
    out = capsys.readouterr().out
    assert "pops:" in out and "one frame" in out

    import json

    main(["debug", str(comp), "--pops", "--no-scan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["pops"]["pops"]
    first = payload["pops"]["pops"][0]
    assert {"frame", "t", "box", "changed", "how", "declared"} <= set(first)


def test_a_clean_report_says_so(tmp_path, capsys):
    from nanoframes.cli import main

    comp = tmp_path / "smooth.nf.svg"
    comp.write_text(SMOOTH, encoding="utf-8")
    main(["debug", str(comp), "--pops", "--no-scan"])
    assert "pops: none" in capsys.readouterr().out

"""Rendering frames across processes: how many, and what comes out.

The load-bearing property is not speed, it is *sameness*: a pool must write the
same bytes the sequential loop wrote, or the feature trades correctness for
throughput. That is asserted directly (every frame of a short clip, rendered
both ways, compared by hash).

Why processes at all is also asserted, cheaply: ``resolve_jobs`` is the whole
policy, and it is a pure function of the requested count and the frame count.
"""

from __future__ import annotations

import hashlib
import os

from nanoframes import parallel

SVG = """<svg xmlns="http://www.w3.org/2000/svg" data-width="160" data-height="90"
     data-fps="10" data-duration="1.2" data-composition-id="p">
  <rect width="160" height="90" fill="#101010" data-duration="1.2"/>
  <rect id="box" x="10" y="20" width="20" height="20" fill="#5ef17c" data-duration="1.2"/>
  <script type="application/nanoframes+json"><![CDATA[
  {"animations": [{"target": "#box", "keyframes": [
      {"t": 0.0, "transform": {"translate": [0, 0]}},
      {"t": 1.0, "transform": {"translate": [100, 40]}}]}]}
  ]]></script>
</svg>"""


def _comp(tmp_path):
    path = tmp_path / "p.nf.svg"
    path.write_text(SVG, encoding="utf-8")
    return str(path)


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --- the policy ---------------------------------------------------------------

def test_auto_asks_for_a_pool_only_when_there_are_frames_to_share():
    assert parallel.resolve_jobs(0, 4) == 1
    assert parallel.resolve_jobs(0, 900) > 1
    assert parallel.resolve_jobs(0, 900) <= parallel.MAX_WORKERS


def test_asking_for_one_job_never_leaves_the_process():
    assert parallel.resolve_jobs(1, 900) == 1
    assert parallel.resolve_jobs(1, 4) == 1


def test_an_explicit_count_is_honoured_but_never_exceeds_the_frames():
    assert parallel.resolve_jobs(3, 900) == 3
    assert parallel.resolve_jobs(99, 5) == 5


def test_the_pool_never_asks_for_more_workers_than_the_machine_has():
    import os as _os

    assert parallel.resolve_jobs(0, 10 ** 6) <= min(parallel.MAX_WORKERS, _os.cpu_count() or 1)


# --- the output ---------------------------------------------------------------

def test_a_pool_writes_exactly_what_the_sequential_loop_writes(tmp_path):
    """The whole feature in one assertion: same frames, byte for byte."""
    from nanoframes.parse import parse_file
    from nanoframes.timeline import frame_times

    comp_path = _comp(tmp_path)
    doc = parse_file(comp_path)
    times = frame_times(doc.composition)

    seq_dir = tmp_path / "seq"
    par_dir = tmp_path / "par"
    seq_dir.mkdir()
    par_dir.mkdir()
    blank_seq = parallel.render_sequence(doc, comp_path, times, str(seq_dir), "p", jobs=1)
    blank_par = parallel.render_sequence(doc, comp_path, times, str(par_dir), "p", jobs=2)

    names = sorted(os.listdir(seq_dir))
    assert names == sorted(os.listdir(par_dir))
    assert len(names) == len(times)
    for name in names:
        assert _sha(str(seq_dir / name)) == _sha(str(par_dir / name)), name
    assert blank_seq == blank_par


def test_the_pool_divides_the_raster_budget_instead_of_multiplying_it():
    """``--threads 8 -j 8`` is eight workers with one raster thread each."""
    assert parallel.worker_threads(8, 8) == 1
    assert parallel.worker_threads(8, 4) == 2
    assert parallel.worker_threads(4, 8) == 1
    assert parallel.worker_threads(4, 1) == 4


def test_a_render_without_a_composition_path_stays_sequential(tmp_path):
    """A document built from a string has no file for a worker to re-parse."""
    from nanoframes.parse import parse_string
    from nanoframes.timeline import frame_times

    doc = parse_string(SVG)
    dest = tmp_path / "out"
    dest.mkdir()
    blank = parallel.render_sequence(doc, "", frame_times(doc.composition), str(dest),
                                     "p", jobs=4)
    assert len(os.listdir(dest)) == doc.composition.frame_count
    assert blank == []

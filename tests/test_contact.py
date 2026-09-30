"""Review images: the contact sheet, the onion blend, and the frame-time rule.

The two renderers below are checked as *functions of the frames they are given*
— sampling, layout and blending — with synthetic images, so the tests stay fast
and can assert exact pixels. The end-to-end path (a composition really going
through ThorVG and coming out as a sheet) is covered by the CLI tests.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from nanoframes import timeline
from nanoframes.contact import onion_image, sample_frames, strip_image
from nanoframes.parse import parse_string

SVG = """<svg xmlns="http://www.w3.org/2000/svg" data-width="160" data-height="90"
     data-fps="30" data-duration="{duration}" data-composition-id="t">
  <rect width="160" height="90" fill="#101010" data-duration="{duration}"/>
</svg>"""


def _comp(duration: float = 2.0):
    return parse_string(SVG.format(duration=duration)).composition


# --- frame times --------------------------------------------------------------

def test_frame_times_are_exact_divisions():
    """The bug the comparison found, pinned.

    ``i * (1/fps)`` rounds twice and lands a hair *below* ``i / fps`` for some
    frames — frames 111/207/222/237 of a 900-frame 30fps clip — which put a
    windowed element outside its own window at the frame it belonged to.
    """
    comp = _comp(30.0)
    times = timeline.frame_times(comp)
    assert times[111] == 111 / 30
    assert times[0] == 0.0 and times[-1] == 899 / 30
    assert times == [i / 30 for i in range(900)]
    # and the way it used to be computed really does differ, so this test fails
    # if someone reintroduces the step
    step = 1.0 / comp.fps
    assert [i * step for i in (111, 207, 222, 237)] != [i / 30 for i in (111, 207, 222, 237)]


def test_every_frame_of_a_clip_is_inside_a_one_frame_window():
    """What the exact division buys: no frame falls out of its own window."""
    comp = _comp(30.0)
    for i, t in enumerate(timeline.frame_times(comp)):
        start, end = i / comp.fps, i / comp.fps + 0.9 / comp.fps
        assert start <= t <= end, f"frame {i} is not in its own window"


# --- sampling -----------------------------------------------------------------

def test_sampling_spreads_across_the_clip_and_includes_both_ends():
    times = sample_frames(_comp(2.0), 4)
    assert times[0] == 0.0
    assert times[-1] == pytest.approx(2.0 - 1 / 30)
    assert times == sorted(times)


def test_sampling_a_range_stays_inside_it():
    times = sample_frames(_comp(10.0), 5, first=2.0, last=4.0)
    assert all(2.0 <= t <= 4.0 for t in times)


def test_asking_for_more_frames_than_exist_gives_what_exists():
    times = sample_frames(_comp(0.2), 50)          # 6 frames of clip
    assert len(times) == len(set(times))
    assert len(times) <= 6


def test_one_frame_is_the_first_one():
    assert sample_frames(_comp(2.0), 1) == [0.0]


# --- the sheet ----------------------------------------------------------------

def _frames(n: int, colour=(200, 40, 40)):
    return [(f"f{i}", Image.new("RGBA", (80, 45), (*colour, 255))) for i in range(n)]


def test_the_sheet_tiles_every_frame_and_keeps_its_labels():
    frames = _frames(5)
    sheet = strip_image(frames, tile_width=80, columns=3)
    assert sheet.width == 240                        # 3 columns
    assert sheet.height == 2 * (45 + 26)             # 5 tiles wrap onto two rows
    assert sheet.size[0] > 0


def test_tiles_keep_the_frame_aspect_ratio():
    sheet = strip_image([("a", Image.new("RGBA", (160, 90), (0, 0, 0, 255)))],
                        tile_width=80, columns=1)
    # 80 wide -> 45 tall, plus the label strip
    assert sheet.height == 45 + 26


def test_a_sheet_is_deterministic():
    a = strip_image(_frames(3)).tobytes()
    b = strip_image(_frames(3)).tobytes()
    assert a == b


def test_an_empty_sheet_is_refused():
    with pytest.raises(ValueError):
        strip_image([])


# --- the blend ----------------------------------------------------------------

def test_the_blend_weights_later_frames_stronger():
    """A red frame then a blue one: the result leans blue."""
    frames = [("a", Image.new("RGBA", (4, 4), (255, 0, 0, 255))),
              ("b", Image.new("RGBA", (4, 4), (0, 0, 255, 255)))]
    out = np.asarray(onion_image(frames, strength=1.0).convert("RGB"))[0, 0]
    assert out[2] > out[0], "the later frame is not the stronger one"


def test_equal_strength_averages():
    frames = [("a", Image.new("RGBA", (4, 4), (250, 0, 0, 255))),
              ("b", Image.new("RGBA", (4, 4), (0, 0, 250, 255)))]
    a, _b, c = np.asarray(onion_image(frames, strength=0.0).convert("RGB"))[0, 0]
    assert abs(int(a) - int(c)) <= 1


def test_the_weight_ratio_is_a_property_of_the_range_not_the_sample_count():
    """``-n`` decides how many ghosts, not how strongly the last one leads.

    Weight is assigned by position in the range, so the first frame always has
    weight 1 and the last ``1 + strength`` however finely the range was sampled
    — which keeps ``--count`` a resolution knob instead of a style one.
    """
    def ratio(count):
        frames = [(f"f{i}", Image.new("RGBA", (4, 4), (0, 0, 0, 255)))
                  for i in range(count)]
        frames[0] = ("first", Image.new("RGBA", (4, 4), (255, 0, 0, 255)))
        frames[-1] = ("last", Image.new("RGBA", (4, 4), (0, 0, 255, 255)))
        out = np.asarray(onion_image(frames, strength=1.0).convert("RGB"))[0, 0]
        # blue (last) : red (first) = 1 + strength : 1, with the black middles
        # contributing to neither channel
        return int(out[2]) / max(1, int(out[0]))

    assert abs(ratio(2) - 2.0) < 0.2
    assert abs(ratio(4) - 2.0) < 0.2


def test_what_every_frame_shares_survives_at_full_opacity():
    """The background is in every frame, so it comes back opaque, not faded."""
    base = (10, 20, 30, 255)
    frames = [(f"f{i}", Image.new("RGBA", (4, 4), base)) for i in range(4)]
    out = np.asarray(onion_image(frames))[0, 0]
    assert tuple(int(v) for v in out) == base


def test_a_blend_is_deterministic():
    assert onion_image(_frames(4)).tobytes() == onion_image(_frames(4)).tobytes()


def test_an_empty_blend_is_refused():
    with pytest.raises(ValueError):
        onion_image([])

"""Draft rendering at --scale: canvas size, asset prescaling, CLI wiring."""

import os

import pytest

from nanoframes.parse import parse_file
from nanoframes.render import render_frame
from nanoframes.scale import draft_size, prescale_images

EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples")
TITLE = os.path.join(EXAMPLES, "title-card.nf.svg")
MASTER = os.path.join(EXAMPLES, "master-demo.nf.svg")  # has two <image> orbs
DOT = os.path.join(EXAMPLES, "assets", "dot.png")  # the asset those orbs share


def test_draft_size_rounds_to_even_pixels():
    # odd canvases must not produce odd draft sizes: yuv420p requires even
    assert draft_size(960, 540, 0.5) == (480, 270)
    assert draft_size(961, 541, 0.5) == (480, 270)
    assert draft_size(1600, 1200, 1.0) == (1600, 1200)


def test_render_frame_scale_shrinks_canvas():
    doc = parse_file(TITLE)
    assert render_frame(doc, t=2.0).size == (480, 240)
    assert render_frame(doc, t=2.0, scale=0.5).size == (240, 120)


def test_prescale_rewrites_href_and_is_scale_idempotent():
    """A second pass at another scale resizes the authored source, not the copy."""
    doc = parse_file(MASTER)
    hrefs = [n.get("href") for n in doc.root.iter() if n.tag.endswith("image")]
    assert len(hrefs) == 2 and all(h == "assets/dot.png" for h in hrefs)

    count = prescale_images(doc, 0.5)
    assert count == 2
    half = [n.get("href") for n in doc.root.iter() if n.tag.endswith("image")]
    assert all(h != "assets/dot.png" for h in half)
    assert len(set(half)) == 1  # one copy shared by both nodes

    prescale_images(doc, 0.5)
    assert [n.get("href") for n in doc.root.iter() if n.tag.endswith("image")] == half

    # a different scale must resize the source again, not the 0.5 copy
    prescale_images(doc, 0.25)
    quarter = [n.get("href") for n in doc.root.iter() if n.tag.endswith("image")]
    assert quarter != half
    from PIL import Image

    side = Image.open(DOT).width
    assert Image.open(half[0]).size == (side // 2, side // 2)
    assert Image.open(quarter[0]).size == (side // 4, side // 4)


def test_prescale_skips_missing_and_remote_assets(tmp_path):
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100" '
        'data-duration="1">'
        '<image id="gone" href="nope.png" width="10" height="10"/>'
        '<image id="remote" href="https://example.com/a.png" width="10" height="10"/>'
        "</svg>"
    )
    doc = parse_file(str(comp))
    assert prescale_images(doc, 0.5) == 0
    assert doc.root.find(".//{http://www.w3.org/2000/svg}image").get("href") == "nope.png"


def test_scale_one_restores_the_authored_asset():
    """A draft must not degrade a later full-quality render of the same doc."""
    doc = parse_file(MASTER)
    prescale_images(doc, 0.25)
    assert prescale_images(doc, 1.0) == 2
    hrefs = [n.get("href") for n in doc.root.iter() if n.tag.endswith("image")]
    assert hrefs == ["assets/dot.png", "assets/dot.png"]
    assert all(n.get("data-src") is None for n in doc.root.iter() if n.tag.endswith("image"))
    # nothing left to restore
    assert prescale_images(doc, 1.0) == 0


def test_scale_above_one_is_a_no_op(tmp_path):
    comp = tmp_path / "c.nf.svg"
    comp.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-width="100" data-height="100" '
        'data-duration="1"><image id="i" href="a.png" width="10" height="10"/></svg>'
    )
    doc = parse_file(str(comp))
    assert prescale_images(doc, 1.0) == 0
    assert prescale_images(doc, 2.0) == 0


def test_cli_render_scale_writes_smaller_frame(tmp_path):
    from nanoframes.cli import main

    dst = str(tmp_path / "draft.png")
    code = main(["render", TITLE, "--t", "2.0", "-o", dst, "--scale", "0.5", "--no-cache"])
    assert code == 0
    from PIL import Image

    assert Image.open(dst).size == (240, 120)


def test_cli_scale_must_be_positive(tmp_path, capsys):
    from nanoframes.cli import main

    dst = str(tmp_path / "x.png")
    with pytest.raises(SystemExit) as excinfo:
        main(["render", TITLE, "--t", "2.0", "-o", dst, "--scale", "0"])
    assert excinfo.value.code == 2
    capsys.readouterr()


def test_cli_video_scale_muxes_at_the_draft_size(tmp_path):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    from nanoframes.cli import main

    out = str(tmp_path / "draft.mp4")
    code = main(["video", TITLE, "-o", out, "--scale", "0.5", "--no-cache"])
    assert code == 0
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
        capture_output=True, text=True).stdout.strip()
    assert info == "240,120"

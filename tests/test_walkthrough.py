"""Happy-path smoke test for the generated walkthrough."""

import os

from nanoframes import walkthrough


def test_walkthrough_generates_artifacts(tmp_path):
    out = str(tmp_path / "walkthrough")
    readme = walkthrough.build(out, with_audio=False)
    assert readme == os.path.join(out, "README.md")
    assert os.path.exists(readme)
    # the story composition + rendered frames + determinism proof + video
    assert os.path.isdir(os.path.join(out, "frames"))
    assert os.listdir(os.path.join(out, "frames"))
    det = open(os.path.join(out, "determinism.txt")).read().splitlines()
    assert "byte-identical: True" in det
    assert os.path.exists(os.path.join(out, "video", "story.mp4"))
    assert os.path.exists(os.path.join(out, "assets", "dot.png"))
    # manifest carries a deterministic sha
    import json

    manifest = json.load(open(os.path.join(out, "manifest.json")))
    assert manifest["render"]["deterministic"] is True
    assert len(manifest["render"]["story_t2.00_sha256"]) == 64


def test_walkthrough_readme_is_well_formed(tmp_path):
    out = str(tmp_path / "w")
    walkthrough.build(out, with_audio=False)
    text = open(os.path.join(out, "README.md")).read()
    assert "## 1 · Why offline" in text
    assert "## 7 · Live for agents" in text
    assert "```svg" in text and "```json" in text
    # relative image/video links (open in a plain markdown editor)
    assert "](frames/story_t2.png)" in text
    assert "video/story.mp4" in text
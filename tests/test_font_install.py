"""``fonts add`` and what it promises: a face that the renderer then loads.

The bug this closes was a promise with no implementation — the command copied a
file into a directory nothing read, so every later render fell back to the
bundled face while `check` said the family resolved to nothing. The tests here
hold the two halves together: the file lands under a name an author can write,
and a render actually selects it.
"""

from __future__ import annotations

import os
import shutil

import numpy as np
import pytest

from nanoframes import fonts

BUNDLED = fonts.DEFAULT_FONT_CANDIDATES[0]


@pytest.fixture()
def user_dir(tmp_path, monkeypatch):
    """A private ``~/.local/share/nanoframes/fonts`` for the test."""
    home = tmp_path / "home"
    directory = home / ".local" / "share" / "nanoframes" / "fonts"
    directory.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return directory


def _ink(img) -> int:
    a = np.array(img.convert("L"))
    return int((a < 128).sum())


def test_the_user_dir_is_where_the_command_and_the_renderer_agree(user_dir):
    assert fonts.user_font_dir() == str(user_dir)


def test_an_empty_user_dir_changes_nothing(user_dir):
    assert fonts.font_candidates() == fonts.DEFAULT_FONT_CANDIDATES


def test_a_face_in_the_user_dir_is_loaded(user_dir):
    shutil.copyfile(BUNDLED, user_dir / "Whatever I Called It.ttf")
    candidates = fonts.font_candidates()
    assert str(user_dir / "Whatever I Called It.ttf") in candidates
    assert candidates[:len(fonts.DEFAULT_FONT_CANDIDATES)] == fonts.DEFAULT_FONT_CANDIDATES, \
        "the bundled face must stay first: it is what an unresolved family falls back to"


def test_only_font_files_are_picked_up(user_dir):
    (user_dir / "notes.txt").write_text("not a font")
    (user_dir / "face.ttc").write_text("collections cannot be loaded by this build")
    assert fonts.font_candidates() == fonts.DEFAULT_FONT_CANDIDATES


def test_the_bundled_face_answers_to_the_name_its_docs_use():
    """'Sarasa Mono SC' has to be a hit, not a miss that lands on the same face."""
    assert fonts.face_names(BUNDLED) == ("Sarasa Mono SC",)


def test_a_face_answers_to_its_file_stem_and_nothing_else(tmp_path):
    """The engine's rule, which is not the font's own family name.

    A copy of the bundled face under a different stem answers to *that* stem:
    the loader registers a face under the path it was handed, so the file name
    is the interface.
    """
    renamed = tmp_path / "Some Brand Face.ttf"
    shutil.copyfile(BUNDLED, renamed)
    assert fonts.face_names(str(renamed)) == ("Some Brand Face",)
    assert fonts.face_names(BUNDLED) == ("Sarasa Mono SC",)


def test_the_name_that_selects_a_face_is_its_file_stem_not_its_family(tmp_path):
    """The rule ``check`` reports, measured on pixels rather than asserted from docs.

    Two faces that draw different widths are loaded; a name that matches a
    loaded *stem* gets that face, and anything else falls back to the first one
    loaded. The bundled face and Arial disagree on how wide this string is, so
    the ink separates a hit from a fallback.
    """
    from nanoframes.render import render_svg

    arial = "/System/Library/Fonts/Supplemental/Arial.ttf"
    if not os.path.exists(arial):
        pytest.skip("no Arial on this host to compare against the bundled face")
    text = "Hello Renderer! 123"
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="120">'
           '<rect width="1400" height="120" fill="#fff"/>'
           '<text x="20" y="80" font-family="%s" font-size="60" fill="#000">%s</text>'
           '</svg>')

    def width(name):
        img = render_svg(svg % (name, text), 1400, 120, threads=1,
                         font_paths=[BUNDLED, arial])
        a = np.array(img.convert("L"))
        cols = (a < 128).any(axis=0)
        idx = np.nonzero(cols)[0]
        return int(idx.max() - idx.min() + 1)

    hit = width("Arial")
    assert hit != width("No Such Face"), "a stem hit drew the same as the fallback"
    # the name table is not consulted: Arial's own full and PostScript names miss
    assert width("ArialMT") == width("No Such Face")
    # and the file's stem is what a copy answers to
    renamed = tmp_path / "Some Brand Face.ttf"
    shutil.copyfile(arial, renamed)
    img = render_svg(svg % ("Some Brand Face", text), 1400, 120, threads=1,
                     font_paths=[BUNDLED, str(renamed)])
    a = np.array(img.convert("L"))
    cols = (a < 128).any(axis=0)
    idx = np.nonzero(cols)[0]
    assert int(idx.max() - idx.min() + 1) == hit, "the copy lost its new stem"


# --- what `fonts add` names the file ------------------------------------------

def test_a_regular_face_is_stored_under_its_family_name():
    from nanoframes.cli import _installed_font_name

    assert _installed_font_name("Some Brand Face", "Regular", ".ttf") == "Some Brand Face.ttf"


def test_a_styled_face_carries_the_style_so_two_styles_can_coexist():
    from nanoframes.cli import _installed_font_name

    assert _installed_font_name("Some Brand Face", "Bold", ".ttf") == "Some Brand Face Bold.ttf"


def test_a_path_hostile_family_name_cannot_escape_the_directory():
    from nanoframes.cli import _installed_font_name

    name = _installed_font_name("../../evil", "Regular", ".ttf")
    assert "/" not in name and name.endswith(".ttf")


def test_adding_a_file_that_is_not_a_font_is_refused(tmp_path, user_dir, capsys):
    from nanoframes.cli import cmd_fonts_add

    junk = tmp_path / "notafont.ttf"
    junk.write_bytes(b"this is not a font at all")

    class Args:
        path = str(junk)
        force = False

    assert cmd_fonts_add(Args()) == 2
    assert "family name" in capsys.readouterr().err
    assert not list(user_dir.iterdir())


def test_adding_the_bundled_face_installs_it_under_a_writable_name(user_dir, capsys):
    from nanoframes.cli import cmd_fonts_add

    class Args:
        path = BUNDLED
        force = False

    assert cmd_fonts_add(Args()) == 0
    installed = user_dir / "Sarasa Mono SC.ttf"
    assert installed.exists()
    assert "'Sarasa Mono SC'" in capsys.readouterr().out


def test_the_install_check_is_what_gates_a_broken_face(monkeypatch, tmp_path, user_dir, capsys):
    """A face that fails the load check is refused before it can reach a render."""
    from nanoframes import cli

    monkeypatch.setattr(cli, "_font_safety", lambda path, family: "crashes ThorVG at exit")

    class Args:
        path = BUNDLED
        force = False

    assert cli.cmd_fonts_add(Args()) == 1
    assert "refusing to install" in capsys.readouterr().err
    assert not list(user_dir.iterdir())


def test_force_installs_anyway(monkeypatch, user_dir, capsys):
    from nanoframes import cli

    monkeypatch.setattr(cli, "_font_safety", lambda path, family: "crashes ThorVG at exit")

    class Args:
        path = BUNDLED
        force = True

    assert cli.cmd_fonts_add(Args()) == 0
    assert (user_dir / "Sarasa Mono SC.ttf").exists()


def test_the_renderer_skips_a_face_it_cannot_load_rather_than_failing():
    """A path that vanished between listing and loading is not fatal."""
    from nanoframes.render import render_svg

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="80">'
           '<rect width="200" height="80" fill="#fff"/>'
           '<text x="10" y="50" font-family="Sarasa Mono SC" font-size="30" fill="#000">hi</text>'
           '</svg>')
    img = render_svg(svg, 200, 80, threads=1,
                     font_paths=["/no/such/face.ttf", BUNDLED])
    assert _ink(img) > 0


def test_the_fonts_directory_ships_with_the_package():
    assert os.path.exists(BUNDLED), "the wheel must carry the bundled face"
    assert os.path.basename(BUNDLED) == "Sarasa Mono SC.ttf"

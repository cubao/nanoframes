"""Dogfood test: the example in the SKILL.md must parse and lint clean."""

import os
import re

from nanoframes.lint import has_errors, lint_string

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "skills", "nanoframes", "SKILL.md")

_FENCE = re.compile(r"```svg\n(.*?)```", re.DOTALL)


def _skill_svg_example() -> str:
    text = open(SKILL).read()
    m = _FENCE.search(text)
    assert m, "SKILL.md must contain a ```svg example"
    return m.group(1)


def test_skill_example_lints_clean():
    svg = _skill_svg_example()
    findings = lint_string(svg)
    assert not has_errors(findings), f"SKILL example must lint clean: {findings}"
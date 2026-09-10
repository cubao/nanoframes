"""Dogfood tests: the shipped compositions must lint clean — SKILL's example, the corpus.

The examples are what a reader copies from, and the skill tells agents to keep
`check` clean, so the corpus is held to the stricter bar: no findings at all
(a warning here is a trap the docs teach against).
"""

import os
import re

import pytest

from nanoframes.lint import has_errors, lint_path, lint_string

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "skills", "nanoframes", "SKILL.md")
EXAMPLES = os.path.join(HERE, "..", "examples")

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


def _examples() -> list:
    return sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".nf.svg"))


@pytest.mark.parametrize("name", _examples())
def test_shipped_examples_have_no_findings(name):
    findings = lint_path(os.path.join(EXAMPLES, name))
    assert not findings, f"{name} must lint clean: {[str(f) for f in findings]}"
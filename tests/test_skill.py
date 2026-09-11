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

# --- diagram craft references ------------------------------------------------

SKILL_DIR = os.path.join(HERE, "..", "skills", "nanoframes")
_REF_LINK = re.compile(r"`(references/[A-Za-z0-9._-]+\.md)`")


def test_skill_routing_table_links_exist():
    """Every reference the routing table names must ship next to SKILL.md."""
    text = open(SKILL).read()
    linked = {os.path.basename(ref) for ref in _REF_LINK.findall(text)}
    assert linked, "SKILL.md routes to no references"
    missing = sorted(ref for ref in linked
                     if not os.path.exists(os.path.join(SKILL_DIR, "references", ref)))
    assert not missing, f"SKILL.md links references that do not exist: {missing}"


def test_diagram_examples_build_from_their_specs(tmp_path):
    """The shipped diagram specs build the shipped compositions, warning-free."""
    from nanoframes.diagram import build_scene, load_spec, render
    from nanoframes.render import measurer

    specs = sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".nf.json"))
    assert specs, "no diagram specs ship in examples/"
    m = measurer()
    for name in specs:
        spec_path = os.path.join(EXAMPLES, name)
        spec = load_spec(spec_path)
        scene = build_scene(spec, measurer=m)
        assert scene.warnings == [], f"{name}: {scene.warnings}"
        svg = render(scene, composition_id=name[:-len(".json")], measurer=m)
        shipped = spec_path[:-len(".nf.json")] + ".nf.svg"
        assert os.path.exists(shipped), f"{name} has no built composition next to it"
        assert svg == open(shipped).read(), f"{shipped} is stale — rebuild it"

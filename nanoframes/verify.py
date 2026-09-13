"""One question, one envelope: is this composition sound?

`check` answers "is the contract satisfied", `debug` answers "where did the
drawing go", `doctor` answers "can this machine render". Each is a different
question with its own output, and an agent that has to run three of them has to
join three objects itself, decide which of them means "no", and keep three exit
codes straight. This turns that into one object and one exit code.

**Every section is the sub-command's own payload, embedded verbatim.** Not a
summary of it, not a re-shaped version — the same object `check --json` prints,
under the key `check`. It is verbatim by construction rather than by discipline:
there is one producer per section (`lint.payload`, `diagnose.debug_payload`,
`doctor.Report.to_dict`), and both the command and this envelope call it. An
envelope that reformatted a section would be a second implementation of every
verdict in it, and the second one is the one nobody tests.

**What decides the exit code.** An *error* is a section whose own verdict is
false: a lint error, an unmet precondition, a parse that failed. A *warning* is
a reported finding — a lint warning, a blank element, a never-visible element, a
buried one — which is carried and does not fail on its own. A box that misses the
canvas and an intended lower third overlapping the shot under it are both real,
and neither is a reason to refuse a render; `--strict` is what makes them count.
Both are listed in the envelope, so the reader can see what was reported and what
was fatal.

A composition that will not parse at all never reaches here — the CLI treats it
as a usage error (exit 2), because the sections that follow cannot run.
"""

from __future__ import annotations

from nanoframes import diagnose, doctor, lint
from nanoframes.cache import DEFAULT_CACHE
from nanoframes.envelope import EXIT_FAIL, EXIT_OK

# Sections, in the order a failure would bite: can the machine render, is the
# composition well-formed, and where does the drawing actually land.
SECTIONS = ("doctor", "check", "debug")


def _thrown(exc: Exception) -> dict:
    """A section that raised, recorded as that section's failure.

    The other sections still report: one missing piece must not cost the reader
    the diagnostics that did run. A section that errored is not `ok`, so it also
    lands in `errors`.
    """
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _count_warnings(payload: dict) -> int:
    """Reported, non-fatal findings in one section's payload.

    Read off the section's own keys rather than recomputed, so this cannot
    disagree with what the section printed.
    """
    total = int(payload.get("warnings", 0) or 0)
    frame = payload.get("frame")
    if isinstance(frame, dict):
        for key in ("blanks", "invisible", "hidden_but_drawn"):
            value = frame.get(key)
            if isinstance(value, list):
                total += len(value)
    scan = payload.get("scan")
    if isinstance(scan, dict) and isinstance(scan.get("never_visible"), list):
        total += len(scan["never_visible"])
    return total


def run(doc, *, t: float = 0.0, samples: int = diagnose.SCAN_SAMPLES,
        pixels: bool = True, threads: int = 4, strict: bool = False,
        cache_dir: str = DEFAULT_CACHE, measurer=None) -> tuple[int, dict]:
    """Run every gate over an already-parsed composition.

    ``pixels`` is passed through to `debug` and defaults to on. It costs one
    render per reported element at a single frame — bounded by the element count,
    not the frame count — and it is the only reading that finds an element
    contributing no pixel. A gate that left out its most informative check by
    default would be weaker than it advertises, and an agent that runs only
    `verify` would never see it.
    """
    if measurer is None:
        from nanoframes.render import measurer as default_measurer

        # One measurer for every section: each measures the same text, and the
        # cache inside it is what keeps `verify` from measuring it three times.
        measurer = default_measurer()

    sections: dict[str, dict] = {}
    try:
        sections["doctor"] = doctor.report(cache_dir).to_dict()
    except Exception as exc:  # noqa: BLE001 — a section failure, not a crash
        sections["doctor"] = _thrown(exc)
    try:
        sections["check"] = lint.payload(lint.lint_document(doc, measurer=measurer))
    except Exception as exc:  # noqa: BLE001
        sections["check"] = _thrown(exc)
    try:
        sections["debug"] = diagnose.debug_payload(
            doc, t, measurer=measurer, samples=samples, pixels=pixels,
            threads=threads, scan=True, loop=False)
    except Exception as exc:  # noqa: BLE001
        sections["debug"] = _thrown(exc)

    errors = [name for name in SECTIONS if sections[name].get("ok") is not True]
    warnings = sum(_count_warnings(sections[name]) for name in SECTIONS)
    ok = not errors and (not strict or warnings == 0)

    payload = {
        "ok": ok,
        "strict": strict,
        "errors": errors,
        "warnings": warnings,
        "examined": {"t": t, "scan_samples": samples, "pixels_probed": pixels},
        **sections,
    }
    return (EXIT_OK if ok else EXIT_FAIL), payload


def summary_lines(payload: dict) -> list[str]:
    """The human-readable form: what ran, what failed, and what was warned about."""
    lines = [f"verify — {len(payload['errors'])} error(s), {payload['warnings']} warning(s)"
             + (", --strict" if payload["strict"] else "")]
    for name in SECTIONS:
        section = payload[name]
        lines.append(f"  {'ok  ' if section.get('ok') else 'FAIL'} {name}{_describe(section)}")
    examined = payload["examined"]
    lines.append("")
    lines.append(f"debug examined frame t={examined['t']:g}, "
                 f"{examined['scan_samples']} sampled frame(s)"
                 + (", each element hidden in turn to check its contribution"
                    if examined["pixels_probed"] else ""))
    if payload["warnings"] and not payload["strict"]:
        lines.append("A warning is a reported finding, not a failure; --strict counts them.")
    return lines


def _describe(section: dict) -> str:
    if "error" in section:
        return f" — {section['error']}"
    if isinstance(section.get("failed"), list) and section["failed"]:
        return f" — {', '.join(section['failed'])}"
    if "errors" in section:
        return f" — {section['errors']} error(s), {section['warnings']} warning(s)"
    if "frame" in section:
        return " — " + describe_debug(section)
    return ""


def describe_debug(section: dict) -> str:
    """What the reading found, in the reader's words rather than the keys'."""
    parts = []
    for label, value in (("blank", section["frame"].get("blanks")),
                         ("invisible", section["frame"].get("invisible")),
                         ("hidden but drawn", section["frame"].get("hidden_but_drawn")),
                         ("never visible", section.get("scan", {}).get("never_visible"))):
        if value:
            parts.append(f"{len(value)} {label}")
    return ", ".join(parts) if parts else "nothing reported"

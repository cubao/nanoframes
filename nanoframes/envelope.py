"""The `--json` contract, in one place: one object, a flushed write, redacted paths.

Every machine-readable command follows the same rules, and they are rules a
reader branches on rather than prose they parse:

* **Exactly one JSON object on stdout.** Diagnostics go to stderr. An agent that
  gets two objects, or an object with a log line in front of it, has to guess.
* **Exit codes mean three different things.** ``0`` the check passed, ``1`` the
  check ran and failed, ``2`` the invocation was wrong. A typo in a filename is
  not the same event as a composition with an error, and a script has to be able
  to tell them apart.
* **The write is flushed before the process ends.** A film-length frame hash
  sequence is hundreds of KB, a piped reader accepts 64 KiB before applying
  backpressure, and ``sys.stdout.write`` queues and returns — so a process that
  exits at that moment truncates the object. This only shows up under a pipe,
  which is exactly where an agent reads it.
* **Absolute paths are redacted.** An envelope is what gets pasted into an issue
  or into another agent's context. A path under the checkout is a fact about the
  repository; a path under the operator's home is a fact about the operator.
  Anything else — ``/opt/homebrew/bin/ffmpeg`` — is left alone. Human-readable
  output is never redacted: that is for a person reading a terminal, where the
  real path is what they paste back into a command.
* **``NANOFRAMES_RUN_ID`` is echoed as ``runId``.** One agent turn runs
  ``check``, ``debug`` and ``verify``; those are three objects with nothing
  joining them, and the shell that ran them is the only place the join existed.
"""

from __future__ import annotations

import json
import os
import sys

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

RUN_ID_ENV = "NANOFRAMES_RUN_ID"


def run_id() -> str | None:
    """The caller's run id, so several envelopes from one turn can be joined."""
    value = os.environ.get(RUN_ID_ENV)
    return value or None


def repo_root() -> str | None:
    """The checkout this is running from, if it is a checkout.

    The working directory first — that is the tree the composition paths are
    relative to — then the package's own parent, which covers a command run from
    elsewhere against a checkout. An installed wheel has neither, and then there
    is nothing to relativise a path against.
    """
    candidates = [os.getcwd(), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for candidate in candidates:
        if os.path.isdir(os.path.join(candidate, ".git")):
            return candidate
    return None


def redact(payload, root: str | None = None, home: str | None = None):
    """``$REPO`` for a path under the checkout, ``$HOME`` for one under home.

    The order is load-bearing: a checkout usually sits under the home directory,
    so replacing home first would swallow the more useful of the two answers.
    The match is a substring replacement, not a path-shaped one, because most
    paths in an envelope appear inside a sentence.
    """
    if root is None:
        root = repo_root()
    if home is None:
        home = os.path.expanduser("~")
    pairs = [(p, label) for p, label in ((root, "$REPO"), (home, "$HOME")) if p]
    if not pairs:
        return payload
    return _walk(payload, pairs)


def _walk(value, pairs):
    if isinstance(value, str):
        for path, label in pairs:
            value = value.replace(path, label)
        return value
    if isinstance(value, dict):
        return {_walk(k, pairs): _walk(v, pairs) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(item, pairs) for item in value]
    return value


def emit(payload: dict, stream=None) -> None:
    """Write exactly one JSON object, with ``runId``, and flush it.

    ``ok`` is not injected here: a section's verdict belongs to the thing that
    computed it. ``runId`` is, because it is one rule for every command and a
    second copy of it would be the copy that goes stale.
    """
    stream = stream if stream is not None else sys.stdout
    out = dict(payload)
    run = run_id()
    if run is not None:
        out.setdefault("runId", run)
    stream.write(json.dumps(out, ensure_ascii=False) + "\n")
    stream.flush()


def emit_json(payload: dict, stream=None) -> None:
    """``emit`` with redaction applied — what a command calls for `--json`."""
    emit(redact(payload), stream=stream)

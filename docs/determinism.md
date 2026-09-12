# Determinism: what is claimed, and how it is checked

nanoframes claims every frame is a pure function of declared inputs. That claim
is worth nothing unless something can falsify it, and the falsification has to
distinguish two events that look identical from the outside:

- **the composition changed** — a normal edit, and the picture is supposed to
  move;
- **the picture changed while the composition did not** — the same declared
  inputs produced different pixels, which is the only outcome that matters.

A PNG baseline cannot tell them apart. `tests/snapshots/` compares committed
PNGs byte for byte, so a ThorVG upgrade and a one-pixel regression both arrive
as the same red test, and the first is not a bug.

## What the frame is a function of

`nanoframes.identity` names four inputs, and the frame cache keys on their
digest. Anything that can move a pixel is in; anything that cannot is out.

| component | what it covers |
| --- | --- |
| `source` | the composition, as a canonical projection — attributes sorted, check-only attributes (`data-safe-margin`, `data-palette-budget`) stripped |
| `media` | the content of every local `<image>` a composition references, named relative to the composition |
| `fonts` | the content of each font file the renderer registers, keyed by basename |
| `toolchain` | the `thorvg-python` version, the `nanoframes` version, and a digest of this package's own modules |

Two consequences are deliberate. `data-safe-margin` and `data-palette-budget`
are read by `lint` and by nothing that draws, so tuning a budget does not
invalidate a single cached frame — and reindenting a composition does not
either. The `toolchain` component over-invalidates: a docstring edit costs a
re-render. That is the direction to err in, because a wasted frame is free to
reproduce and a stale one is not.

## The ledger

`tests/digests.json` records, per composition, the digest of its full frame
sequence *and the identity it was taken under*:

```json
"examples/title-card.nf.svg": {
  "digest": "fc7b0da9cd6e6f7c…",
  "frames": 120,
  "sampled": false,
  "identity": { "source": "…", "media": "none", "fonts": "…", "toolchain": "…" }
}
```

`digest --check` compares a fresh render against it and reports one of three
outcomes:

- **match** — the digest agrees.
- **changed** — the digest moved, and so did at least one recorded input. The
  reasons name which: `source changed` is an edit, `toolchain changed` or
  `fonts changed` is the renderer. Exit 1 under `--check`, and the report says
  which side moved rather than leaving the reader to bisect their own tree.
- **regression** — the digest moved and *every* declared input is identical, so
  the same inputs produced a different frame. This is the outcome the ledger
  exists to make visible.

```bash
nanoframes digest --all --record     # (re)record every example — about 5s for 750 frames
nanoframes digest --all --check      # compare; exit 1 on any changed or regression
nanoframes digest <one>.nf.svg --check --json
```

A digest is taken over the raw RGBA of each frame, before any encoder sees it,
and the sequence digest is SHA-256 over the per-frame hashes joined **in order**
— frame order is part of a film's identity. MP4 bytes are deliberately not the
unit: they drag in the encoder's build, which cannot move a pixel, and upstream
precedent is a golden suite broken by a runtime upgrade whose pixels were
identical.

`--samples N` digests a subset for a quick check and records `sampled: true`, so
a cheap reading can never be mistaken in the ledger for a whole-film one.

## What is not done here

**Cross-architecture checking.** The claim that most needs this evidence is that
two machines produce identical frames. The ledger is the half that can exist in
a checkout; the other half is a CI job that renders the same tree on Linux/x86-64
and runs `digest --all --check` against digests recorded on macOS/ARM. There is
no CI configuration in this repository yet, so that check has not been run — the
ledger records the toolchain precisely so that when it is, a mismatch can name
its cause.

**A digest in the test suite.** `pytest` asserts the ledger's *shape* — every
example has an entry, no entry outlives its file, every entry carries its four
inputs, and the ledger was recorded in one pass so it has a single expiry date.
It does not render the tree, and it does not assert that the recorded toolchain
is the running one: a code edit legitimately moves the toolchain, so that
assertion would be red from the day it landed, which is not a gate. Freshness is
what `digest --all --check` reports, and it reports it as `changed — toolchain
changed` rather than as a failure of the composition.

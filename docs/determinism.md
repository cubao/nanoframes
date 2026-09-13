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
| `fonts` | the content of each face the composition's runs **resolve to**, keyed by basename |
| `toolchain` | the `thorvg-python` version, the content of the `libthorvg` that package carries, the `nanoframes` version, and a digest of this package's own modules |

`fonts` is a *resolution*, not an inventory. This loader matches a whole
`font-family` value against the faces it loaded and falls back to the first one
for a value that matches none (the CSS stacks in a typical composition match
nothing), so what can move a pixel is the face each run lands on — not every
face the machine happens to have. The distinction is what makes the component
comparable across machines: macOS ships Arial and a Linux runner does not, so an
inventory of candidates differs by construction and *every* cross-machine
comparison arrived as `changed — fonts changed`, which was true of the
fingerprint and false of the render. A composition that names no family, or a
stack that resolves to nothing, draws with the bundled face on every machine and
now hashes the same on every machine; one that names a face the host lacks
resolves to the fallback, is a genuinely different face, and still says so. A
composition with no `<text>` at all has no faces in this component — a font swap
cannot have moved a frame that draws no glyphs.

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
nanoframes digest --all --record     # (re)record every example — about 5s for 780 frames
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

## The other half: a second machine

`.github/workflows/determinism.yml` renders the corpus on Linux/x86-64 and runs
`digest --all --check` against the ledger recorded here on macOS/ARM. Before it
became a gate it was run by hand on native x86-64 hardware — Ubuntu 22.04.3,
Intel i9-9900K, CPython 3.12.13, `thorvg-python` 1.1.3, Pillow 11.1.0, NumPy
2.4.2 — against a ledger recorded on macOS 26.6.2, Apple M3, CPython 3.12.10.

What that run measured:

| composition | result |
| --- | --- |
| 8 of 10, over every frame | byte-identical |
| `text-measure` | 9 pixels of 230 400 differ, by at most 3/255, inside one glyph |
| `master-demo` | 45 frames of 180 differ, 1–5 pixels each, exactly ±1/255, on a glyph edge |

The two are exempt from the gate by name in `EXCUSED_COMPOSITIONS`, and printed
on every run as `EXCUSED` so that an exemption cannot quietly turn into silence.
What they are *not* is a layout difference: `nanoframes measure` prints identical
widths on both machines, and restricting the registered faces to the bundled one
changes nothing on either — the corpus draws with the same face everywhere. What
is left is the rasterizer's own rounding of a glyph edge, and that is exactly
what the identity now names: every platform wheel carries its own `libthorvg`, so
a mismatch on the second machine arrives as `changed — toolchain changed`, the
two bytes-level differences as well as any that would be new. It used to arrive
as `changed — fonts changed`, which was never the cause.

Three things a green run here does not say:

- **Anything about emulation.** GitHub's `ubuntu-latest` runners are native
  x86-64. The same comparison inside an `x86-64` container on an Apple Silicon
  host is *translated*, not native x86-64 — a green result there says the
  translation is faithful, not that the architecture is. (pocket-motion, in the
  same lane, writes the same warning into `baselines/hash-portability.md`.)
- **That every machine agrees.** One second machine is one sample. Another
  runner — a different CPU, a different FreeType underneath the rasterizer — may
  round another glyph differently. When it does, the job names the composition
  and the reason, and the choice is to measure it and add it to the exemption
  list, or to treat the claim as falsified for that commit.
- **That a mismatch here is a diagnosis of *why* two machines disagree.** The
  reason is now the right component — `toolchain`, because the platform's
  rasterizer build is in it — but it is still one component covering four inputs,
  and the verdict does not say whether the pixels moved because of the library,
  the version or this package. `regression`, the alarming verdict, is reachable
  again: two machines with the same declared inputs *and* the same rasterizer
  build that disagree are exactly what it names, and until the library's bytes
  were in the identity no cross-machine comparison could ever produce it.

## What is not done here

**The interpreter and the two libraries.** The rasterizer's build is covered now
— the `libthorvg` the installed `thorvg-python` carries is hashed into
`toolchain`, because a version is not a build and every platform wheel links its
own copy with its own FreeType. What stays out is the Python runtime and
Pillow/NumPy, and they stay out on purpose rather than by omission: neither
draws. Pillow decodes an `<image>` and NumPy carries the pixels, so anything they
decide reaches the frame *through* the decoded asset — whose bytes are the
`media` component — or through a measurement whose result is a coordinate in the
drawn picture, and the code that turns it into one is in `toolchain` already. The
workflow still pins Pillow and NumPy to the versions the ledger was recorded
under, so a red result names the machine rather than a dependency bump; that is a
pin inside one job, not an input in the identity. If a decode ever turns out to
move a pixel, the honest fix is to add it here, and the way to find out is the
same as it was for the rasterizer: a cross-machine run whose mismatch no declared
input can explain.

**A digest in the test suite.** `pytest` asserts the ledger's *shape* — every
example has an entry, no entry outlives its file, every entry carries its four
inputs, and the ledger was recorded in one pass so it has a single expiry date.
It does not render the tree, and it does not assert that the recorded toolchain
is the running one: a code edit legitimately moves the toolchain, so that
assertion would be red from the day it landed, which is not a gate. Freshness is
what `digest --all --check` reports, and it reports it as `changed — toolchain
changed` rather than as a failure of the composition.

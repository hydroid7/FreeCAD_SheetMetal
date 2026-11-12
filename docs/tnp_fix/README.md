# tnp_fix: implementation package for scored reference recovery

This folder is a self-contained implementation plan. It specifies a
replacement for the rule-based lost-reference resolver in
`SheetMetalTools.py` (lines ~1162–1430) by a scored, confidence-aware
resolver with a *refuse* outcome, plus a benchmark and an optional learned
scoring model. The problem it solves is described in
[../reference-resolution-problem.md](../reference-resolution-problem.md);
background on FreeCAD's naming mechanism is in [../TNP.md](../TNP.md).

Everything needed to implement is in this folder and the two documents
above. No other context is required.

## Goal

Given a lost reference (`?Edge98`) and the rebuilt upstream solid, return
the element(s) the user would consider "the same", or **refuse** with a
clear message. A wrong element is far worse than a refusal: the quality
metric is the rate of *wrong* resolutions (target: Wilson 95% upper bound
≤ 0.1% on the generated benchmark, per edit type).

## Hard constraints

* Pure Python, runs inside FreeCAD 1.1+ (flatpak 1.1.4 is the reference
  install). No network, no GPU, no new runtime dependencies (numpy is
  allowed only in the *offline* training script).
* Deterministic: the same document recomputes to the same result, always.
* At most tens of milliseconds per lost reference on parts with ~10^3
  edges.
* Works for edges, faces and vertices, and multi-element references.
* None of the 13 existing callers of
  `SheetMetalTools.smResolveSubElements` may need changes, and the
  function must never return an empty list for a non-empty sub list
  (three callers index `[0]` unconditionally: `ExtrudedCutout.py:145`,
  `SheetMetalFormingCmd.py:172`, `SheetMetalUnfoldCmd.py:583`).
* Existing documents must recompute exactly as before unless the old
  behaviour would have been a wrong answer (see strict/legacy modes in
  [01-architecture.md](01-architecture.md)).

## Folder contents

| file | contents |
|------|----------|
| [01-architecture.md](01-architecture.md) | module layout, pipeline, data types, refuse semantics, caller table |
| [02-name-parser.md](02-name-parser.md) | structured mapped-name parser, hash decoding, relation functions |
| [03-evidence-v2.md](03-evidence-v2.md) | recorded-evidence schema v2 and migration from v1 |
| [04-scoring.md](04-scoring.md) | feature definitions, weights, split grouping, decision rule |
| [05-benchmark.md](05-benchmark.md) | benchmark generator, ground truth, calibration, CI subset |
| [06-learned-scorer.md](06-learned-scorer.md) | offline trainer, weights file format, runtime inference |
| [07-phases.md](07-phases.md) | ordered implementation phases with acceptance criteria |
| `tests/` | ready-made unittest files, written *before* the implementation |

## How to use this folder

1. Implement the phases of [07-phases.md](07-phases.md) **in order**. Each
   phase is independently landable and names the test files that verify it.
2. The test files in `tests/` are written against the APIs specified in
   these documents. As each phase lands, **move** (git mv) the phase's test
   file from `docs/tnp_fix/tests/` into `SMTests/` and import its classes
   in `TestSheetMetal.py`. Until moved they are not part of the suite, so
   the suite stays green at every commit.
3. The prepared tests are the acceptance bar. Where a test asserts a
   *behavioural* outcome (e.g. "the split edge resolves to 2 pieces with
   confidence ≥ 0.75"), tune `DEFAULT_WEIGHTS` in
   [04-scoring.md](04-scoring.md) until it passes — do not weaken the
   test. Where a test asserts "correct **or refused**, never wrong", a
   refusal is an acceptable outcome; a wrong element is not.

## Running tests

```
# whole suite (114 tests before this work; ~20 s)
flatpak run --command=FreeCADCmd org.freecad.FreeCAD -t TestSheetMetal

# one module / one case
flatpak run --command=FreeCADCmd org.freecad.FreeCAD -t SMTests.testTNP
flatpak run --command=FreeCADCmd org.freecad.FreeCAD -t SMTests.testRefNameParser
```

With a non-flatpak FreeCAD use its `FreeCADCmd` the same way. The flatpak
cannot read the host's `/tmp`: any script passed to it must live under
`~/.var/app/org.freecad.FreeCAD/` (the repository itself is under that
path). Benchmark output files must be written inside the repository
directory for the same reason.

Test conventions (from [../testing.md](../testing.md)): build documents in
`setUp`, close in `tearDown`; find elements by geometry
(`SMTests.helpers.findElement`), never by hard-coded index; after a
recompute check `"Invalid" in obj.State` (a failed feature keeps its old
shape, so geometry checks alone can pass by accident); derive expected
values from the definition where possible.

## Definition of done

* All phases of [07-phases.md](07-phases.md) merged; all prepared tests
  moved into `SMTests/`, imported in `TestSheetMetal.py`, and passing.
* The full suite passes.
* The benchmark of [05-benchmark.md](05-benchmark.md) reports, per edit
  type, correct / refused / wrong rates, with the wrong-rate bound met.
* `docs/reference-recovery-solution.md` written (phase 8) with the
  measured numbers, answering the five open questions of
  `docs/reference-resolution-problem.md` section 6.

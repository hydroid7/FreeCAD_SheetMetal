# 07 Implementation phases

Each phase is independently landable. After **every** phase the full suite
must pass:

```
flatpak run --command=FreeCADCmd org.freecad.FreeCAD -t TestSheetMetal
```

"Move in `tests/X.py`" means: `git mv docs/tnp_fix/tests/X.py SMTests/X.py`
and import its test classes in `TestSheetMetal.py`.

## Phase 1 — mechanical extraction

Create `SheetMetalRefRecovery.py`; move the resolver block
(`SheetMetalTools.py:1162–1430` minus `smGetShadowNames` and the
tag/element-key helpers) into it; leave `smResolveSubElements` as the
one-line shim and re-export the moved names from `SheetMetalTools`
(see 01). Zero behaviour change.

*Acceptance:* full suite green (`TestTNPRecovery` in particular);
`git grep -n "smFindLostElement\|smHistoryCandidates\|smGeometryMatches"`
shows no caller importing them from the old location without the alias.

## Phase 2 — name parser and hash decoding

Implement 02 (`parseMappedName`, `expandHashes`, `nameRelation`,
`sharedOpPrefix`, `opEditDistance`, `historyCandidatesFromMap`,
`historyCandidates`). Rewire the resolver's candidate generation to
`historyCandidates`; behaviour for today's cases must not change.

*Acceptance:* move in `tests/testRefNameParser.py`; full suite green;
additionally assert manually (or as a temporary script) that on
`SMTests/data/HoleSplitsEdge.FCStd` as saved (Diameter 36, `?Edge98` on
`Bend003`) the candidates are the two pieces of the split 53 mm edge.

## Phase 3 — evidence v2

Implement 03 (`recordEvidence`, `upgradeEvidence`); record v2 on every
followed resolution; resolution logic still consumes only the v1 fields.
Measure the per-reference JSON size on HoleSplitsEdge and note it for
phase 8.

*Acceptance:* full suite green; `SMTests/testPersistence.py` extended to
assert a saved+reloaded feature keeps a `"v": 2` entry in
`smRefGeometry`.

## Phase 4 — scoring and decision (legacy refuse mode)

Implement 04 end to end inside `resolveLostElement`, plus the console
line and the `smRefReport` property of 01. Legacy mode only (refusal =
warn + old index). This removes the `matching or found` fallback — the
known wrong-answer source — by construction.

*Acceptance:* move in `tests/testRefScoring.py`, `tests/testRefRecovery.py`
(its strict-mode test stays `skip`ped until phase 7, see the file) and
`tests/testTNPHoleSplitsEdge.py`; full suite green, including the old
`TestTNPRecovery.testSplitEdgeIsFollowed` (still exactly 2 pieces). Tune
`DEFAULT_WEIGHTS` until the behavioural tests pass; do not weaken tests.

## Phase 5 — benchmark and calibration

Implement 05 (`SMTests/benchmarkTNP.py`); run it over ≥ 3000 lost-ref
cases; run `calibrate` and commit the resulting `T_ACCEPT`, `T_MARGIN`
and group scales; create `SMTests/testTNPBenchmark.py` with the pinned CI
subset and import it in `TestSheetMetal.py`. Keep the JSONL (or the seed
range to regenerate it) for phase 6.

*Acceptance:* full suite + CI subset green; benchmark report shows the
wrong-rate bound met (raise thresholds until it is — refusals are
acceptable, wrong answers are not).

## Phase 6 — learned scorer

Implement 06: `scripts/train_ref_scorer.py`, train on the benchmark
JSONL, commit `resources/refRecoveryWeights.json`, implement
`loadWeights`/`scoreFeaturesLearned` with the fallback and the
`RefRecoveryLearned` preference.

*Acceptance:* move in `tests/testRefLearnedWeights.py`; the three
validation gates of 06; full suite green with and without the weights
file.

## Phase 7 — strict mode

Implement the `smRefStrict` property, the `RefRecoveryStrict` preference
and the `SMException` path (01). Set `smRefStrict = True` on newly
created features in the task panels / `addNewObject` paths (existing
documents are untouched).

*Acceptance:* unskip the strict-mode test in `testRefRecovery.py`; full
suite green (all pre-existing tests run legacy mode and must not change).

## Phase 8 — solution document

Write `docs/reference-recovery-solution.md`: architecture summary,
evidence schema + measured size cost, parser grammar findings, feature
table + calibrated weights, the benchmark table (correct/refused/wrong per
edit type), user-facing behaviour and the strict-mode transition, learned
scorer results, and the upstreaming note (the parser/scorer operate on
`Part.Shape` + hasher only; the caller table and `kindPrior` are the only
workbench-specific parts — relevant to FreeCAD's own
`rescueDriftedElement` fallback). This answers the five open questions of
`docs/reference-resolution-problem.md` section 6. Update `docs/TNP.md`
section 2.5 to describe the new resolver and link the document.

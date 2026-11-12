# 05 Benchmark generator and calibration

Purpose: measure, per edit type, the rates of **correct**, **refused** and
**wrong** resolutions; calibrate `T_ACCEPT`, `T_MARGIN` (and coarse weight
scaling); and produce labelled training data for the learned scorer (06).
Wrong resolutions are the metric that matters; the target is a Wilson 95%
upper bound ≤ 0.1%, which needs ≥ ~3000 lost-reference cases (seeds are
cheap).

## Files

* **`SMTests/benchmarkTNP.py`** — generator, runner, calibration. *Not*
  imported by `TestSheetMetal.py`; run manually:

  ```
  flatpak run --command=FreeCADCmd org.freecad.FreeCAD -t SMTests.benchmarkTNP
  ```

  Seed range and output path come from environment variables
  (`SM_BENCH_SEEDS=0:500`, `SM_BENCH_OUT=SMTests/data/bench.jsonl`) because
  `-t` passes no arguments. Output must stay inside the repository
  directory (the flatpak cannot write the host `/tmp`).
* **`SMTests/testTNPBenchmark.py`** — fast CI subset (< 30 s), imported by
  `TestSheetMetal.py` (phase 5).

## Chain generator

```python
def buildChain(doc, rng: random.Random) -> Chain
```

Grammar over the existing builders in `SMTests/helpers.py`
(`makePlate`, `makeWall`, `findElement`, `backEdge`, `rightEdge`,
`topFace`, `addFeature`):

1. Base: `makePlate` with a randomized outline (plate 60–140 × 30–70,
   optionally one chamfered corner).
2. 1–3 features drawn from: Wall on a random qualifying top edge
   (`makeWall`, random length/gaps), Hem on an edge, Extend on a side
   face, a `Part::Cut` with a tagged `Part::Cylinder` "hole" through a
   wall (the pattern of `TestTNPRecovery.setUp`, `SMTests/testTNP.py:
   499–519`), an `ExtrudedCutout` from a small sketch circle.
3. Probe: either a real Wall on a referenced edge, or a bare
   `App::FeaturePython` with an `App::PropertyLinkSub` named `Link`
   pointing at one element (the pattern of
   `TestTNPReferences.assertReferenceFollows`, `SMTests/testTNP.py:
   386–402`) — resolvable via `resolveSubElements(ref, "Link")`.

`Chain` records, for each probe reference, the carrier signature of the
referenced element (the `edgeSignature` pattern, `SMTests/testTNP.py:
50–56`, generalized to faces by plane/cylinder carrier and to vertices by
point) and its extent interval on that carrier.

## Edits

```python
EDITS = {
  "hole_resize":  ...,   # tool.Radius over a range crossing the referenced edge
  "sketch_move":  ...,   # sketch.moveGeometry of one or two outline points
  "gap_toggle":   ...,   # wall.gap1/gap2 0 <-> 2..8
  "relief_type":  ...,   # wall.reliefType "Rectangle" <-> "Round" (+ gap)
  "chamfer_add":  ...,   # add a corner line segment to the base sketch
  "wall_length":  ...,   # wall.length +/- 5..20
}
```

Each edit is a callable `apply(fraction)` with `fraction` in `[0, 1]`
(0 = original value, 1 = final value), so it can be applied in small
steps, plus a human-readable description.

## Ground truth

```python
def groundTruth(chain, edit) -> "list[str] | None"
```

Small-step tracking: apply the edit in 8 increments. After each increment
recompute and require that FreeCAD still follows the reference by name
(the sub does not start with `?`); update the tracked carrier signature
and extent from the followed element (this absorbs legitimate movement,
like `testWall1Length` moving the line up by the length delta,
`SMTests/testTNP.py:160–166`). If a step loses the name early, fall back
to construction knowledge: the generator knows which sketch line or tool
face produced the element and can recompute the expected carrier from the
feature parameters. After the final step, the truth is the set of elements
of the final shape lying on the tracked carrier within the tracked extent
(tolerance `relTol(scale)`), or `None` when nothing remains there — then
the correct resolver answer is a refusal.

The per-reference label for a candidate element: `1` if it is in the truth
set, else `0`. `groupLabel` is `"all"` when the feature takes all elements
(wantsMany) and the truth set has several members, `"one"` when a
single-element feature should take the largest piece, `null` otherwise.

## Runner and report

```python
def runBenchmark(seeds, outPath) -> dict
```

For each seed: build the chain, snapshot it (`Document.saveCopy` is not
needed — rebuild from the seed instead, documents are cheap), apply each
edit in one jump (fraction 1.0 directly, a fresh chain per edit), recompute
and classify every lost reference:

* **correct** — resolver output equals the truth set (or, for
  `wantsMany=False`, the largest truth element); truth `None` and status
  `refused` also counts as correct;
* **refused** — status refused while truth existed;
* **wrong** — anything else (extra element, missing element, wrong
  element, or recovered while truth was `None`).

References that FreeCAD follows by itself are skipped (they never reach
the resolver). The report prints a per-edit-type table and dumps one JSON
line per (lost reference, candidate):

```json
{"case": "s0042-hole_resize", "edit": "hole_resize", "kind": "Edge",
 "candidate": "Edge14", "features": {"sameOrigin": 1.0, "...": 0.9},
 "label": 1, "groupLabel": "all"}
```

## Calibration

```python
def calibrate(jsonlPath) -> dict
```

Grid search `T_ACCEPT` ∈ [0.6, 0.9] step 0.01 × `T_MARGIN` ∈ [0.05, 0.3]
step 0.01, plus a coarse scale factor per feature *group* (name, geom,
topo ∈ {0.5, 1.0, 2.0}), replaying `decide` over the dumped rows (no
FreeCAD needed for the replay — rows carry the features). Objective:
maximize the correct rate subject to the Wilson 95% upper bound of the
wrong rate ≤ 0.1%, overall and per edit type. Print the resulting table
(for the final solution document) and the chosen constants; commit them
into `DEFAULT_WEIGHTS` / `T_ACCEPT` / `T_MARGIN`.

## CI subset (`SMTests/testTNPBenchmark.py`)

* `TestTNPGenerated`: ~15 fixed seeds × the two historically worst edit
  types (`hole_resize`, `sketch_move`), asserting the outcome is correct
  or refused — never wrong — and that specific seeds known to be correct
  at calibration time stay correct (regression pinning).
* The HoleSplitsEdge sweep lives in its own prepared file
  (`tests/testTNPHoleSplitsEdge.py`, phase 4) — do not duplicate it here.

Runtime budget: < 30 s for the subset; the full benchmark run is manual
and unbounded.

# 06 Learned scorer

Replaces the hand-tuned weighted sum of 04 with a logistic regression
trained on the benchmark data, while keeping everything else — candidate
generation, split grouping, decision rule, refusal semantics,
explanations — unchanged. Inference is pure Python, deterministic, with
an automatic fallback to `DEFAULT_WEIGHTS`.

## Training data

The JSONL dumped by `SMTests/benchmarkTNP.py` (05): one row per
(lost reference, candidate) with the feature dict and a 0/1 label.
Generate 10⁴–10⁵ rows by widening the seed range. Split train/validation
**by seed** (`case` prefix), never by row — rows of one case are
correlated.

## Missing features

The runtime omits features whose inputs are unavailable (04). A logistic
model needs a fixed-length vector, so every feature `f` gets a paired
indicator `miss_f`:

* feature present: `x_f = value`, `x_miss_f = 0`
* feature absent: `x_f = 0`, `x_miss_f = 1`

The trainer builds the same columns from the JSONL (absent key = missing).
This makes train/serve behaviour structurally identical — no imputation by
means, no renormalization mismatch.

## Trainer

`scripts/train_ref_scorer.py` — offline only, numpy allowed, no FreeCAD
needed (it reads the JSONL). Plain logistic regression (L2, lambda chosen
on the validation seeds), features as above. Outputs
`resources/refRecoveryWeights.json`:

```json
{
  "version": 1,
  "features": ["sameOrigin", "relation", "..."],
  "w": {"sameOrigin": 1.92, "miss_sameOrigin": -0.31, "...": 0.0},
  "b": -3.17,
  "thresholds": {"accept": 0.78, "margin": 0.12}
}
```

`features` must list exactly the scoreable feature names the runtime
emits (the keys of `DEFAULT_WEIGHTS`); `w` holds a weight for every
feature and every `miss_` indicator. `thresholds` come from re-running the
calibration of 05 on the learned scores.

## Runtime

```python
def loadWeights(path=None) -> "LearnedWeights|None"
    # default path: <workbench>/resources/refRecoveryWeights.json
    # returns None (-> hand-tuned DEFAULT_WEIGHTS are used) when the file
    # is absent, unreadable, has an unknown version, or its feature list
    # does not exactly match the runtime's feature registry; logs one
    # PrintLog line saying which.

def scoreFeaturesLearned(features: dict, lw) -> float
    # z = lw.b + sum over registry features of
    #       (lw.w[f] * features[f] if f in features else lw.w["miss_" + f])
    # return 1 / (1 + math.exp(-z)), plain float64
```

`scoreCandidate` (04) uses `scoreFeaturesLearned` when `loadWeights()`
returned weights, else `scoreFeatures`. The moved-element down-weighting
rule of 04 does not apply to the learned scorer (the model sees the name
features and learns the interaction itself); the split-group score formula
and `decide` are shared. Load the weights file once per session
(module-level cache); a preference
`Mod/SheetMetal/RefRecoveryLearned` (default `True`) allows forcing the
hand-tuned scorer.

## Validation gates (all must hold before the weights file is committed)

1. Wrong-rate Wilson 95% upper bound ≤ 0.1% on held-out seeds, overall
   and per edit type, and not worse than the calibrated hand-tuned scorer.
2. Determinism: resolving the same context twice yields byte-identical
   `Resolution`s (covered by `tests/testRefScoring.py` and
   `tests/testRefLearnedWeights.py`).
3. The full test suite passes with the weights file present, and again
   with it renamed away (fallback path).

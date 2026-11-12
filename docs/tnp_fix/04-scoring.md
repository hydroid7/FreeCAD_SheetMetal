# 04 Scoring and decision

One scoring function for every candidate (no per-repair strategy classes;
that design was considered and dropped for simplicity). Structure:

```python
def nameFeatures(old: "MappedName|None", cand: "MappedName|None",
                 shape=None) -> dict
def geometryFeatures(evidence: "dict|None", element, scale: float) -> dict
def topologyFeatures(ctx, name: str) -> dict
def extractFeatures(ctx, name: str) -> dict      # union of the three + kindPrior
def scoreFeatures(features: dict, weights: "dict|None" = None) -> float
def scoreCandidate(ctx, name: str) -> Candidate
def splitGroups(candidates: "list[Candidate]") -> "list[Candidate]"  # input + groups
def decide(candidates, *, wantsMany: bool, sizeOf) -> Resolution
```

All feature values are in `[0, 1]`. A feature whose inputs are missing
(no evidence field, no mapped name, hasher absent...) is **not emitted**,
and `scoreFeatures` removes its weight from the normalizer:

```python
def scoreFeatures(features, weights=None):
    w = weights or DEFAULT_WEIGHTS
    used = {k: v for k, v in features.items()
            if not k.startswith("_") and k in w}
    if not used:
        return 0.0
    return sum(w[k] * v for k, v in used.items()) / sum(w[k] for k in used)
```

Keys starting with `_` are auxiliary (not scored): `_midParam` (projection
of the candidate's midpoint onto the old carrier, used for ordering group
members), `_extent` (candidate Length/Area).

## Relative tolerance

```python
def relTol(scale):                     # scale = shape.BoundBox.DiagonalLength
    return min(max(scale * 1e-5, 1e-4), 1e-2)      # mm
```

This replaces the single hard-coded `smRefTolerance = 1e-4`.

## Features

### name features (need `ctx.oldMapped` and the candidate's mapped name)

| feature | value |
|---|---|
| `sameOrigin` | 1.0 if origins equal (structurally, or by expanded string), else 0.0 |
| `relation` | by `nameRelation` (02): same 1.0, copy 1.0, modified 0.9, ancestor 0.6, generated 0.4, neighbour 0.2, unrelated 0.0 |
| `prefixRatio` | `sharedOpPrefix / max(1, len(old.ops))` |
| `opEditSim` | `1 / (1 + opEditDistance(old, cand))` |
| `sameSourceTag` | 1.0 if `shape.getElementHistory` returns the same source tag for both names, 0.0 if different; omitted when either call fails or returns no tag |

### geometry features (need `evidence["geom"]`; `geometryFeatures` takes the element, not the shape)

Let `g` be the old signature, `t = relTol(scale)`.

| feature | value |
|---|---|
| `typeMatch` | 1.0 same `TypeId`; 0.5 for the compatible pairs Line↔Arc/Circle and Plane↔Cylinder; else 0.0 |
| `carrierFit` | `exp(-d / t)` where `d` is the carrier distance in mm: line — max distance of the candidate's vertices to the old infinite line; circle/arc — `max(|Δcenter|, |Δradius|, (1-|axis·axis'|)·radius)`; plane — `max(|(pos-pos0)·n0|, (1-|n·n0|)·scale·0.01)`; cylinder — `max(distance of axis point to old axis line, |Δradius|, (1-|axis·axis0|)·radius)`; vertex — point distance. Monotone in the deviation, 1.0 for an exact fit |
| `containment` | fraction of the candidate lying inside the old extent. Lines: project the candidate's vertices onto the old carrier → interval `[a,b]`; old segment `[0,L]`; `containment = overlap_len / (b-a)` (1.0 for a degenerate candidate inside). Faces: per-axis bound-box overlap product over axes where the old box extent > t, divided by the candidate's box measure. Vertices: 1.0 within t of the old point, else from the distance via `exp(-d/t)` |
| `overlap` | fraction of the **old** extent covered by the candidate (same intersection, divided by `L` resp. the old box measure) |
| `extentRatio` | `min(e, e0) / max(e, e0)` of lengths/areas (omit for vertices, or when `evidence["extent"]` is None) |
| `midDist` | `exp(-|mid - mid0| / max(extent0, t))` (needs `evidence["mid"]`) |
| `dirDot` | abs of the dot product of unit directions (lines) or unit normals (planes) or axes (circles, cylinders) |

### topology features (need `ctx.shape` and the v2 fingerprint)

| feature | value |
|---|---|
| `adjCount` | `1 - min(1, abs(n - n0) / 4)` over the number of adjacent faces (edge/vertex) or edges (face) |
| `adjTypes` | Jaccard similarity of the surface/curve `TypeId` multisets |
| `adjNames` | fraction of the old non-empty `adjNames` for which some neighbour of the candidate has `nameRelation` in {same, copy, modified} (expand both sides) |
| `convexity` | 1.0 if the candidate edge's dihedral sign equals `evidence["convex"]`, 0.0 otherwise; omitted when either side is None |

### context feature

| feature | value |
|---|---|
| `kindPrior` | 1.0 when the candidate's geometric type is what `ctx.featureKind` typically references (bend/wall features: a straight edge adjacent to at least one plane; unfold/fold/cutout: a plane), 0.5 otherwise; omitted when `featureKind` is unknown |

## Default weights

```python
DEFAULT_WEIGHTS = {
    "sameOrigin": 2.0, "relation": 2.0, "prefixRatio": 1.0,
    "opEditSim": 0.5, "sameSourceTag": 0.5,
    "typeMatch": 1.5, "carrierFit": 3.0, "containment": 1.5,
    "overlap": 0.5, "extentRatio": 0.5, "midDist": 0.5, "dirDot": 1.0,
    "adjCount": 0.25, "adjTypes": 0.5, "adjNames": 1.0, "convexity": 0.5,
    "kindPrior": 0.5,
}
T_ACCEPT = 0.75
T_MARGIN = 0.15
```

These are starting values; phase 5 calibrates them (and the thresholds) on
the benchmark, and phase 6 can replace the whole weighted sum with the
learned scorer (06). Sanity anchor: for the HoleSplitsEdge split piece
(sameOrigin 1, relation 0.9, carrier/type/containment 1, overlap ≈ 0.37)
these weights give ≈ 0.84 — comfortably above `T_ACCEPT`; an unrelated
edge scores near 0.

**Moved-element rule** (applied inside `scoreCandidate`): when the name
evidence is strong — `sameOrigin == 1` and `relation` ∈ {same, copy,
modified} and `prefixRatio ≥ 0.8` — the carrier may have moved
legitimately (an upstream dimension changed). Halve the weights of
`carrierFit`, `containment`, `overlap` and `midDist` for that candidate
(copy the weights dict; determinism is unaffected). This lets a renamed
*and* moved element pass on its name + direction + topology, while pure
geometry matches still need the full carrier fit.

## Split grouping

After scoring the individual candidates:

```python
def splitGroups(candidates):
    members = [c for c in candidates
               if c.features.get("carrierFit", 0) > 0.5
               and c.features.get("containment", 0) > 0.9]
    if len(members) >= 2:
        members.sort(key=lambda c: c.features.get("_midParam", 0.0))
        coverage = min(1.0, sum(c.features.get("overlap", 0) for c in members))
        score = min(c.score for c in members) * (0.9 + 0.1 * coverage)
        candidates = candidates + [Candidate(
            elements=tuple(e for c in members for e in c.elements),
            score=score, repairKind="split", ...)]
    return candidates
```

`containment`, not coverage, is the membership gate: at Hole.Diameter = 50
the single 7.6 mm remnant of the 53 mm edge has coverage ≈ 0.14 but
containment 1.0 and must be recoverable (as a single candidate — a group
needs ≥ 2 members).

## repairKind labelling (descriptive only — report and console text)

Computed for the winning candidate, first match wins:

1. group candidate → `"split"`
2. `overlap > 0.9` and (`relation == "ancestor"` or candidate extent >
   1.5 × old extent) → `"merge"`
3. name strong (the moved-element rule fired) and `carrierFit < 0.5` →
   `"moved"`
4. `typeMatch == 0.5` → `"type-change"`
5. no name features present → `"geometry-only"`
6. otherwise → `"drift"`

## Decision

```python
def decide(candidates, *, wantsMany, sizeOf):
    if not candidates:
        return Resolution("refused", [], 0.0, "none", "no candidates")
    ranked = dedupeByElements(candidates)           # keep max score per tuple
    ranked.sort(key=lambda c: (-round(c.score, 9), c.elements))
    best = ranked[0]
    if best.score < T_ACCEPT:
        return refusal(best)
    rival = next((c for c in ranked[1:]
                  if not set(c.elements) <= set(best.elements)
                  and not set(best.elements) <= set(c.elements)), None)
    if rival is not None:
        if round(best.score, 9) == round(rival.score, 9):
            return refusal(best)                     # exact tie, different answer
        if best.score - rival.score < T_MARGIN:
            return refusal(best)                     # ambiguous
    elements = list(best.elements)
    if not wantsMany and len(elements) > 1:
        elements = [max(elements, key=sizeOf)]       # largest piece, group confidence
    return Resolution("recovered", elements, best.score, best.repairKind, ...)
```

Subset/superset candidates (a piece of the winning group, or the group
containing the winner) do not count as rivals — they are the same answer
at a different granularity. A refusal carries the best score and
repairKind so the message can say how close it was.

Determinism: ranking uses `(-round(score, 9), elements)`; `sizeOf` is
`shape.getElement(n).Length` / `.Area` / `0.0` as in the current code.

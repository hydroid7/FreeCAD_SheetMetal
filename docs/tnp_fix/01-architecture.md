# 01 Architecture

## Module layout

Create a new top-level module **`SheetMetalRefRecovery.py`** next to
`SheetMetalTools.py` (the workbench has a flat module layout, and
SheetMetalTools is already 2400+ lines). It owns:

```
SheetMetalRefRecovery.py
├── mapped-name parsing     parseMappedName, expandHashes, nameRelation, ...   (02)
├── evidence                recordEvidence, upgradeEvidence, SCHEMA_VERSION    (03)
├── candidate generation    historyCandidates / historyCandidatesFromMap       (02)
├── feature extraction      nameFeatures, geometryFeatures, topologyFeatures,
│                           extractFeatures                                    (04)
├── scoring + decision      scoreFeatures, scoreCandidate, splitGroups,
│                           decide, DEFAULT_WEIGHTS, loadWeights               (04, 06)
└── entry points            resolveSubElements(fp, propName), resolveLostElement(ctx)
```

What moves out of `SheetMetalTools.py` (currently lines 1162–1430):
`smHistoryCandidates`, `smGeometrySignature`, `smGeometryMatches`,
`smFindLostElement`, `_sameLineDistance`, `_isSpecificName`,
`_loadRefGeometry`, `_storeRefGeometry`, and the constants
`smRefGeometryProp`, `smRefTolerance`. Keep thin re-export aliases in
`SheetMetalTools` for one release (external scripts may import them).

What stays in `SheetMetalTools.py`: `smGetShadowNames` (also useful
elsewhere), `smTagTool`, `smElementKey`, `getElementFromTNP`, and
`smResolveSubElements` itself as a **one-line shim**:

```python
def smResolveSubElements(fp, propName="baseObject"):
    import SheetMetalRefRecovery
    return SheetMetalRefRecovery.resolveSubElements(fp, propName)
```

None of the 13 callers change.

## Callers (verified, with what they need)

| caller | kind | uses |
|---|---|---|
| `SheetMetalCmd.py:1898` (Wall) | edges/faces | all elements |
| `SheetMetalHem.py:353` | edges | all |
| `SheetMetalExtendCmd.py:261` | faces | all |
| `SheetMetalFoldCmd.py:277` | faces | all |
| `SheetMetalBend.py:132` | edges | all |
| `SheetMetalJunction.py:88` | edges | all |
| `SheetMetalCornerReliefCmd.py:727` | edges | all |
| `SheetMetalRelief.py:139` | vertices | all |
| `SketchOnSheetMetalCmd.py:204` | faces | all |
| `SheetMetalFromSolid.py:718` | faces | all |
| `ExtrudedCutout.py:145` | one face | `[0]` |
| `SheetMetalFormingCmd.py:172` | one face | `[0]` |
| `SheetMetalUnfoldCmd.py:583` | one face | `[0]` |

Encode this as a module-level dict mapping the feature proxy class name to
`wantsMany` (True except `ExtrudedCutout`, `SMBendWall` in
SheetMetalFormingCmd — note the Forming proxy class is also called
`SMBendWall`; key by `type(fp.Proxy).__module__ + "." +
type(fp.Proxy).__qualname__` to disambiguate — and `SMUnfold`). Unknown
proxies (e.g. bare probe objects in tests) default to `wantsMany=True`.

## Data types

```python
SCHEMA_VERSION = 2

@dataclass
class ResolutionContext:
    shape: "Part.Shape"            # the new upstream solid S'
    kind: str                      # "Edge" | "Face" | "Vertex"
    oldMapped: "MappedName|None"   # parsed saved mapped name (02), None if none stored
    evidence: "dict|None"          # v2 evidence dict (03), None if none stored
    featureKind: str               # proxy class identifier, "" if unknown
    wantsMany: bool
    scale: float                   # shape.BoundBox.DiagonalLength

@dataclass
class Candidate:
    elements: "tuple[str, ...]"    # one index name, or several for a split group
    score: float
    repairKind: str                # descriptive label, see 04
    explanation: str               # human-readable, translated
    features: dict                 # feature name -> value (aux keys start with "_")

@dataclass
class Resolution:
    status: str                    # "recovered" | "refused"
    elements: "list[str]"          # empty when refused
    confidence: float              # winning score, or best score when refused
    repairKind: str
    explanation: str
```

## Pipeline

`resolveSubElements(fp, propName)` keeps the contract of the current
implementation (`SheetMetalTools.py:1377–1430`): iterate the subs of the
link property; pass through followed references and record evidence for
them (03); for each lost reference (`?EdgeN`) build a `ResolutionContext`
and call `resolveLostElement`, then act on the `Resolution` as described
under "Refuse semantics". Store updated evidence with the same
change-detection as today (only write the property when values changed —
it is an `App::PropertyStringList` named `smRefGeometry`, hidden, status
`["Output"]`). Deduplicate the final list with `dict.fromkeys` as today.

`resolveLostElement(ctx)` is the unit-testable core:

1. **Candidate generation.** `historyCandidates(ctx.shape, ctx.oldMapped,
   ctx.kind)` (02). If it returns nothing and evidence with geometry is
   available, prefilter all elements of `ctx.kind` by a cheap geometry
   test (carrier distance under `64 * relTol`, bound boxes of faces must
   intersect the old box enlarged by 10% of its diagonal) — the exact
   prefilter only needs to be generous, scoring decides. Cap the candidate
   set at 32 by keeping the ones with the best `carrierFit` (04); the cap
   keeps the cost bounded on pathological parts.
2. **Feature extraction + scoring.** `scoreCandidate(ctx, name)` for each
   candidate (04).
3. **Split grouping.** `splitGroups(candidates)` may add group candidates
   (04).
4. **Decision.** `decide(candidates, wantsMany=ctx.wantsMany,
   sizeOf=...)` (04) returns the `Resolution`.

## Refuse semantics and compatibility

Two modes. The mode is read per feature:

* hidden `App::PropertyBool` **`smRefStrict`** on the feature if present
  (added lazily like `smRefGeometry`; task panels set it to `True` on
  *newly created* features only after phase 7), otherwise
* the boolean parameter **`Mod/SheetMetal/RefRecoveryStrict`**
  (`FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/SheetMetal")`),
  default `False`.

| | status `recovered` | status `refused` |
|---|---|---|
| legacy (default) | use `Resolution.elements`, `PrintWarning` one line | keep the old index, `PrintError` one line |
| strict | same | raise `SheetMetalTools.SMException(message)` |

Raising inside the feature's `execute()` is the one mechanism that works
for all 13 callers without touching them: FreeCAD catches it, marks the
feature *Invalid* (touched + error), keeps the previous shape and shows
the message in the report view and the tree tooltip. In legacy mode the
old-index fallback preserves today's behaviour exactly — including the
invariant that the returned list is never empty.

Behavioural change in **both** modes compared to the old resolver: a
candidate set whose best score is below the accept threshold is no longer
silently used. The old code (`smFindLostElement`,
`SheetMetalTools.py:1348`) fell back to unfiltered name candidates even
when the recorded geometry contradicted all of them (`found = matching or
found`) — that line is the known source of confident wrong answers and
must not be reproduced.

## Console and report output

Exactly one line per lost reference (replacing the current two-variant
warning):

```
Wall2: lost Edge98 of Hole — split: using Edge101 + Edge105 (confidence 0.93)
Wall2: lost Edge98 of Hole — no safe match (best 0.41, drift); re-select the base edge of Wall2
```

The first via `FreeCAD.Console.PrintWarning`, the second via
`PrintError`. All strings go through
`translate("SheetMetalRefRecovery", ...)` with `.format()` placeholders,
like the existing warnings.

Additionally write a machine-readable report to a hidden
`App::PropertyStringList` **`smRefReport`** on the feature (created lazily,
status `["Output"]`, same pattern as `smRefGeometry`): one JSON string per
sub of the link property, `""` for subs that were followed normally,
otherwise

```json
{"status": "recovered", "old": "Edge98", "elements": ["Edge101", "Edge105"],
 "confidence": 0.93, "repairKind": "split", "explanation": "..."}
```

Clear the property (set all entries `""`) when every reference follows.
This property is what a future task-panel highlight will read; no GUI work
is part of this package.

## Determinism requirements

* No iteration over `set`/`dict` where order reaches the result; sort
  candidate lists by `(-round(score, 9), elements)`.
* All floats are plain Python floats (float64); no randomness anywhere in
  the resolver.
* Resolving the same context twice must give an identical `Resolution`
  (asserted by `tests/testRefScoring.py`).

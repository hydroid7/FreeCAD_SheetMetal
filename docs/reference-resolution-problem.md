# Problem statement: re-finding referenced geometry after a model change

This document describes an open problem in the FreeCAD SheetMetal
workbench in a self-contained way, so that solutions (rule-based,
probabilistic or learned) can be proposed without reading the code. The
mechanism and the current state are described in more detail in
[TNP.md](TNP.md); the tests in [testing.md](testing.md).

## 1. The problem in one paragraph

A parametric CAD model is a chain of features. Each feature takes the
output solid of an earlier feature and a *reference* to some of its faces,
edges or vertices ("put a wall on this edge"). When the user changes an
upstream parameter (a hole diameter, a sketch dimension, a gap), every
downstream solid is rebuilt from scratch, and the referenced element must
be found again in the new solid. The new solid has no object identity in
common with the old one; only geometry and a recorded construction history
are available. If the wrong element is chosen, the downstream feature is
silently built in the wrong place ("the bend jumped to another edge").
This is known as the topological naming problem (TNP).

**Goal:** given the old reference and the new solid, return the element(s)
the user would consider "the same", or report that there is none, with very
few wrong answers.

## 2. What is available when a reference must be resolved

At recompute time of a downstream feature F, which references elements of
an upstream solid S:

| information | always? | notes |
|-------------|---------|-------|
| new solid S' (B-rep: faces, edges, vertices, adjacency, exact geometry) | yes | OpenCASCADE shape, queried from Python |
| old index name, e.g. `Edge98` | yes | position in S's edge list; meaningless after a change |
| old *mapped name* of the element | usually | construction history, see 2.1 |
| mapped names of every element of S' | mostly | some elements may be unnamed |
| geometry of the old element (line, endpoints, circle, plane, bound box...) | only if recorded | SheetMetal now records it after every successful resolution |
| the old solid S | no | not kept; could be recorded at a cost |
| the change the user made (which parameter, old/new value) | no | could be recorded |
| which feature F it is and what it needs (one edge, several edges, one face) | yes | |
| user confirmation | no | recompute is non-interactive; a warning can be shown |

### 2.1 Mapped names

FreeCAD's element map gives every element a history string. Examples:

```
g3;SKT;:H100f,E;:G;XTR;:H100f:7,F;:U;XTR;:H100f:7,E;:H,E
#312:9;:H1013,E
#312:9;:M;CUT;:H1013:7,E
#312:9;:M2;CUT;:H1013:8,E
```

* Read left to right: the origin first (`g3;SKT` = geometry 3 of a sketch;
  `#312` = a hashed long prefix, stored in a document string table), then
  each operation applied (`:G` generated, `:M` modified, `:M2` second
  result of a modification, `:U`/`:L` upper/lower neighbour, `XTR`
  extrude, `CUT`, `FUS` fuse..., `:H<hex>` tag of the object that did it).
* The full name is matched **exactly**. Any change in the history (an extra
  cut touches the element, a refine step merges it, it is split into two)
  produces a different name and the reference is reported lost.
* Long names are hashed (`#312`), so similarity between names is only
  visible after decoding through the string table.

### 2.2 What FreeCAD itself does when the name is missing

1. Search for an element with the same vertices (geometric identity).
   Fails as soon as the element was cut or resized.
2. (newer FreeCAD only) search with a growing tolerance.
3. Otherwise mark the reference lost (`?Edge98`) and keep the old index,
   which now points at an arbitrary element.

## 3. A concrete failing case

File: `SMTests/data/HoleSplitsEdge.FCStd` (a PartDesign body).

```
Sketch -> BaseBend -> Bend -> Bend001 -> Bend002 -> Sketch001 -> Hole -> Bend003
```

Bend003 is a wall on a straight 53 mm edge at the bottom of a wall made by
Bend002. The Hole (diameter D) passes close to that edge.

| D | what happens to the edge | its name | old behaviour |
|---|--------------------------|----------|---------------|
| 20 | untouched | `#312:9;:H1013,E` | correct |
| 30, 36, 40 | split by the hole into two collinear pieces (19.4 + 11.5 mm at D=30) | `#312:9;:M;CUT;...:7,E`, `#312:9;:M2;CUT;...:8,E` | reference lost, wall built on an unrelated 1 mm or 14 mm edge |
| 50 | one piece left (7.6 mm) | `#312:9;:M;CUT;...:7,E` | lost, wrong edge |

The user's intent is clear in every row: "the wall stays on that line".
Changes like this (holes, cutouts, chamfers, gaps and reliefs growing into
an edge) are very common in sheet metal design.

## 4. Current solution (rule-based, implemented)

`SheetMetalTools.smResolveSubElements` (branch `reference-recovery`):

1. If FreeCAD followed the reference, use it and record its geometry.
2. If it is lost, read the old mapped name and shorten it one operation at
   a time from the right until some elements of S' are copies (`:H`) or
   modifications (`:M`) of the remaining prefix. The prefix must still
   contain an origin (tag, hash, sketch geometry), never a bare index.
3. Of these candidates keep the ones lying on the recorded geometry (same
   line and overlapping the old segment; same circle; same plane and
   overlapping bound box). If there are no name candidates, search all
   elements by geometry only.
4. Return all matches, largest first (a split edge → wall on all pieces);
   features needing one face take the largest. Otherwise warn and fall
   back to the old index.

It solves the case in section 3 for all diameters. Known weaknesses:

* **Thresholds are hard-coded** (1e-4 mm collinearity/coincidence). An
  edge that moved legitimately (sketch dimension changed) but was also
  split falls back to name candidates only.
* **No ranking between different candidates.** If history gives several
  unrelated descendants and no geometry is recorded, all are used.
* **Pure-geometry fallback can be ambiguous**: a symmetric part has
  several edges on equivalent lines; only the exact old line is accepted.
* **No notion of intent**: a wall on a split edge is put on all pieces;
  for a face reference the largest piece is taken. Whether that is what
  the user wants depends on the feature.
* **Elements that merge** (a refine step joins the edge with a neighbour)
  or **change type** (a line becomes an arc after a fillet) are not
  handled.
* **No confidence measure** is reported; the user only sees a warning.

## 5. What a better solution should do

Required:

* Pure Python inside FreeCAD 1.1+ (no network, no GPU), at most tens of
  milliseconds per reference on parts with ~10^3 edges.
* Deterministic: the same document recomputes to the same result.
* Prefer "lost, please re-select" over a confident wrong answer. A wrong
  element is far worse than an error message.
* Work for edges, faces and vertices, and for multi-element references.

Desirable:

* A confidence score, and a threshold below which the feature stops with a
  clear message instead of building.
* Graceful use of whatever information is available (old name only,
  geometry only, both).
* Optionally record more at resolution time if it helps (local topology
  signature, neighbouring element names, the old solid).

## 6. Framing for a learned or probabilistic approach

The task is a **matching / ranking problem**: for a lost reference r and
the candidate elements c of the new solid, score P(c is the same element
as r), then return the top set (possibly several, for splits) or nothing.

Possible per-pair features:

* *name history*: length of the shared mapped-name prefix (in operations),
  whether c is a copy/modification/generation of that prefix, edit
  distance over the operation sequence, same origin tag;
* *geometry*: same curve/surface type, collinearity / coplanarity /
  coaxiality distance, overlap ratio of the old and new extents, length or
  area ratio, direction and normal agreement, distance between midpoints;
* *topology*: number of adjacent faces, types of adjacent faces, whether
  the adjacent faces' names match the old element's neighbours, convexity
  of the edge (for sheet metal: inner/outer side of the sheet);
* *context*: what the feature does with the element (bend edge, root face
  of an unfold, cut face).

Training data can be generated automatically: the repository already has
headless builders for every feature (`SMTests/helpers.py`,
`SMTests/testFeatures.py`). A generator can build random feature chains,
reference elements, apply random upstream edits (resize cuts and holes,
move sketch geometry, toggle gaps and reliefs, add chamfers) and record
the ground truth. The ground truth can be obtained by tracking the element
through a *small* parameter step (where names still match) or by
construction (we know which sketch line or tool face produced it). Labels
for "should split to both pieces" vs. "take one" come from the feature
type.

Open questions for the proposal:

1. Is a learned scorer worth it over a hand-tuned scoring function with
   the same features (simpler, explainable, no model to ship)?
2. How to calibrate the "refuse" threshold so wrong answers stay below a
   target rate (e.g. 0.1 % on the generated benchmark)?
3. What extra information should be recorded at resolution time to make
   the problem easier (e.g. a topological fingerprint of the
   neighbourhood), and what does it cost in file size?
4. How to present low-confidence results to the user (warning, task
   panel highlight, ask to re-select)?
5. Can the same scorer improve FreeCAD's own fallback (section 2.2) for
   all workbenches, not just SheetMetal?

## 7. How to evaluate a proposal

* Existing tests: `flatpak run --command=FreeCADCmd org.freecad.FreeCAD
  -t TestSheetMetal` (114 tests; reference tests in `SMTests/testTNP.py`,
  classes `TestTNPWalls`, `TestTNPReferences`, `TestTNPRecovery`).
* The case in section 3 (`SMTests/data/HoleSplitsEdge.FCStd`, vary
  `Hole.Diameter` from 10 to 60).
* A proposed benchmark: generated chains as in section 6, reporting for
  each edit type the rate of correct, refused and **wrong** resolutions.
  Wrong resolutions are the metric that matters most.

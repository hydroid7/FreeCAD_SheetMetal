# 03 Recorded evidence, schema v2

Whenever a reference is followed normally, the resolver records what the
element looked like, so that a later loss can be repaired. Today (v1) this
is the geometry signature of `smGeometrySignature`
(`SheetMetalTools.py:1241–1267`). v2 extends it with extent, position and
a local topology fingerprint.

## Storage

Unchanged from v1: a hidden `App::PropertyStringList` named
**`smRefGeometry`** on the feature, one JSON string per sub of the link
property (`""` = nothing recorded), same order as the subs. Created
lazily with `addProperty(..., 0, False, True)` and
`setPropertyStatus(prop, ["Output"])` so writing it does not trigger
recomputes; only written when the values actually changed
(`SheetMetalTools.py:1364–1374` shows the pattern).

## Schema

```json
{
  "v": 2,
  "geom": {
    "kind": "Edge", "type": "Part::GeomLine",
    "start": [0.0, 50.0, 22.0], "end": [53.0, 50.0, 22.0]
  },
  "extent": 53.0,
  "mid": [26.5, 50.0, 22.0],
  "scale": 118.4,
  "convex": true,
  "adjTypes": ["Part::GeomCylinder", "Part::GeomPlane"],
  "adjNames": ["#216;:H1012,F", "Face3;:M;CUT;:Hc8d:7,F"],
  "mapped": "#312:9;:H1013,E"
}
```

| key | meaning | how computed |
|---|---|---|
| `v` | schema version; a dict without `"v"` is v1 | |
| `geom` | the v1 signature, unchanged format: Vertex `point`; Edge `type`, `start`, `end` (+ `center`, `axis`, `radius` for circles/arcs); Face `type`, `boundBox` (+ `point`, `normal` for planes; + `point`, `normal`, `radius` for cylinders); `null` for unsupported types | `smGeometrySignature` moved into the new module |
| `extent` | `Length` (edge), `Area` (face), `0.0` (vertex) | |
| `mid` | edge: `valueAt` at the parametric middle; face: `CenterOfMass`; vertex: the point | |
| `scale` | `owningShape.BoundBox.DiagonalLength`, for relative tolerances | |
| `convex` | edges only: `true` if the dihedral between the two adjacent faces is convex (outward); `null` for faces/vertices, border edges, or when not computable | adjacent faces via `shape.ancestorsOfType(element, Part.Face)`; compare `(n1 × n2) · t` with a consistent edge orientation |
| `adjTypes` | sorted list of the adjacent faces' `Surface.TypeId` (for an edge or vertex) or of the adjacent edges' `Curve.TypeId` (for a face) | `ancestorsOfType` for edges/vertices; `face.Edges` for faces |
| `adjNames` | expanded mapped names (02 `expandHashes`) of those neighbours, capped at 8, `""` where unnamed | `shape.getElementMappedName(neighbourIndexName)`; neighbour index names found by identity against `shape.Faces`/`shape.Edges` (`isSame`) |
| `mapped` | the element's own expanded mapped name at record time — belt and braces next to the shadow XML | `shape.getElementMappedName(name)` |

Costs: computing the fingerprint touches only the recorded element and its
direct neighbours (no global scans). The JSON is ~400–800 bytes per
reference against ~150 today; a document with 50 references grows by
< 40 kB uncompressed, and `.FCStd` files are zip archives. Measure the
real number on `SMTests/data/HoleSplitsEdge.FCStd` in phase 3 and record
it in the final solution document.

## Migration

```python
def recordEvidence(shape, indexName) -> "dict|None"   # full v2, None for unsupported
def upgradeEvidence(sig: "dict|None") -> "dict|None"
```

`upgradeEvidence` accepts whatever was stored: a v2 dict passes through;
a v1 dict (no `"v"` key — it is the bare `geom` payload) becomes
`{"v": 2, "geom": sig, "extent": None, "mid": None, "scale": None,
"convex": None, "adjTypes": None, "adjNames": None, "mapped": None}`;
`None` stays `None`. **Every consumer of evidence must tolerate `None` in
any field** — that is the graceful-degradation mechanism of the scorer
(04): a feature whose inputs are missing is simply not emitted.

Old documents therefore work immediately (their v1 signatures still drive
the geometry features that v1 supported) and are upgraded to full v2 on
their first successful recompute, because recording already happens on
every followed resolution.

Loading keeps the defensive behaviour of `_loadRefGeometry`
(`SheetMetalTools.py:1355–1361`): invalid JSON yields no evidence, never
an exception.

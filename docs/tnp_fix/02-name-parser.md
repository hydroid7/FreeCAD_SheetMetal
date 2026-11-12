# 02 Structured mapped-name parser

Replaces the naive `mapped.split(";")` in the current
`smHistoryCandidates` (`SheetMetalTools.py:1207–1238`), which miscounts
operations inside parenthesized groups and cannot see through `#hash`
prefixes.

## The grammar (as observed in FreeCAD 1.1.4)

A mapped name is a sequence of **segments** separated by `;` — but only at
parenthesis depth 0; `(`…`)` groups contain `;` and `|` that must not
split the outer name. Observed segment forms:

| segment | meaning |
|---|---|
| `g3` | origin: sketch geometry id 3 |
| `#312:9`, `#216:` | origin: hashed string id 0x312 in the document string table, with an optional trailing `:sub` index |
| `Edge10`, `Face4`, `Vertex2` | origin: a bare index name (fragile) |
| `SKT`, `XTR`, `CUT`, `FUS`, `CMN`, `RVL`, `FLT`, `THK`, `OFS`, `XFM`, `FAC` | operation code (`src/Mod/Part/App/TopoShapeOpCode.h`) |
| `:M`, `:M2`, `:G`, `:U`, `:U2`, `:L` | marker: modified / 2nd modified / generated / upper / lower element |
| `:G(Face5;K-1;:Hce4:4,F)`, `:L(a\|b)` | marker with a parenthesized group — groups follow `:G` as well as `:L`, may nest, and may contain `K-<n>` weight markers (verified live; `docs/TNP.md` only shows `:L` groups) |
| `:H1013`, `:H1013:7`, `:H-304497de`, `:H` | tag segment: tag of the object that performed the operation (hex, may be negative for `smTagTool` tools), optional `:sub` result index, empty for a re-tag by the owning feature |
| `D1910` | duplicate marker |
| `K-1` | weight marker (inside groups) |
| `,E` / `,F` / `,V` | type suffix appended to a segment (Edge/Face/Vertex) |

Real examples (first three from `docs/TNP.md` / the problem statement, the
fourth captured live from a `Part::Cut` with an untagged tool):

```
g3;SKT;:H100f,E;:G;XTR;:H100f:7,F;:U;XTR;:H100f:7,E;:H,E
#312:9;:H1013,E
#312:9;:M;CUT;:H1013:7,E
Edge1;:G(Face5;K-1;:Hce4:4,F);CUT;:Hce5:1c,V
```

## Hash decoding (verified live against FreeCAD 1.1.4)

* `shape.Hasher` is the document's `App.StringHasher` with `getID(int)`,
  `Table`, `Count`, `Threshold`. It is **`None`** on shapes of documents
  where hashing never kicked in — every use must fall back to opaque
  string matching.
* `shape.Hasher.getID(0x312).Data` returns the stored expansion text,
  e.g. `'#216:;:H1012,E;:H,E'` — expansions can themselves contain further
  `#refs`, so expansion must recurse with a depth cap and a memo.
* `shape.getElementHistory('#29e;:H1013,V')` works on hashed names and
  returns `(sourceTag, sourceName, [intermediateNames])`. It finds no
  source object for the negative tags set by `SheetMetalTools.smTagTool`
  (see `docs/TNP.md` 3.2), so it is a cross-check, not the primary
  mechanism.
* The document object only exposes `UseHasher`; always take the hasher
  from the shape.

**Consistency invariant.** The exact way FreeCAD recombines a hash's
`:sub` suffix with the expansion is not documented; we therefore use
expansion only *textually and symmetrically*: `expandHashes` replaces each
token matching `#[0-9a-fA-F]+` with its `Data` (recursively, depth cap 4,
memoized), leaving any `:sub` suffix in place, and both the old name and
all candidate names are expanded by the same function before string
comparison. Structural parsing keeps a hash origin opaque (`("hash", id,
sub)`). Correctness only requires that equal histories expand to equal
strings, which this guarantees.

## API

```python
@dataclass(frozen=True)
class Op:
    marker: str        # ":M", ":M2", ":G", ":U", ":U2", ":L", "" (plain copy/op)
    code: str          # "CUT", "XTR", ... or "" when the op has no code segment
    tag: "int|None"    # from ":H<hex>"; None for ":H" (re-tag) and when absent
    sub: str           # "7" from ":H1013:7", "" otherwise
    typeChar: str      # "E"/"F"/"V"/"" from the ",X" suffix of the closing segment
    args: tuple        # raw text of parenthesized groups, "D<hex>", "K-<n>" segments
                       # (kept verbatim; never used in comparisons)

@dataclass(frozen=True)
class MappedName:
    raw: str
    expanded: str              # expandHashes(raw, hasher); == raw without a hasher
    origin: tuple              # ("hash", 0x312, "9") | ("geom", 3)
                               # | ("index", "Edge10") | ("other", "<text>")
    ops: "tuple[Op, ...]"
    typeSuffix: str            # type char of the whole name ("E"/"F"/"V"/"")

def expandHashes(name: str, hasher, maxDepth: int = 4) -> str
def parseMappedName(name: str, hasher=None) -> "MappedName|None"   # None for ""
def nameRelation(old: MappedName, new: MappedName) -> str
    # "same" | "copy" | "modified" | "generated" | "neighbour"
    # | "ancestor" | "unrelated"
def sharedOpPrefix(old: MappedName, new: MappedName) -> int
    # number of leading ops equal as (marker, code, tag, sub); 0 if origins differ
def opEditDistance(old: MappedName, new: MappedName, cap: int = 8) -> int
    # Levenshtein over (marker, code) tokens, capped; cap when origins differ
def historyCandidatesFromMap(elementMap: dict, mapped: str, kind: str,
                             hasher=None) -> "list[str]"
def historyCandidates(shape, mapped: "MappedName|str|None", kind: str) -> "list[str]"
    # thin wrapper: historyCandidatesFromMap(shape.ElementMap, ..., shape.Hasher)
```

### Tokenization rules

1. Split the raw name on `;` at paren depth 0 (track `(`/`)`; `|` has no
   special role at depth 0). A leading `;` (as stored in shadow strings) is
   stripped by the caller (`smGetShadowNames` already does).
2. The first segment is the **origin**: `#<hex>[:<sub>]` → `("hash", int(hex,
   16), sub)`; `g<n>` → `("geom", n)`; `Edge|Face|Vertex<n>` → `("index",
   segment)`; anything else → `("other", segment)`. A `,X` suffix on the
   origin is recorded as its type char.
3. Remaining segments accumulate into `Op`s. A segment starting `:H` is a
   **tag segment** and closes the current op: parse `:H[<-?hex>][:<sub>][,X]`.
   A segment starting `:` otherwise sets the op's `marker` (text up to a
   `(` group; the group text goes to `args`). A segment of uppercase
   letters sets `code`. `D<hex>` and `K-<n>` segments append to `args`.
   A `,X` suffix on the closing segment becomes the op's `typeChar`.
   Trailing segments that never reach a tag segment still form a final op.
4. `typeSuffix` of the whole name = the last non-empty `typeChar`.

With these rules the four examples parse to:

| raw | origin | ops `(marker, code, tag, sub, typeChar)` |
|---|---|---|
| `g3;SKT;:H100f,E;...` | `("geom", 3)` | `("", "SKT", 0x100f, "", "E")`, `(":G", "XTR", 0x100f, "7", "F")`, `(":U", "XTR", 0x100f, "7", "E")`, `("", "", None, "", "E")` |
| `#312:9;:H1013,E` | `("hash", 0x312, "9")` | `("", "", 0x1013, "", "E")` |
| `#312:9;:M;CUT;:H1013:7,E` | `("hash", 0x312, "9")` | `(":M", "CUT", 0x1013, "7", "E")` |
| `Edge1;:G(...);CUT;:Hce5:1c,V` | `("index", "Edge1")` | `(":G", "CUT", 0xce5, "1c", "V")` with the group text in `args` |

### Relations

Let `p = sharedOpPrefix(old, new)` (0 when origins differ — compare
origins structurally; if both are hashes with different ids, compare
`expanded` strings before giving up).

* origins differ (also after expansion) → `"unrelated"`.
* `p == len(old.ops) == len(new.ops)` → `"same"`.
* `p == len(new.ops) < len(old.ops)` → `"ancestor"` (new is a prefix of old).
* otherwise classify by `new.ops[p].marker`: `""` (a pure tag/copy op or
  an op with a code but no marker) → `"copy"`; `":M"`/`":M2"` →
  `"modified"`; `":G"` → `"generated"`; `":U"`/`":U2"`/`":L"` →
  `"neighbour"`.

### historyCandidatesFromMap

Reimplementation of the current shortening loop on structured ops, same
semantics for today's cases:

1. Parse `mapped`; return `[]` for empty/unparseable input.
2. For `n` from `len(ops)` down to 0: the prefix `(origin, ops[:n])` must
   still be *specific* — origin kind `"hash"` or `"geom"`, or any op in
   the prefix carries a tag (this is `_isSpecificName` generalized). Stop
   when it is not.
3. Collect index names of elements of `kind` whose parsed name has an
   equal origin and whose first `n` ops equal the prefix ops (compared as
   `(marker, code, tag, sub)`, ignoring `args` and `typeChar`), and which
   either have exactly `n` ops (same element, name intact) or whose op
   `n` has marker `":M"`/`":M2"` or is a pure copy (`marker == "" and
   code == ""`). This reproduces the old `name == prefix or
   name.startswith(prefix + ";:H" / ";:M")` rule.
4. First non-empty set wins; sort by numeric element index. One pass over
   the element map per prefix length; parse each map entry at most once
   (parse lazily, memoize per call).
5. **Fallback pass** when the structural scan finds nothing and a hasher
   exists: repeat the scan comparing `expandHashes`-expanded *strings*
   with the old prefix logic (prefix + `";:H"`/`";:M"`), to catch names
   whose hashing boundaries differ between old and new shape.

Sanity requirement (asserted in phase 2): on
`SMTests/data/HoleSplitsEdge.FCStd` as saved (Hole.Diameter = 36, lost
reference `?Edge98` on `Bend003`), `historyCandidates` must return the two
split pieces of the 53 mm edge, exactly like the current implementation
does.

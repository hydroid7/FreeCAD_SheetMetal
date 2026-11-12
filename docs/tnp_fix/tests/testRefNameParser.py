# -*- coding: utf-8 -*-
# #######################################################################
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
# #######################################################################

"""Mapped-name parser tests (docs/tnp_fix/02-name-parser.md).

Prepared test file for phase 2 of docs/tnp_fix/07-phases.md. Move to
SMTests/testRefNameParser.py and import TestMappedNameParser in
TestSheetMetal.py. Pure string level, no documents; run alone with

    flatpak run --command=FreeCADCmd org.freecad.FreeCAD \
        -t SMTests.testRefNameParser
"""

import unittest

from SheetMetalRefRecovery import (
    expandHashes,
    historyCandidatesFromMap,
    nameRelation,
    opEditDistance,
    parseMappedName,
    sharedOpPrefix,
)

# Names taken from docs/TNP.md, docs/reference-resolution-problem.md and
# live probes of FreeCAD 1.1.4 (docs/tnp_fix/02-name-parser.md).
SKETCH_CHAIN = "g3;SKT;:H100f,E;:G;XTR;:H100f:7,F;:U;XTR;:H100f:7,E;:H,E"
COPIED = "#312:9;:H1013,E"
MODIFIED = "#312:9;:M;CUT;:H1013:7,E"
MODIFIED2 = "#312:9;:M2;CUT;:H1013:8,E"
GENERATED_GROUP = "Edge1;:G(Face5;K-1;:Hce4:4,F);CUT;:Hce5:1c,V"
NEGATIVE_TAG = "Edge10;:H-304497de,E"


class StubID:
    def __init__(self, data):
        self.Data = data


class StubHasher:
    """Mimics App.StringHasher.getID for the ids in a fixed table."""

    def __init__(self, table):
        self.table = table  # {int: str}

    def getID(self, value):
        if value not in self.table:
            raise ValueError(f"no string id {value}")
        return StubID(self.table[value])


class TestMappedNameParser(unittest.TestCase):
    def testEmptyName(self):
        self.assertIsNone(parseMappedName(""))

    def testOriginKinds(self):
        self.assertEqual(parseMappedName(COPIED).origin, ("hash", 0x312, "9"))
        self.assertEqual(parseMappedName(SKETCH_CHAIN).origin, ("geom", 3))
        self.assertEqual(parseMappedName(GENERATED_GROUP).origin, ("index", "Edge1"))

    def testSimpleCopy(self):
        name = parseMappedName(COPIED)
        self.assertEqual(len(name.ops), 1)
        op = name.ops[0]
        self.assertEqual((op.marker, op.code, op.tag, op.sub, op.typeChar),
                         ("", "", 0x1013, "", "E"))
        self.assertEqual(name.typeSuffix, "E")

    def testModifiedCut(self):
        name = parseMappedName(MODIFIED)
        self.assertEqual(len(name.ops), 1)
        op = name.ops[0]
        self.assertEqual((op.marker, op.code, op.tag, op.sub, op.typeChar),
                         (":M", "CUT", 0x1013, "7", "E"))

    def testSecondModification(self):
        op = parseMappedName(MODIFIED2).ops[0]
        self.assertEqual((op.marker, op.sub), (":M2", "8"))

    def testSketchChain(self):
        name = parseMappedName(SKETCH_CHAIN)
        self.assertEqual([op.marker for op in name.ops], ["", ":G", ":U", ""])
        self.assertEqual([op.code for op in name.ops], ["SKT", "XTR", "XTR", ""])
        self.assertEqual([op.tag for op in name.ops],
                         [0x100F, 0x100F, 0x100F, None])
        self.assertEqual([op.sub for op in name.ops], ["", "7", "7", ""])
        self.assertEqual(name.typeSuffix, "E")

    def testNegativeTag(self):
        op = parseMappedName(NEGATIVE_TAG).ops[0]
        self.assertEqual(op.tag, -0x304497DE)

    def testGeneratedGroupIsOneOp(self):
        # Parenthesized groups follow :G too (verified live); the ';' and
        # 'K-1' inside the group must not split the outer name.
        name = parseMappedName(GENERATED_GROUP)
        self.assertEqual(len(name.ops), 1)
        op = name.ops[0]
        self.assertEqual((op.marker, op.code, op.tag, op.sub, op.typeChar),
                         (":G", "CUT", 0xCE5, "1c", "V"))
        self.assertTrue(any("Face5;K-1;:Hce4:4,F" in a for a in op.args))

    def testDuplicateMarkerKeptAsArg(self):
        name = parseMappedName("#5a:1;D1910;:Hc0,F")
        self.assertEqual(len(name.ops), 1)
        self.assertIn("D1910", name.ops[0].args)
        # D markers are ignored by comparisons:
        other = parseMappedName("#5a:1;:Hc0,F")
        self.assertEqual(nameRelation(other, name), "same")

    def testRelations(self):
        old = parseMappedName(COPIED)
        self.assertEqual(nameRelation(old, parseMappedName(COPIED)), "same")
        self.assertEqual(nameRelation(old, parseMappedName(MODIFIED)), "modified")
        self.assertEqual(nameRelation(old, parseMappedName(MODIFIED2)), "modified")
        self.assertEqual(nameRelation(parseMappedName(MODIFIED), old), "ancestor")
        self.assertEqual(
            nameRelation(old, parseMappedName("#999;:M;CUT;:H1013:7,E")),
            "unrelated")

    def testGeneratedAndNeighbourRelations(self):
        stem = parseMappedName("g3;SKT;:H100f,E")
        gen = parseMappedName("g3;SKT;:H100f,E;:G;XTR;:H100f:7,F")
        self.assertEqual(nameRelation(stem, gen), "generated")
        self.assertEqual(nameRelation(gen, parseMappedName(SKETCH_CHAIN)), "neighbour")

    def testSharedPrefixAndEditDistance(self):
        a = parseMappedName(SKETCH_CHAIN)
        b = parseMappedName("g3;SKT;:H100f,E;:G;XTR;:H100f:7,F")
        self.assertEqual(sharedOpPrefix(a, b), 2)
        self.assertEqual(opEditDistance(a, a), 0)
        self.assertEqual(opEditDistance(a, b), 2)  # two ops removed
        self.assertEqual(sharedOpPrefix(a, parseMappedName(COPIED)), 0)
        self.assertEqual(opEditDistance(a, parseMappedName("#999;:H1,E"), cap=3), 3)

    def testExpandHashes(self):
        hasher = StubHasher({0x312: "#216:;:H1012,E;:H,E", 0x216: "g7;SKT"})
        # Recursive, textual, ':sub' suffixes left in place.
        self.assertEqual(expandHashes(COPIED, hasher),
                         "g7;SKT:;:H1012,E;:H,E:9;:H1013,E")
        # No hasher, or an unknown id: unchanged.
        self.assertEqual(expandHashes(COPIED, None), COPIED)
        self.assertEqual(expandHashes("#dead;:H1,E", hasher), "#dead;:H1,E")

    def testExpandHashesDepthCap(self):
        hasher = StubHasher({0x1: "#1;:M"})  # self-referential
        expandHashes("#1,E", hasher)  # must terminate; value is unspecified

    def testHistoryCandidates(self):
        # The HoleSplitsEdge pattern: the copied edge is gone, two pieces
        # modified by the CUT remain; shortening by one op must find both,
        # and nothing else.
        elementMap = {
            MODIFIED: "Edge101",
            MODIFIED2: "Edge105",
            "#312:9;:G;CUT;:H1013:9,F": "Face7",   # generated: not a candidate
            "#777;:M;CUT;:H1013:3,E": "Edge3",     # other origin
            "Edge9;:M;CUT;:H1013:4,E": "Edge9",    # index origin: not specific
        }
        found = historyCandidatesFromMap(elementMap, COPIED, "Edge")
        self.assertEqual(found, ["Edge101", "Edge105"])

    def testHistoryCandidatesExactMatch(self):
        found = historyCandidatesFromMap({COPIED: "Edge98"}, COPIED, "Edge")
        self.assertEqual(found, ["Edge98"])

    def testHistoryCandidatesNeverBareIndex(self):
        # A prefix that is just 'Edge9' (no tag, hash or geometry id) must
        # never match: that was _isSpecificName's job.
        # The 1-op prefix 'Edge9;:H7' matches nothing (the candidate's op
        # is ':M;CUT;:H10:1'), and the 0-op prefix 'Edge9' carries no tag,
        # hash or geometry id, so the shortening must stop there.
        found = historyCandidatesFromMap(
            {"Edge9;:M;CUT;:H10:1,E": "Edge4"}, "Edge9;:H7,E", "Edge")
        self.assertEqual(found, [])

    def testEmptyAndKindFilter(self):
        self.assertEqual(historyCandidatesFromMap({}, COPIED, "Edge"), [])
        self.assertEqual(historyCandidatesFromMap({MODIFIED: "Edge1"}, "", "Edge"), [])
        self.assertEqual(
            historyCandidatesFromMap({MODIFIED: "Face1"}, COPIED, "Edge"), [])


if __name__ == "__main__":
    unittest.main()

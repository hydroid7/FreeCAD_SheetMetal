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

"""Scoring and decision tests (docs/tnp_fix/04-scoring.md).

Prepared test file for phase 4 of docs/tnp_fix/07-phases.md. Move to
SMTests/testRefScoring.py and import the classes in TestSheetMetal.py.
Uses synthetic Part geometry, no documents; run alone with

    flatpak run --command=FreeCADCmd org.freecad.FreeCAD \
        -t SMTests.testRefScoring
"""

import unittest

import Part

from SheetMetalRefRecovery import (
    Candidate,
    decide,
    geometryFeatures,
    relTol,
    scoreFeatures,
    splitGroups,
    T_ACCEPT,
    T_MARGIN,
)

SCALE = 118.4  # bound-box diagonal of the HoleSplitsEdge part

# Evidence for the canonical case: a straight 53 mm edge along X.
LINE_EVIDENCE = {
    "v": 2,
    "geom": {"kind": "Edge", "type": "Part::GeomLine",
             "start": [0.0, 50.0, 22.0], "end": [53.0, 50.0, 22.0]},
    "extent": 53.0,
    "mid": [26.5, 50.0, 22.0],
    "scale": SCALE,
    "convex": None, "adjTypes": None, "adjNames": None, "mapped": None,
}


def lineEdge(x0, x1, y=50.0, z=22.0):
    return Part.makeLine((x0, y, z), (x1, y, z))


class TestScoreFeatures(unittest.TestCase):
    def testWeightedMean(self):
        self.assertAlmostEqual(
            scoreFeatures({"a": 1.0, "b": 0.0}, {"a": 2.0, "b": 2.0}), 0.5)

    def testMissingFeatureRenormalizes(self):
        # 'b' is absent: its weight must leave the normalizer entirely.
        self.assertAlmostEqual(
            scoreFeatures({"a": 1.0}, {"a": 2.0, "b": 3.0}), 1.0)

    def testUnknownAndAuxKeysIgnored(self):
        self.assertAlmostEqual(
            scoreFeatures({"a": 1.0, "_midParam": 7.0, "zz": 1.0},
                          {"a": 1.0}), 1.0)

    def testNoUsableFeatures(self):
        self.assertEqual(scoreFeatures({}, {"a": 1.0}), 0.0)


class TestGeometryFeatures(unittest.TestCase):
    def testExactMatch(self):
        f = geometryFeatures(LINE_EVIDENCE, lineEdge(0, 53), SCALE)
        self.assertGreater(f["carrierFit"], 0.95)
        self.assertAlmostEqual(f["containment"], 1.0, places=3)
        self.assertAlmostEqual(f["overlap"], 1.0, places=3)
        self.assertAlmostEqual(f["extentRatio"], 1.0, places=3)
        self.assertAlmostEqual(f["dirDot"], 1.0, places=6)
        self.assertEqual(f["typeMatch"], 1.0)

    def testSplitPiece(self):
        # Left piece of the split edge: 0..19.4 of 53.
        f = geometryFeatures(LINE_EVIDENCE, lineEdge(0, 19.4), SCALE)
        self.assertGreater(f["carrierFit"], 0.95)
        self.assertAlmostEqual(f["containment"], 1.0, places=3)
        self.assertAlmostEqual(f["overlap"], 19.4 / 53.0, places=3)
        self.assertAlmostEqual(f["extentRatio"], 19.4 / 53.0, places=3)

    def testSmallRemnantIsContained(self):
        # The Hole.Diameter = 50 case: a 7.6 mm remnant, coverage ~0.14.
        # Containment must be the strong signal, not coverage.
        f = geometryFeatures(LINE_EVIDENCE, lineEdge(45.4, 53.0), SCALE)
        self.assertAlmostEqual(f["containment"], 1.0, places=3)
        self.assertAlmostEqual(f["overlap"], 7.6 / 53.0, places=3)

    def testOffsetLineDoesNotFit(self):
        # 1 mm off the carrier: carrierFit ~ exp(-1 / relTol) ~ 0.
        f = geometryFeatures(LINE_EVIDENCE, lineEdge(0, 53, y=51.0), SCALE)
        self.assertLess(f["carrierFit"], 0.05)

    def testDisjointSegmentOnSameLine(self):
        # Collinear but outside the old extent: fits the carrier, no overlap.
        f = geometryFeatures(LINE_EVIDENCE, lineEdge(60, 80), SCALE)
        self.assertGreater(f["carrierFit"], 0.95)
        self.assertAlmostEqual(f["overlap"], 0.0, places=3)
        self.assertAlmostEqual(f["containment"], 0.0, places=3)

    def testTypeChangePair(self):
        arc = Part.Edge(Part.Arc(Part.Vertex(0, 50, 22).Point,
                                 Part.Vertex(26.5, 51, 22).Point,
                                 Part.Vertex(53, 50, 22).Point).toShape())
        f = geometryFeatures(LINE_EVIDENCE, arc, SCALE)
        self.assertEqual(f["typeMatch"], 0.5)

    def testNoEvidence(self):
        self.assertEqual(geometryFeatures(None, lineEdge(0, 53), SCALE), {})

    def testV1EvidenceStillWorks(self):
        # upgradeEvidence wraps v1; geometryFeatures must cope with the
        # extent/mid fields being None (only carrier features emitted).
        v1wrapped = dict(LINE_EVIDENCE, extent=None, mid=None)
        f = geometryFeatures(v1wrapped, lineEdge(0, 53), SCALE)
        self.assertGreater(f["carrierFit"], 0.95)
        self.assertNotIn("extentRatio", f)
        self.assertNotIn("midDist", f)

    def testRelTolClamped(self):
        self.assertAlmostEqual(relTol(1.0), 1e-4)
        self.assertAlmostEqual(relTol(118.4), 118.4e-5)
        self.assertAlmostEqual(relTol(1e6), 1e-2)


def cand(elements, score, **features):
    return Candidate(elements=tuple(elements), score=score, repairKind="drift",
                     explanation="", features=features)


class TestSplitGroups(unittest.TestCase):
    def testTwoPiecesFormAGroup(self):
        pieces = [
            cand(["Edge101"], 0.84, carrierFit=1.0, containment=1.0,
                 overlap=19.4 / 53, _midParam=9.7),
            cand(["Edge105"], 0.82, carrierFit=1.0, containment=1.0,
                 overlap=11.5 / 53, _midParam=47.0),
        ]
        out = splitGroups(pieces)
        groups = [c for c in out if len(c.elements) == 2]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group.elements, ("Edge101", "Edge105"))  # by _midParam
        coverage = (19.4 + 11.5) / 53
        self.assertAlmostEqual(group.score, 0.82 * (0.9 + 0.1 * coverage), places=6)
        self.assertEqual(group.repairKind, "split")

    def testOffCarrierCandidateExcluded(self):
        out = splitGroups([
            cand(["Edge101"], 0.8, carrierFit=1.0, containment=1.0, _midParam=1),
            cand(["Edge7"], 0.8, carrierFit=0.1, containment=1.0, _midParam=2),
        ])
        self.assertTrue(all(len(c.elements) == 1 for c in out))

    def testSingleMemberNoGroup(self):
        out = splitGroups([cand(["Edge101"], 0.8, carrierFit=1.0,
                                containment=1.0, _midParam=1)])
        self.assertEqual(len(out), 1)


class TestDecide(unittest.TestCase):
    def sizeOf(self, name):
        return {"Edge101": 19.4, "Edge105": 11.5, "Edge7": 5.0}.get(name, 1.0)

    def testClearWinner(self):
        r = decide([cand(["Edge101"], 0.9), cand(["Edge7"], 0.3)],
                   wantsMany=True, sizeOf=self.sizeOf)
        self.assertEqual((r.status, r.elements), ("recovered", ["Edge101"]))
        self.assertAlmostEqual(r.confidence, 0.9)

    def testBelowThresholdRefuses(self):
        r = decide([cand(["Edge101"], T_ACCEPT - 0.01)],
                   wantsMany=True, sizeOf=self.sizeOf)
        self.assertEqual(r.status, "refused")
        self.assertEqual(r.elements, [])

    def testSmallMarginRefuses(self):
        r = decide([cand(["Edge101"], 0.9), cand(["Edge7"], 0.9 - T_MARGIN / 2)],
                   wantsMany=True, sizeOf=self.sizeOf)
        self.assertEqual(r.status, "refused")

    def testExactTieRefuses(self):
        r = decide([cand(["Edge101"], 0.9), cand(["Edge7"], 0.9)],
                   wantsMany=True, sizeOf=self.sizeOf)
        self.assertEqual(r.status, "refused")

    def testSubsetIsNotARival(self):
        # The group's own pieces must not count as ambiguity.
        r = decide([
            cand(["Edge101", "Edge105"], 0.90),
            cand(["Edge101"], 0.84),
            cand(["Edge105"], 0.82),
        ], wantsMany=True, sizeOf=self.sizeOf)
        self.assertEqual((r.status, list(r.elements)),
                         ("recovered", ["Edge101", "Edge105"]))

    def testSingleElementCallerGetsLargestPiece(self):
        r = decide([cand(["Edge101", "Edge105"], 0.90)],
                   wantsMany=False, sizeOf=self.sizeOf)
        self.assertEqual(r.elements, ["Edge101"])
        self.assertAlmostEqual(r.confidence, 0.90)

    def testNoCandidates(self):
        r = decide([], wantsMany=True, sizeOf=self.sizeOf)
        self.assertEqual(r.status, "refused")

    def testDeterminism(self):
        candidates = [cand(["Edge101", "Edge105"], 0.90), cand(["Edge101"], 0.84),
                      cand(["Edge7"], 0.2)]
        a = decide(list(candidates), wantsMany=True, sizeOf=self.sizeOf)
        b = decide(list(reversed(candidates)), wantsMany=True, sizeOf=self.sizeOf)
        self.assertEqual((a.status, a.elements, a.confidence),
                         (b.status, b.elements, b.confidence))


if __name__ == "__main__":
    unittest.main()

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

"""In-document recovery tests (docs/tnp_fix/01-architecture.md, 04-scoring.md).

Prepared test file for phase 4 of docs/tnp_fix/07-phases.md (the strict-mode
test is skipped until phase 7 — remove the skip there). Move to
SMTests/testRefRecovery.py and import TestRefRecovery in TestSheetMetal.py.

    flatpak run --command=FreeCADCmd org.freecad.FreeCAD \
        -t SMTests.testRefRecovery
"""

import json
import unittest

import FreeCAD
import Part
from FreeCAD import Vector

import SheetMetalTools
from SMTests.helpers import TOL, backEdge, findElement, isLine, makePlate, makeWall
from SMTests.testTNP import edgeSignature, sameLine


class TestRefRecovery(unittest.TestCase):
    """Plate -> Wall1 -> Hole (Part::Cut with a cylinder) -> Wall2 on the
    top edge of the cut, the TestTNPRecovery scenario extended with the
    scored resolver's outcomes."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("TestRefRecovery")
        self.sketch, base = makePlate(self.doc)
        self.wall1 = makeWall(self.doc, base, [backEdge(base.Shape)], "Wall1")
        self.doc.recompute()
        self.tool = self.doc.addObject("Part::Cylinder", "HoleTool")
        self.tool.Radius = 2
        self.tool.Height = 20
        self.tool.Placement = FreeCAD.Placement(
            Vector(50, 40, 17), FreeCAD.Rotation(Vector(1, 0, 0), -90))
        self.cut = self.doc.addObject("Part::Cut", "Hole")
        self.cut.Base = self.wall1
        self.cut.Tool = self.tool
        self.doc.recompute()
        shape = self.cut.Shape
        self.zmax, self.ymax = shape.BoundBox.ZMax, shape.BoundBox.YMax
        self.topEdgeName = findElement(shape, "Edge", self.onTopEdge)
        self.sig = edgeSignature(shape.getElement(self.topEdgeName))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def onTopEdge(self, e, dz=0.0):
        return (isLine(e) and e.BoundBox.XLength > 1
                and abs(e.BoundBox.ZMin - (self.zmax + dz)) < TOL
                and abs(e.BoundBox.YMin - self.ymax) < TOL)

    def makeWall2(self, subNames=None):
        wall2 = makeWall(self.doc, self.cut, subNames or [self.topEdgeName],
                         "Wall2")
        self.doc.recompute()
        # One resolution with the reference intact records the evidence.
        SheetMetalTools.smResolveSubElements(wall2)
        return wall2

    def report(self, obj):
        entries = [json.loads(s) for s in getattr(obj, "smRefReport", []) if s]
        return entries[0] if entries else None

    def assertLost(self, obj):
        self.assertTrue(obj.baseObject[1][0].startswith("?"),
                        "FreeCAD unexpectedly kept the name")

    # ------------------------------------------------------------------ #

    def testSplitRecoveredWithConfidence(self):
        wall2 = self.makeWall2()
        self.tool.Radius = 8  # cuts through the top edge
        self.doc.recompute()
        self.assertLost(wall2)
        self.assertFalse("Invalid" in wall2.State)
        pieces = SheetMetalTools.smResolveSubElements(wall2)
        self.assertEqual(len(pieces), 2)
        for name in pieces:
            self.assertTrue(sameLine(self.cut.Shape.getElement(name), self.sig),
                            name)
        report = self.report(wall2)
        self.assertIsNotNone(report, "smRefReport was not written")
        self.assertEqual(report["status"], "recovered")
        self.assertEqual(report["repairKind"], "split")
        self.assertGreaterEqual(report["confidence"], 0.75)
        self.assertEqual(sorted(report["elements"]), sorted(pieces))

    def testContradictingEvidenceRefuses(self):
        # Tampered evidence puts the old edge on a line 30 mm away. Name
        # candidates exist but contradict the geometry; nothing lies on the
        # recorded line. The resolver must refuse, never follow the names
        # blindly (the old 'matching or found' bug).
        wall2 = self.makeWall2()
        tampered = []
        for s in wall2.smRefGeometry:
            e = json.loads(s)
            for key in ("start", "end", "mid"):
                if e.get(key):
                    e[key] = [e[key][0], e[key][1] + 30.0, e[key][2]]
            g = e.get("geom") or {}
            for key in ("start", "end"):
                if g.get(key):
                    g[key] = [g[key][0], g[key][1] + 30.0, g[key][2]]
            tampered.append(json.dumps(e))
        wall2.smRefGeometry = tampered
        self.tool.Radius = 8
        self.doc.recompute()
        self.assertLost(wall2)
        old = wall2.baseObject[1][0].lstrip("?")
        result = SheetMetalTools.smResolveSubElements(wall2)
        report = self.report(wall2)
        self.assertIsNotNone(report)
        self.assertEqual(report["status"], "refused")
        # Legacy mode: the old index is kept, the list is never empty.
        self.assertEqual(result, [old])

    def testMergeAfterUnsplit(self):
        # Reference one piece while the edge is split, then shrink the hole:
        # the piece's name disappears into the merged full edge.
        self.tool.Radius = 8
        self.doc.recompute()
        left = findElement(self.cut.Shape, "Edge",
                           lambda e: self.onTopEdge(e) and e.BoundBox.XMax < 50)
        wall2 = self.makeWall2([left])
        self.tool.Radius = 2
        self.doc.recompute()
        self.assertLost(wall2)
        merged = SheetMetalTools.smResolveSubElements(wall2)
        self.assertEqual(len(merged), 1)
        self.assertTrue(sameLine(self.cut.Shape.getElement(merged[0]), self.sig))
        report = self.report(wall2)
        self.assertEqual(report["status"], "recovered")

    def testMovedAndSplitNeverWrong(self):
        # Wall1 grows by 15 (the referenced top edge moves up) AND the hole
        # splits it in the same recompute. Correct or refused — but never an
        # edge on the old line or elsewhere.
        wall2 = self.makeWall2()
        self.wall1.length = 35.0
        self.tool.Placement = FreeCAD.Placement(
            Vector(50, 40, 32), FreeCAD.Rotation(Vector(1, 0, 0), -90))
        self.tool.Radius = 8
        self.doc.recompute()
        self.assertLost(wall2)
        result = SheetMetalTools.smResolveSubElements(wall2)
        report = self.report(wall2)
        self.assertIsNotNone(report)
        if report["status"] == "recovered":
            d, p = self.sig
            movedSig = (d, p + Vector(0, 0, 15))
            for name in result:
                self.assertTrue(
                    sameLine(self.cut.Shape.getElement(name), movedSig),
                    f"{name} is not on the moved top edge")
        else:
            self.assertEqual(result, [wall2.baseObject[1][0].lstrip("?")])

    def testTypeChangeNeverWrong(self):
        # A fillet turns the referenced straight edge into an arc. The probe
        # is a bare PropertyLinkSub (the resolver is feature-agnostic).
        fillet = self.doc.addObject("Part::Fillet", "Fillet")
        fillet.Base = self.cut
        # Start by filleting an unrelated short edge so the top edge's name
        # is a plain copy in the fillet output.
        other = findElement(
            self.cut.Shape, "Edge",
            lambda e: isLine(e) and abs(e.BoundBox.ZMax - self.zmax) < TOL
            and abs(e.BoundBox.YMax - (self.ymax - 2.0)) < TOL
            and e.BoundBox.XLength > 1)
        fillet.Edges = [(int(other[4:]), 0.5, 0.5)]
        self.doc.recompute()
        topInFillet = findElement(fillet.Shape, "Edge", self.onTopEdge)
        ref = self.doc.addObject("App::FeaturePython", "Ref")
        ref.addProperty("App::PropertyLinkSub", "Link")
        ref.Link = (fillet, [topInFillet])
        self.doc.recompute()
        SheetMetalTools.smResolveSubElements(ref, "Link")  # record evidence
        fillet.Edges = fillet.Edges + [(int(topInFillet[4:]), 0.5, 0.5)]
        self.doc.recompute()
        if not ref.Link[1][0].startswith("?"):
            self.skipTest("FreeCAD followed the reference by itself")
        result = SheetMetalTools.smResolveSubElements(ref, "Link")
        report = self.report(ref)
        if report and report["status"] == "recovered":
            d, p = self.sig
            for name in result:
                for v in fillet.Shape.getElement(name).Vertexes:
                    self.assertLess(v.Point.distanceToLine(p, d), 0.5 + TOL,
                                    f"{name} is far from the old edge")

    @unittest.skip("strict mode lands in phase 7 - remove this skip then")
    def testStrictModeMarksFeatureInvalid(self):
        wall2 = self.makeWall2()
        if not hasattr(wall2, "smRefStrict"):
            wall2.addProperty("App::PropertyBool", "smRefStrict", "Base", "")
        wall2.smRefStrict = True
        tampered = []
        for s in wall2.smRefGeometry:
            e = json.loads(s)
            g = e.get("geom") or {}
            for key in ("start", "end"):
                if g.get(key):
                    g[key] = [g[key][0], g[key][1] + 30.0, g[key][2]]
            for key in ("mid",):
                if e.get(key):
                    e[key] = [e[key][0], e[key][1] + 30.0, e[key][2]]
            tampered.append(json.dumps(e))
        wall2.smRefGeometry = tampered
        self.tool.Radius = 8
        self.doc.recompute()
        wall2.touch()
        self.doc.recompute()
        self.assertIn("Invalid", wall2.State,
                      "strict mode must mark the feature invalid on refusal")


if __name__ == "__main__":
    unittest.main()

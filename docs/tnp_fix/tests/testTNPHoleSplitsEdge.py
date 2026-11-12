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

"""The hole-splits-edge benchmark case from
docs/reference-resolution-problem.md section 3.

Prepared test file for phase 4 of docs/tnp_fix/07-phases.md. Move to
SMTests/testTNPHoleSplitsEdge.py and import the class in TestSheetMetal.py.
This is the heaviest TNP test (it reopens the document per diameter);
expect ~30-60 s.

The document SMTests/data/HoleSplitsEdge.FCStd is a PartDesign body
(Sketch -> BaseBend -> Bend -> Bend001 -> Bend002 -> Sketch001 -> Hole ->
Bend003) **saved with Hole.Diameter = 36 and the reference of Bend003
already lost** (baseObject sub '?Edge98', pointing at a wrong ~1 mm edge).
At a small diameter FreeCAD re-finds the original name from the stored
shadow, which this test uses to record the true reference line (the 53 mm
edge at the bottom of Bend002's wall). The document is modified in memory
only and closed without saving.

    flatpak run --command=FreeCADCmd org.freecad.FreeCAD \
        -t SMTests.testTNPHoleSplitsEdge
"""

import json
import os
import unittest

import FreeCAD

import SheetMetalTools
from SMTests.testTNP import edgeSignature, sameLine

DATA = os.path.join(os.path.dirname(__file__), "data", "HoleSplitsEdge.FCStd")
SAFE_DIAMETER = 20.0  # the edge is untouched; FreeCAD follows the name


class TestTNPHoleSplitsEdge(unittest.TestCase):
    def setUp(self):
        self.doc = None

    def tearDown(self):
        if self.doc:
            FreeCAD.closeDocument(self.doc.Name)  # never save

    def openAt(self, diameter):
        """Fresh document, reference re-established at SAFE_DIAMETER (which
        also records the resolver evidence), then set to `diameter`."""
        self.doc = FreeCAD.openDocument(DATA)
        hole = self.doc.getObject("Hole")
        bend = self.doc.getObject("Bend003")
        hole.Diameter = SAFE_DIAMETER
        self.doc.recompute()
        sub = bend.baseObject[1][0]
        self.assertFalse(sub.startswith("?"),
                         "FreeCAD did not re-find the edge at D=20")
        edge = bend.baseObject[0].Shape.getElement(sub)
        self.assertAlmostEqual(edge.Length, 53.0, delta=1.0)
        sig = edgeSignature(edge)
        SheetMetalTools.smResolveSubElements(bend)  # record evidence
        hole.Diameter = diameter
        self.doc.recompute()
        return hole, bend, sig

    def resolveAndCheck(self, diameter):
        """Resolve Bend003's reference at the given diameter and assert the
        never-wrong property: every recovered element lies on the recorded
        line, or the resolution refused. Returns (resolved, report, sig)."""
        hole, bend, sig = self.openAt(diameter)
        resolved = SheetMetalTools.smResolveSubElements(bend)
        reports = [json.loads(s) for s in getattr(bend, "smRefReport", []) if s]
        report = reports[0] if reports else None
        refused = report is not None and report["status"] == "refused"
        if not refused:
            self.assertTrue(resolved, f"D={diameter}: empty result")
            for name in resolved:
                self.assertTrue(
                    sameLine(bend.baseObject[0].Shape.getElement(name), sig),
                    f"D={diameter}: {name} is not on the reference line")
            self.assertFalse("Invalid" in bend.State,
                             f"D={diameter}: Bend003 failed to recompute")
        return resolved, report, sig

    def testUntouched(self):
        # D=10: the hole stays clear of the edge; the name must simply follow.
        hole, bend, sig = self.openAt(10.0)
        self.assertFalse(bend.baseObject[1][0].startswith("?"))
        resolved = SheetMetalTools.smResolveSubElements(bend)
        self.assertEqual(len(resolved), 1)
        self.assertTrue(sameLine(bend.baseObject[0].Shape.getElement(resolved[0]),
                                 sig))

    def testSplitAt30(self):
        resolved, report, _sig = self.resolveAndCheck(30.0)
        self.assertEqual(len(resolved), 2, "D=30 must split into two pieces")

    def testSplitAt36(self):
        # The state the document is saved in (wrong 1 mm edge before this work).
        resolved, report, _sig = self.resolveAndCheck(36.0)
        self.assertEqual(len(resolved), 2, "D=36 must split into two pieces")

    def testSplitAt40(self):
        resolved, report, _sig = self.resolveAndCheck(40.0)
        self.assertEqual(len(resolved), 2, "D=40 must split into two pieces")

    def testRemnantAt50(self):
        # Only a ~7.6 mm remnant of the 53 mm edge is left (coverage ~0.14).
        resolved, report, sig = self.resolveAndCheck(50.0)
        self.assertEqual(len(resolved), 1, "D=50 must leave one remnant")
        hole = self.doc.getObject("Hole")
        bend = self.doc.getObject("Bend003")
        edge = bend.baseObject[0].Shape.getElement(resolved[0])
        self.assertAlmostEqual(edge.Length, 7.6, delta=1.0)

    def testNeverWrongAt60(self):
        # At D=60 what remains of the edge is not pinned down by the problem
        # statement; the only requirement is correct-or-refused.
        self.resolveAndCheck(60.0)


if __name__ == "__main__":
    unittest.main()

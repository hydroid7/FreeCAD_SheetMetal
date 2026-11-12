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


"""Tests for the transparent preview of what a feature adds or removes.

The preview extension (Part::PreviewExtensionPython) is not in FreeCAD
1.1.4; the tests that need it are skipped there. See docs/TNP.md section 6.
"""

import unittest
from types import SimpleNamespace

import FreeCAD
import Part
from FreeCAD import Vector

import SheetMetalTools
from SMTests.testTNP import THK, TOL, TestTNPWalls, findElement, isLine, makeBase, makeSketch, makeWall

previewAvailable = SheetMetalTools.smIsTypeAvailable(SheetMetalTools.smPreviewExtension)
needsPreview = unittest.skipUnless(previewAvailable, "FreeCAD has no Part::PreviewExtensionPython")


class TestPreview(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestPreview")
        self.sketch = makeSketch(self.doc, TestTNPWalls.PLATE)
        self.base = makeBase(self.doc, self.sketch)
        self.doc.recompute()
        edge = findElement(self.base.Shape, "Edge", lambda e: isLine(e)
                           and abs(e.BoundBox.YMin - 50) < TOL and abs(e.BoundBox.YMax - 50) < TOL
                           and abs(e.BoundBox.ZMin - THK) < TOL)
        self.wall = makeWall(self.doc, self.base, [edge])
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def makeCutout(self):
        import ExtrudedCutout

        circle = self.doc.addObject("Sketcher::SketchObject", "CutSketch")
        circle.Placement.Base = Vector(0, 0, THK)
        circle.addGeometry(Part.Circle(Vector(30, 25, 0), Vector(0, 0, 1), 5))
        self.doc.recompute()
        face = findElement(self.base.Shape, "Face", lambda f: abs(f.BoundBox.ZMin - THK) < TOL
                           and abs(f.BoundBox.ZMax - THK) < TOL)
        cutout = self.doc.addObject("Part::FeaturePython", "Cutout")
        ExtrudedCutout.ExtrudedCutout(cutout, circle, (self.base, [face]))
        self.doc.recompute()
        return cutout

    def expectedAdded(self, obj):
        return obj.Shape.Volume - obj.baseObject[0].Shape.Volume

    def testDeltaAdd(self):
        delta = SheetMetalTools.smPreviewDelta(self.base.Shape, self.wall.Shape, "add")
        self.assertAlmostEqual(delta.Volume, self.expectedAdded(self.wall), places=3)
        # Everything shown is new material: it lies outside the base plate.
        self.assertAlmostEqual(delta.common(self.base.Shape).Volume, 0, places=3)

    def testDeltaRemove(self):
        cutout = self.makeCutout()
        delta = SheetMetalTools.smPreviewDelta(self.base.Shape, cutout.Shape, "remove")
        self.assertAlmostEqual(delta.Volume, 3.14159265 * 25 * THK, places=3)

    def testDeltaNullShape(self):
        self.assertTrue(SheetMetalTools.smPreviewDelta(Part.Shape(), self.wall.Shape,
                                                        "add").isNull())

    def testProxyHooks(self):
        # Stand in for the extension: the hook only needs ext.ExtendedObject
        # and a PreviewShape property.
        self.wall.addProperty("Part::PropertyPartShape", "PreviewShape")
        self.sketch.Placement.Base = Vector(0, 0, 10)
        self.doc.recompute()
        ext = SimpleNamespace(ExtendedObject=self.wall)
        self.assertTrue(self.wall.Proxy.mustRecomputePreview(ext))
        self.wall.Proxy.recomputePreview(ext)
        preview = self.wall.PreviewShape
        self.assertAlmostEqual(preview.Volume, self.expectedAdded(self.wall), places=3)
        # The preview is drawn in the object's coordinate system.
        self.assertTrue(preview.Placement.isSame(self.wall.Placement.inverse(), TOL))

    def testRemoveMode(self):
        cutout = self.makeCutout()
        self.assertEqual(cutout.Proxy.previewMode, "remove")
        self.assertEqual(self.wall.Proxy.previewMode, "add")

    def testNoExtensionWithoutSupport(self):
        if previewAvailable:
            self.skipTest("FreeCAD has the preview extension")
        self.assertFalse(SheetMetalTools.smAddPreviewExtension(self.wall))
        self.assertNotIn("PreviewShape", self.wall.PropertiesList)

    def testNoExtensionForOtherFeatures(self):
        self.assertFalse(SheetMetalTools.smAddPreviewExtension(self.base))

    @needsPreview
    def testExtensionShowsAddedMaterial(self):
        self.assertTrue(SheetMetalTools.smAddPreviewExtension(self.wall))
        self.wall.invalidatePreview()
        self.wall.updatePreview()
        self.assertAlmostEqual(self.wall.PreviewShape.Volume, self.expectedAdded(self.wall),
                               places=3)

    @needsPreview
    def testExtensionFollowsRecompute(self):
        SheetMetalTools.smAddPreviewExtension(self.wall)
        self.wall.updatePreview()
        self.wall.length = 35.0
        self.doc.recompute()
        self.assertFalse(self.wall.isPreviewFresh())
        self.wall.updatePreview()
        self.assertAlmostEqual(self.wall.PreviewShape.Volume, self.expectedAdded(self.wall),
                               places=3)

    @needsPreview
    def testExtensionShowsRemovedMaterial(self):
        cutout = self.makeCutout()
        self.assertTrue(SheetMetalTools.smAddPreviewExtension(cutout))
        cutout.invalidatePreview()
        cutout.updatePreview()
        self.assertAlmostEqual(cutout.PreviewShape.Volume, 3.14159265 * 25 * THK, places=3)

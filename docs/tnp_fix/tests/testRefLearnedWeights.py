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

"""Learned-scorer loading and inference tests (docs/tnp_fix/06-learned-scorer.md).

Prepared test file for phase 6 of docs/tnp_fix/07-phases.md. Move to
SMTests/testRefLearnedWeights.py and import the class in TestSheetMetal.py.

    flatpak run --command=FreeCADCmd org.freecad.FreeCAD \
        -t SMTests.testRefLearnedWeights
"""

import json
import math
import os
import tempfile
import unittest

from SheetMetalRefRecovery import (
    DEFAULT_WEIGHTS,
    loadWeights,
    scoreFeaturesLearned,
)

FEATURES = sorted(DEFAULT_WEIGHTS)


def weightsDict(**overrides):
    w = {}
    for f in FEATURES:
        w[f] = 1.0
        w["miss_" + f] = -0.5
    data = {"version": 1, "features": FEATURES, "w": w, "b": -2.0,
            "thresholds": {"accept": 0.78, "margin": 0.12}}
    data.update(overrides)
    return data


class TestLearnedWeights(unittest.TestCase):
    def writeWeights(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        self.addCleanup(os.unlink, path)
        return path

    def testLoadValidFile(self):
        lw = loadWeights(self.writeWeights(weightsDict()))
        self.assertIsNotNone(lw)

    def testMissingFileFallsBack(self):
        self.assertIsNone(loadWeights("/nonexistent/refRecoveryWeights.json"))

    def testCorruptJsonFallsBack(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{not json")
        self.addCleanup(os.unlink, path)
        self.assertIsNone(loadWeights(path))

    def testFeatureMismatchFallsBack(self):
        # A weights file for a different feature registry must be rejected,
        # whether features are missing or unknown.
        data = weightsDict(features=FEATURES[:-1])
        self.assertIsNone(loadWeights(self.writeWeights(data)))
        data = weightsDict(features=FEATURES + ["bogusFeature"])
        self.assertIsNone(loadWeights(self.writeWeights(data)))

    def testUnknownVersionFallsBack(self):
        self.assertIsNone(loadWeights(self.writeWeights(weightsDict(version=99))))

    def testInferenceMatchesHandComputation(self):
        lw = loadWeights(self.writeWeights(weightsDict()))
        features = {FEATURES[0]: 1.0, FEATURES[1]: 0.5}
        # present features contribute w*f, absent ones contribute miss_f.
        z = -2.0 + 1.0 * 1.0 + 1.0 * 0.5 + (-0.5) * (len(FEATURES) - 2)
        expected = 1.0 / (1.0 + math.exp(-z))
        self.assertAlmostEqual(scoreFeaturesLearned(features, lw), expected,
                               places=12)

    def testInferenceIgnoresAuxKeys(self):
        lw = loadWeights(self.writeWeights(weightsDict()))
        features = {FEATURES[0]: 1.0}
        withAux = dict(features, _midParam=42.0, _extent=7.0)
        self.assertEqual(scoreFeaturesLearned(features, lw),
                         scoreFeaturesLearned(withAux, lw))

    def testDeterminism(self):
        lw = loadWeights(self.writeWeights(weightsDict()))
        features = {f: 0.3 for f in FEATURES[::2]}
        scores = {scoreFeaturesLearned(dict(features), lw) for _ in range(5)}
        self.assertEqual(len(scores), 1)

    def testCommittedWeightsFileIsValid(self):
        # Once resources/refRecoveryWeights.json is committed (phase 6), it
        # must load against the current feature registry.
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "resources", "refRecoveryWeights.json")
        if not os.path.exists(path):
            self.skipTest("no committed weights file yet")
        self.assertIsNotNone(loadWeights(path),
                             "committed weights file fails validation")


if __name__ == "__main__":
    unittest.main()

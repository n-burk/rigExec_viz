"""Fire activity: exponential decay under a scripted clock."""

import unittest

from rigexec_viz.activity import ActivityModel


class ActivityTest(unittest.TestCase):
    def test_fire_is_brightest_at_zero(self):
        model = ActivityModel(tau=1.0)
        model.fire(["a"], 10.0)
        self.assertAlmostEqual(model.value("a", 10.0), 1.0)

    def test_decay_and_prune(self):
        model = ActivityModel(tau=1.0, floor=0.01)
        model.fire(["a", "b"], 0.0)
        self.assertAlmostEqual(model.value("a", 1.0), 0.367879, places=5)
        live = model.live(0.5)
        self.assertEqual(set(live), {"a", "b"})
        live = model.live(10.0)
        self.assertEqual(live, {})
        # Pruned keys read back zero.
        self.assertEqual(model.value("a", 10.0), 0.0)

    def test_refire_resets(self):
        model = ActivityModel(tau=1.0)
        model.fire(["a"], 0.0)
        model.fire(["a"], 5.0)
        self.assertAlmostEqual(model.value("a", 5.0), 1.0)

    def test_unknown_key_is_dark(self):
        self.assertEqual(ActivityModel().value("nope", 3.0), 0.0)

    def test_fade_seconds_matches_floor(self):
        import math

        model = ActivityModel(tau=0.5, floor=0.01)
        model.fire(["a"], 0.0)
        self.assertAlmostEqual(model.value("a", model.fade_seconds),
                               model.floor, places=9)
        self.assertAlmostEqual(model.fade_seconds,
                               -0.5 * math.log(0.01), places=9)

    def test_clear(self):
        model = ActivityModel()
        model.fire(["a"], 0.0)
        self.assertTrue(model.has_live(0.0))
        self.assertFalse(model.has_live(10.0))
        model.clear()
        self.assertFalse(model.has_live(0.0))
        self.assertEqual(model.live(0.0), {})


if __name__ == "__main__":
    unittest.main()

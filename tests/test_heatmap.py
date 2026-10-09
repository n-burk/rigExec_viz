import unittest
from rigexec_viz.heatmap import COLORS, color_bucket, operation_costs


class HeatmapTest(unittest.TestCase):
    def test_only_measured_body_time(self):
        self.assertEqual(operation_costs([
            [1, 10, 20, 'a', 1], [1, 30, 5, 'b', 2],
            [2, 0, 900, 'a', 3], [3, 40, 900, '', 4],
            [4, 50, 0, 'a', 5], [5, 60, -1, 'a', 6],
            [6, 70, float('nan'), 'a', 7]]), {'step:1': 25, 'step:4': 0})

    def test_log_scale_monotonic_and_bounded(self):
        bins = [color_bucket(t, 10000) for t in (0, 1, 10, 100, 1000, 10000)]
        self.assertEqual(bins, sorted(bins))
        self.assertEqual(bins[0], 0)
        self.assertEqual(bins[-1], len(COLORS)-1)
        self.assertEqual(color_bucket(0, 0), 0)
        self.assertEqual(operation_costs([]), {})

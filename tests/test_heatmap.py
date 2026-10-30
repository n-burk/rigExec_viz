import unittest
from rigexec_viz.heatmap import COLORS, color_bucket, operation_costs, dependency_bucket


class HeatmapTest(unittest.TestCase):
    def test_dependency_uses_source_cost_only_for_same_snapshot(self):
        costs = operation_costs([[1, 10, 100, 'a', 1], [2, 20, 0, 'b', 2]])
        self.assertEqual(dependency_bucket('step:1', 'step:2', costs, 100), len(COLORS)-1)
        self.assertEqual(dependency_bucket('step:2', 'step:1', costs, 100), 0)
        self.assertIsNone(dependency_bucket('step:1', 'step:3', costs, 100))
        # Replacing the trace must not join runs from different generations.
        costs = operation_costs([[3, 30, 50, 'b', 1]])
        self.assertIsNone(dependency_bucket('step:1', 'step:3', costs, 50))

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

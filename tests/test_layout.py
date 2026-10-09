"""Layered layout: columns from edges, barycenter order, wrapped layers."""

import unittest

from rigexec_viz.layout import PITCH_X, PITCH_Y, layout_nodes


class LayoutTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(layout_nodes([], []), {})

    def test_chain_flows_left_to_right(self):
        pos = layout_nodes(["a", "b", "c"], [("a", "b"), ("b", "c")])
        self.assertEqual(
            [pos[i][0] for i in ("a", "b", "c")],
            [0.0, PITCH_X, 2 * PITCH_X])

    def test_diamond_shares_middle_column(self):
        pos = layout_nodes(
            ["a", "b", "c", "d"],
            [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
        self.assertEqual(pos["a"][0], 0.0)
        self.assertEqual(pos["b"][0], PITCH_X)
        self.assertEqual(pos["c"][0], PITCH_X)
        self.assertEqual(pos["d"][0], 2 * PITCH_X)
        # b and c share the column but not the row.
        self.assertNotEqual(pos["b"][1], pos["c"][1])

    def test_unknown_endpoints_ignored(self):
        pos = layout_nodes(["a"], [("a", "ghost"), ("ghost", "a")])
        self.assertEqual(pos, {"a": (0.0, 0.0)})

    def test_barycenter_pulls_toward_predecessors(self):
        # x reads only the bottom source, y only the top one; after the
        # sweeps x sits below y.
        pos = layout_nodes(
            ["top", "bottom", "x", "y"],
            [("bottom", "x"), ("top", "y")],
            order_of={"top": 0, "bottom": 1, "x": 0, "y": 0})
        self.assertGreater(pos["x"][1], pos["y"][1])

    def test_wrap_folds_tall_columns(self):
        ids = ["n%d" % i for i in range(30)]
        pos = layout_nodes(ids, [], wrap=12)
        columns = sorted({x for x, _y in pos.values()})
        self.assertEqual(len(columns), 3)
        rows_per_column = {}
        for x, y in pos.values():
            rows_per_column.setdefault(x, []).append(y)
        for rows in rows_per_column.values():
            self.assertLessEqual(len(rows), 12)
            self.assertEqual(len(set(rows)), len(rows))

    def test_cycle_degrades_to_column_zero(self):
        pos = layout_nodes(["a", "b"], [("a", "b"), ("b", "a")])
        self.assertEqual(set(pos), {"a", "b"})
        for _id, (x, y) in pos.items():
            self.assertGreaterEqual(x, 0.0)
            self.assertGreaterEqual(y, 0.0)

    def test_row_pitch(self):
        pos = layout_nodes(["a", "b"], [])
        ys = sorted(y for _x, y in pos.values())
        self.assertEqual(ys[1] - ys[0], PITCH_Y)


class LargeLayoutTest(unittest.TestCase):
    def test_deep_graph_does_not_use_python_recursion(self):
        nodes = list(range(2500))
        positions = layout_nodes(nodes, [(i, i+1) for i in nodes[:-1]])
        self.assertEqual(len(positions), len(nodes))
        self.assertGreater(positions[2499][0], positions[0][0])


if __name__ == "__main__":
    unittest.main()

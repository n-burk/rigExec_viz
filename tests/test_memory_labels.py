"""Node titles and colors: the pure helpers behind the memory graph."""

import unittest

from rigexec_viz.memory import compact_title, domain_color


class MemoryLabelsTest(unittest.TestCase):
    def test_titles_stay_short(self):
        cases = [
            ({"domain": "batch", "id": "batch:2", "label": "x"},
             "batch 2"),
            ({"domain": "tap", "id": "tap:main:12", "label": "x"},
             "tap main:12"),
            ({"domain": "solver", "id": "s", "label": "/Rig/Solvers/IkFk"},
             "IkFk"),
            ({"domain": "constraint", "id": "c",
              "label": "/Rig/Movers/tail/tail_from_ankle"},
             "tail_from_ankle"),
            ({"domain": "chain", "id": "c",
              "label": "/Model/Geom/Dots.points"},
             "Geom/Dots.points"),
            ({"domain": "revision", "id": "r", "label": "x", "order": 3,
              "details": {"mover": "/Rig/Movers/chain/move"}},
             "move@3"),
            ({"domain": "step", "id": "step:7", "label": "x",
              "kind": "Constraint"},
             "s7 Constraint"),
        ]
        for node, expected in cases:
            self.assertEqual(compact_title(node), expected)

    def test_domain_colors_cover_every_domain(self):
        for domain in ("batch", "solver", "constraint", "chain", "revision",
                       "propchain", "proprev", "tap", "provider", "switch",
                       "interp", "skipped", "step", "unknown-domain"):
            color = domain_color(domain)
            self.assertEqual(len(color), 3)
            for channel in color:
                self.assertGreaterEqual(channel, 0.0)
                self.assertLessEqual(channel, 1.0)

    def test_step_kinds_group_by_program_half(self):
        pose = domain_color("step", "Solve")
        geometry = domain_color("step", "RevisionChunk")
        weights = domain_color("step", "WeightPacket")
        self.assertNotEqual(pose, geometry)
        self.assertNotEqual(pose, weights)
        self.assertNotEqual(geometry, weights)
        # Unknown kinds fall back to the domain color.
        self.assertEqual(domain_color("step", "Nope"),
                         domain_color("step"))


if __name__ == "__main__":
    unittest.main()

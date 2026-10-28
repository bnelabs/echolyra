"""Pose-graph adjustment tests: loop closure reduces drift; validation is strict."""
import math
import unittest

import numpy as np

import geometry_pose as pose


class PoseTests(unittest.TestCase):
    def test_sanitize_accepts_and_rejects(self):
        good = {"segments": [{"distance_m": .6, "heading_rad": 0.0},
                             {"distance_m": .6, "heading_rad": math.pi / 2},
                             {"distance_m": .6, "heading_rad": math.pi},
                             {"distance_m": .6, "heading_rad": -math.pi / 2}], "loop": True}
        self.assertIsNotNone(pose.sanitize_trajectory(good))
        self.assertIsNone(pose.sanitize_trajectory({"segments": good["segments"][:2]}))
        self.assertIsNone(pose.sanitize_trajectory({**good, "loop": "yes"}))
        bad = {"segments": good["segments"][:3] + [{"distance_m": 9.0, "heading_rad": 0.0}], "loop": True}
        self.assertIsNone(pose.sanitize_trajectory(bad))
        self.assertIsNone(pose.sanitize_trajectory({"segments": "nope", "loop": True}))

    def test_loop_closure_reduces_drift(self):
        # True square-ish loop; distances/headings measured with noise.
        segments = [{"distance_m": .6, "heading_rad": 0.0},
                    {"distance_m": .6, "heading_rad": math.pi / 2},
                    {"distance_m": .6, "heading_rad": math.pi},
                    {"distance_m": .62, "heading_rad": -math.pi / 2 + 0.04}]
        result = pose.adjust({"segments": segments, "loop": True})
        diag = result["diagnostics"]
        self.assertGreater(diag["raw_loop_error_m"], 0.02)
        self.assertLess(diag["adjusted_loop_error_m"], diag["raw_loop_error_m"])
        self.assertLess(diag["adjusted_loop_error_m"], 0.02)
        self.assertEqual(len(result["poses"]), len(segments) + 1)
        self.assertTrue(all(abs(p["yaw"]) < 1e-6 for p in result["poses"]))

    def test_adjusted_poses_are_near_ground_truth(self):
        # Ground-truth L path: right 0.6, forward 0.6, right 0.6, return to start.
        truth = np.array([[0, 0], [0.6, 0], [0.6, 0.6], [1.2, 0.6], [0, 0]], dtype=float)
        segments = []
        for i in range(4):
            delta = truth[i + 1] - truth[i]
            segments.append({"distance_m": float(np.linalg.norm(delta)),
                             "heading_rad": float(np.arctan2(delta[1], delta[0]))})
        result = pose.adjust({"segments": segments, "loop": True})
        poses = np.array([[p["x"], p["y"]] for p in result["poses"]])
        # Orientation may be rotated; align the first segment and compare relative geometry.
        angle = -segments[0]["heading_rad"]
        rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        expected = truth @ rotation.T
        self.assertLess(float(np.max(np.abs(poses - expected))), 0.12)

    def test_no_loop_keeps_dead_reckoning(self):
        segments = [{"distance_m": .6, "heading_rad": 0.0},
                    {"distance_m": .6, "heading_rad": math.pi / 2},
                    {"distance_m": .6, "heading_rad": math.pi}]
        result = pose.adjust({"segments": segments, "loop": False})
        self.assertIsNone(result["diagnostics"]["raw_loop_error_m"])
        self.assertEqual(len(result["poses"]), 4)


if __name__ == "__main__":
    unittest.main()

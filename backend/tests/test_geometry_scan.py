"""Walk-scan localization tests: controlled echoes, clutter, validation. No HTTP, no audio I/O."""
import math
import unittest

import numpy as np

import geometry_scan as scan

SOUND_SPEED = 343.0
POSES = [{"x": 0.0, "y": 0.0, "yaw": 0.0},
         {"x": 0.6, "y": 0.0, "yaw": 0.0},
         {"x": 0.6, "y": 0.6, "yaw": 0.0},
         {"x": 1.2, "y": 0.6, "yaw": 0.0}]
REFLECTORS = [(2.0, 1.2), (3.4, 2.6), (1.4, 2.8)]


def echo_sets(reflectors, poses, strength=0.6, extra_walls=()):
    sets = []
    for pose in poses:
        echoes = []
        for x, y in list(reflectors) + list(extra_walls):
            distance = math.hypot(x - pose["x"], y - pose["y"])
            echoes.append({"delay_ms": 2 * distance / SOUND_SPEED * 1000.0,
                           "strength": strength, "radius_m": distance})
        sets.append(echoes)
    return sets


class WalkScanTests(unittest.TestCase):
    def test_recovers_controlled_reflectors(self):
        out = scan.scan_echoes(echo_sets(REFLECTORS, POSES), POSES)
        self.assertEqual(out["status"], "reflectors")
        self.assertTrue(3 <= len(out["reflectors"]) <= len(REFLECTORS) + 3)
        for truth in REFLECTORS:
            nearest = min(math.hypot(r["x"] - truth[0], r["y"] - truth[1]) for r in out["reflectors"])
            self.assertLess(nearest, 0.30, f"reflector {truth} not recovered: {nearest}")
        self.assertGreaterEqual(sum(1 for r in out["reflectors"] if r["type"] == "persistent"), 3)

    def test_moving_reflector_is_unstable(self):
        sets = echo_sets(REFLECTORS, POSES)
        for i in range(3):  # a person walking is seen at three of four poses
            sets[i].append({"delay_ms": 2 * 1.1 / SOUND_SPEED * 1000.0,
                            "strength": 0.5, "radius_m": 1.1})
        out = scan.scan_echoes(sets, POSES)
        self.assertTrue(any(r["type"] == "unstable" for r in out["reflectors"]),
                        "partially supported reflection should be marked unstable")
        for r in out["reflectors"]:
            self.assertEqual(r["type"], "persistent" if r["support"] >= 4 else "unstable")

    def test_dense_clutter_does_not_invent_many_reflectors(self):
        rng = np.random.default_rng(3)
        sets = []
        for _ in POSES:
            sets.append([{"delay_ms": float(t), "strength": float(a),
                          "radius_m": t / 1000 * SOUND_SPEED / 2}
                         for t, a in zip(rng.uniform(2, 24, 10), rng.uniform(0.1, 0.8, 10))])
        out = scan.scan_echoes(sets, POSES)
        self.assertLessEqual(len(out["reflectors"]), 6)

    def test_requires_enough_separated_poses(self):
        self.assertIsNotNone(scan.sanitize_poses(POSES))
        self.assertIsNone(scan.sanitize_poses(POSES[:3]))
        self.assertIsNone(scan.sanitize_poses([POSES[0], {"x": 0.05, "y": 0.0, "yaw": 0}]))
        self.assertIsNone(scan.sanitize_poses([{"x": float("nan"), "y": 0}] + POSES[1:]))
        self.assertIsNone(scan.sanitize_poses([{"x": 99, "y": 0}] + POSES[1:]))
        self.assertIsNone(scan.sanitize_poses(["not-a-pose"] + POSES[1:]))

    def test_scan_validates_input_shape(self):
        audio = [np.zeros(4 * 48000)] * 2
        with self.assertRaises(ValueError):
            scan.scan(audio, POSES)
        with self.assertRaises(ValueError):
            scan.scan_echoes([[{"delay_ms": 5, "strength": .5}]], POSES)
        with self.assertRaises(ValueError):
            scan.scan_echoes([[], [], [], []], POSES[:3])

    def test_empty_or_noisy_echoes_give_honest_refusal(self):
        out = scan.scan_echoes([[], [], [], []], POSES)
        self.assertEqual(out["status"], "insufficient_evidence")
        self.assertEqual(out["reflectors"], [])
        self.assertIn("Not enough consistent reflections", out["message"])


if __name__ == "__main__":
    unittest.main()

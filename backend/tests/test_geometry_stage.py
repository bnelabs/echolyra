"""Staging is illustrative only; all HTTP is mocked here (no live models, no keys)."""
import json
import unittest
from unittest.mock import patch

import httpx

import geometry_stage as stage


def result(objects=None):
    return {
        "status": "candidate", "source": "synthetic_demo",
        "message": "private room text", "room_name": "private bedroom",
        "candidates": [{"id": "private-id", "dimensions_m": [5.7, 4.3, 2.9],
                        "sensor_position_m": [1.2, 1.5, 1.1],
                        "vertices": [[0, 0, 0]], "faces": [[0, 1, 2]]}],
        "objects": objects if objects is not None else [
            {"id": "object-1", "distance_m": 1.4, "strength": 0.5, "note": "private"}],
        "echoes": [{"delay_ms": 12, "strength": .7, "path": "/private/file.wav"}],
        "diagnostics": {"recordings": 3},
    }


class StagingTests(unittest.TestCase):
    def test_sanitizer_drops_free_text_and_audio(self):
        payload = stage.sanitize(result())
        serialized = json.dumps(payload)
        for token in ("private", "audio", "room_name", "vertices", "path"):
            self.assertNotIn(token, serialized)
        self.assertEqual(payload["dimensions_m"], [5.7, 4.3, 2.9])
        self.assertEqual(payload["acoustic_candidates"][0]["distance_m"], 1.4)

    def test_procedural_objects_stay_inside_estimated_shell(self):
        payload = stage.sanitize(result())
        spec = stage.procedural(payload)
        length, depth, height = payload["dimensions_m"]
        self.assertTrue(spec["available"])
        self.assertEqual(spec["source"], "procedural")
        self.assertTrue(spec["objects"])
        for obj in spec["objects"]:
            self.assertIn(obj["kind"], stage.KINDS)
            self.assertGreaterEqual(obj["x"] - obj["w"] / 2, -1e-6)
            self.assertLessEqual(obj["x"] + obj["w"] / 2, length + 1e-6)
            self.assertGreaterEqual(obj["z"] - obj["d"] / 2, -1e-6)
            self.assertLessEqual(obj["z"] + obj["d"] / 2, depth + 1e-6)
            self.assertLessEqual(obj["h"], height + 1e-6)

    def test_missing_key_returns_procedural_without_http(self):
        with patch.object(stage.mm, "KEY", ""), patch.object(stage.httpx, "Client") as client:
            spec = stage.stage(result())
            client.assert_not_called()
        self.assertEqual(spec["source"], "procedural")
        self.assertTrue(any(t in spec["note"] for t in ("not measured", "not a measurement")))

    def test_forced_procedural_never_calls_http(self):
        with patch.dict("os.environ", {"GEOMETRY_STAGE_MODE": "procedural"}), \
             patch.object(stage.httpx, "Client") as client:
            self.assertEqual(stage.stage(result())["source"], "procedural")
            client.assert_not_called()

    def test_meta_spec_is_validated_and_clamped(self):
        content = json.dumps({"style": "Calm studio", "palette": ["#AABBCC"],
                              "objects": [{"kind": "sofa", "x": 99, "z": -5, "w": 30, "d": 0.9,
                                           "h": 99, "color": "#112233"},
                                          {"kind": "hologram", "x": 1, "z": 1, "w": 1, "d": 1, "h": 1},
                                          {"kind": "table", "x": 2, "z": 2, "w": 1, "d": 1, "h": 0.5}]})
        with patch.object(stage.mm, "KEY", "test-placeholder"), \
             patch.object(stage.mm, "MODEL_SPARK", "muse-spark-1.3-contributor"), \
             patch.object(stage.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.post.return_value = httpx.Response(200,
                request=httpx.Request("POST", "https://api.meta.ai/v1/chat/completions"),
                json={"choices": [{"message": {"content": content}}]})
            spec = stage.stage(result())
            self.assertEqual(spec["source"], "meta")
            self.assertTrue(spec["training_use"])
            self.assertEqual([o["kind"] for o in spec["objects"]], ["sofa", "table"])
            self.assertEqual(len(spec["objects"]), 2)
            sofa = spec["objects"][0]
            self.assertLessEqual(sofa["w"], 5.7 * 0.85 + 1e-6)
            self.assertGreaterEqual(sofa["x"] - sofa["w"] / 2, 0)
            self.assertLessEqual(sofa["x"] + sofa["w"] / 2, 5.7)
            self.assertLessEqual(sofa["h"], 2.9)
            sent = json.loads(client.post.call_args.kwargs["json"]["messages"][1]["content"])
            self.assertEqual(sent, stage.sanitize(result()))
            self.assertEqual(client.post.call_count, 1)

    def test_malformed_or_failed_meta_falls_back_to_procedural(self):
        for content in ("not json", '{"objects": []}', '[]'):
            with self.subTest(content=content), patch.object(stage.mm, "KEY", "test-placeholder"), \
                 patch.object(stage.httpx, "Client") as factory:
                factory.return_value.__enter__.return_value.post.return_value = httpx.Response(200,
                    request=httpx.Request("POST", "https://api.meta.ai/v1/chat/completions"),
                    json={"choices": [{"message": {"content": content}}]})
                self.assertEqual(stage.stage(result())["source"], "procedural")
        with patch.object(stage.mm, "KEY", "test-placeholder"), \
             patch.object(stage.httpx, "Client") as factory:
            factory.return_value.__enter__.return_value.post.side_effect = \
                httpx.ReadTimeout("secret private header")
            spec = stage.stage(result())
            self.assertEqual(spec["source"], "procedural")
            self.assertNotIn("secret", spec["note"])

    def test_no_candidate_means_nothing_to_stage(self):
        spec = stage.stage({"status": "insufficient_evidence", "candidates": [], "objects": []})
        self.assertFalse(spec["available"])
        self.assertEqual(spec["objects"], [])

    def test_only_official_meta_endpoint_is_used(self):
        for base in ("http://api.meta.ai/v1", "https://example.com/v1", "https://api.meta.ai:8443/v1"):
            with self.subTest(base=base), patch.object(stage.mm, "KEY", "test-placeholder"), \
                 patch.object(stage.mm, "BASE", base), patch.object(stage.httpx, "Client") as factory:
                self.assertEqual(stage.stage(result())["source"], "procedural")
                factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

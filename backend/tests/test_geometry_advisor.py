"""These tests mock all HTTP; no credential files or live models are accessed."""
import json
import math
import unittest
from unittest.mock import patch

import httpx

import geometry_advisor as advisor


class GeometryAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "status": "candidate", "source": "recorded_audio",
            "message": "DO NOT SEND private room name or instructions",
            "audio": "private audio", "room_name": "private bedroom",
            "candidates": [{"id": "private-room", "dimensions_m": [5, 4, 3],
                            "sensor_position_m": [2, 1, 1], "vertices": [[1, 2, 3]],
                            "fit_error_ms": 0.1, "matched_echoes": 12,
                            "total_predicted_echoes": 15, "support_fraction": .8}],
            "echoes": [{"delay_ms": 12, "strength": .7, "path": "/private/file.wav"}],
            "diagnostics": {"recordings": 3, "repeatable_echoes": 12,
                            "path": "/private/location"},
        }

    def test_sanitizer_drops_free_text_and_coordinates(self):
        payload = advisor.sanitize(self.result)
        serialized = json.dumps(payload)
        for token in ("private", "audio", "room_name", "sensor_position", "vertices", "path"):
            self.assertNotIn(token, serialized)
        self.assertEqual(payload["candidates"][0]["dimensions_m"], [5.0, 4.0, 3.0])
        self.assertEqual(payload["diagnostics"], {"recordings": 3, "repeatable_echoes": 12})

    def test_sanitizer_rejects_nonfinite_boolean_and_unbounded_numbers(self):
        self.result["candidates"] *= 10
        self.result["candidates"][0] = {"dimensions_m": [math.nan, 4, 3]}
        self.result["echoes"] = [{"delay_ms": v, "strength": .5}
                                 for v in (math.inf, -1, True, "12", 201, 10)]
        self.result["diagnostics"]["recordings"] = True
        payload = advisor.sanitize(self.result)
        self.assertEqual(len(payload["candidates"]), 2)
        self.assertEqual(payload["echoes"], [{"delay_ms": 10.0, "strength": .5}])
        self.assertNotIn("recordings", payload["diagnostics"])
        json.dumps(payload, allow_nan=False)

    def test_missing_key_never_calls_http(self):
        with patch.object(advisor.mm, "KEY", ""), patch.object(advisor.httpx, "Client") as client:
            self.assertFalse(advisor.review(self.result)["available"])
            client.assert_not_called()

    def test_empty_evidence_never_calls_http(self):
        with patch.object(advisor.mm, "KEY", "test-placeholder"), patch.object(advisor.httpx, "Client") as client:
            self.assertFalse(advisor.review({"status": "insufficient_evidence"})["available"])
            client.assert_not_called()

    def test_one_request_sends_only_sanitized_data_and_leaves_result_unchanged(self):
        before = json.dumps(self.result)
        with patch.object(advisor.mm, "KEY", "test-placeholder"), \
             patch.object(advisor.mm, "MODEL_SPARK", "muse-spark-1.3-contributor"), \
             patch.object(advisor.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://api.meta.ai/v1/chat/completions"),
                json={"choices": [{"message": {"content": json.dumps({
                    "assessment": "Echo associations remain ambiguous.",
                    "next_measurement": "Repeat a probe after moving the phone away from a nearby surface."})}}]})
            result = advisor.review(self.result)
            self.assertTrue(result["available"])
            self.assertTrue(result["training_use"])
            self.assertIn("does not confirm", result["text"])
            sent = client.post.call_args.kwargs["json"]
            self.assertEqual(sent["model"], "muse-spark-1.3-contributor")
            self.assertEqual(json.loads(sent["messages"][1]["content"]), advisor.sanitize(self.result))
            self.assertEqual(client.post.call_count, 1)
            self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertEqual(json.dumps(self.result), before)

    def test_only_official_https_meta_destination_is_allowed(self):
        for base in ("http://api.meta.ai/v1", "https://example.com/v1", "https://api.meta.ai.evil.test/v1",
                     "https://api.meta.ai/v1?forward=elsewhere", "https://user:password@api.meta.ai/v1",
                     "https://api.meta.ai:8443/v1", "https://api.meta.ai/v2"):
            with self.subTest(base=base), patch.object(advisor.mm, "KEY", "test-placeholder"), \
                 patch.object(advisor.mm, "BASE", base), patch.object(advisor.httpx, "Client") as factory:
                result = advisor.review(self.result)
                self.assertFalse(result["available"])
                self.assertIn("official Meta API address", result["text"])
                factory.assert_not_called()
        for base in ("https://api.meta.ai/v1", "https://api.meta.ai/v1/"):
            self.assertEqual(advisor._meta_endpoint(base), "https://api.meta.ai/v1/chat/completions")

    def test_provider_error_does_not_expose_exception_or_retry(self):
        with patch.object(advisor.mm, "KEY", "test-placeholder"), patch.object(advisor.httpx, "Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.post.side_effect = httpx.ReadTimeout("secret header and private content")
            result = advisor.review(self.result)
            self.assertFalse(result["available"])
            self.assertNotIn("secret", result["text"])
            self.assertNotIn("private", result["text"])
            self.assertEqual(client.post.call_count, 1)

    def test_malformed_advice_is_not_displayed(self):
        for content in ('{"geometry": "invented"}', '[]', 'null', 'not json'):
            with self.subTest(content=content), patch.object(advisor.mm, "KEY", "test-placeholder"), \
                 patch.object(advisor.mm, "MODEL_SPARK", "muse-spark-1.3"), \
                 patch.object(advisor.httpx, "Client") as factory:
                factory.return_value.__enter__.return_value.post.return_value = httpx.Response(200,
                    request=httpx.Request("POST", "https://api.meta.ai/v1/chat/completions"),
                    json={"choices": [{"message": {"content": content}}]})
                result = advisor.review(self.result)
                self.assertFalse(result["available"])
                self.assertFalse(result["training_use"])
                self.assertNotIn("invented", result["text"])


if __name__ == "__main__":
    unittest.main()

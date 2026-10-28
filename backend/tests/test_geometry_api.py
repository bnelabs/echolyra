"""Route contracts: geometry never changes awareness/probe enrollment state."""
import io
import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as api


def wav(seconds=4.8, fs=48000):
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * fs)), fs, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class GeometryAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_requires_one_to_three_recordings(self):
        self.assertEqual(self.client.post("/api/geometry/reconstruct").status_code, 400)
        four = [("audio", ("probe.wav", wav(), "audio/wav"))] * 4
        self.assertEqual(self.client.post("/api/geometry/reconstruct", files=four).status_code, 400)

    def test_rejects_bad_audio_and_oversized_upload(self):
        for raw, expected in [(b"not audio", 400), (b"x" * 2_000_001, 413),
                              (wav(.1), 400), (wav(3.1), 400), (wav(fs=16000), 400)]:
            response = self.client.post("/api/geometry/reconstruct",
                                        files={"audio": ("probe.wav", raw, "audio/wav")})
            self.assertEqual(response.status_code, expected, response.text)

    def test_reconstruction_is_transient_and_has_no_cloud_call(self):
        before = json.dumps(api.SESSION.state, sort_keys=True)
        probe_path = api.probe.STATE_PATH
        probe_before = probe_path.read_bytes() if probe_path.exists() else None
        with patch.object(api.geometry, "reconstruct", return_value={"status": "insufficient_evidence"}) as solve, \
                patch.object(api.geometry_advisor, "review") as review:
            response = self.client.post("/api/geometry/reconstruct", files=[
                ("audio", ("probe.wav", wav(), "audio/wav"))] * 3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(solve.call_args.args[0]), 3)
        self.assertEqual(solve.call_args.args[1], 48000)
        review.assert_not_called()
        self.assertEqual(before, json.dumps(api.SESSION.state, sort_keys=True))
        self.assertEqual(probe_before, probe_path.read_bytes() if probe_path.exists() else None)

    def test_stage_is_separate_bounded_and_illustrative(self):
        result = {"status": "candidate", "candidates": [{"dimensions_m": [5, 4, 3]}],
                  "objects": [{"distance_m": 1.2, "strength": 0.4}]}
        response = self.client.post("/api/geometry/stage", json=result)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn(body["source"], {"meta", "procedural"})
        self.assertTrue(any(t in json.dumps(body["note"]).lower() for t in ("not measured", "not a measurement")))
        self.assertLessEqual(len(body["objects"]), 8)
        self.assertEqual([], body["objects"]) if body["source"] == "none" else None
        self.assertEqual(self.client.post("/api/geometry/stage", content=b"not json").status_code, 400)

    def test_walk_scan_requires_poses_and_transient_audio(self):
        clip = wav()
        files = [("audio", (f"p{i}.wav", clip, "audio/wav")) for i in range(4)]
        poses = '[{"x":0,"y":0,"yaw":0},{"x":0.6,"y":0,"yaw":0},{"x":0.6,"y":0.6,"yaw":0},{"x":1.2,"y":0.6,"yaw":0}]'
        before = json.dumps(api.SESSION.state, sort_keys=True)
        response = self.client.post("/api/geometry/scan", files=files, data={"poses": poses})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(response.json()["status"], {"reflectors", "insufficient_evidence"})
        self.assertEqual(self.client.post("/api/geometry/scan", files=files,
                                          data={"poses": "[]"}).status_code, 400)
        self.assertEqual(self.client.post("/api/geometry/scan", files=files[:3],
                                          data={"poses": poses}).status_code, 400)
        self.assertEqual(json.dumps(api.SESSION.state, sort_keys=True), before)

    def test_walk_scan_accepts_pose_graph_trajectory(self):
        clip = wav()
        files = [("audio", (f"p{i}.wav", clip, "audio/wav")) for i in range(5)]
        # Closed loop: right, forward, left, back; distances/headings slightly off.
        trajectory = {"segments": [
            {"distance_m": 0.6, "heading_rad": 0.0},
            {"distance_m": 0.6, "heading_rad": math.pi / 2},
            {"distance_m": 0.6, "heading_rad": math.pi},
            {"distance_m": 0.62, "heading_rad": -math.pi / 2 + 0.03},
        ], "loop": True}
        response = self.client.post("/api/geometry/scan", files=files,
                                    data={"trajectory": json.dumps(trajectory)})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("trajectory", body)
        self.assertIn("adjusted_loop_error_m", body["trajectory"]["diagnostics"])
        self.assertEqual(len(body["trajectory"]["poses"]), 5)
        self.assertEqual(self.client.post("/api/geometry/scan", files=files,
                                          data={"trajectory": "bad"}).status_code, 400)
        six = files + [("audio", ("p5.wav", clip, "audio/wav"))]
        self.assertEqual(self.client.post("/api/geometry/scan", files=six,
                                          data={"trajectory": json.dumps(trajectory)}).status_code, 400)

    def test_review_is_separate_and_bounded(self):
        with patch.object(api.geometry_advisor, "review", return_value={
                "available": False, "text": "Not configured", "training_use": False}) as review:
            self.assertEqual(self.client.post("/api/geometry/review", json=[]).status_code, 400)
            self.assertEqual(self.client.post("/api/geometry/review", content=b"x" * 64_001).status_code, 413)
            review.assert_not_called()
            response = self.client.post("/api/geometry/review", json={"status": "insufficient_evidence"})
            self.assertEqual(response.status_code, 200)
            review.assert_called_once()

    def test_demo_response_is_explicitly_synthetic_and_cached(self):
        prior = api.DEMO_CACHE.pop("geometry", None)
        try:
            with patch.object(api.geometry, "demo", return_value={"source": "synthetic_demo"}) as demo:
                for _ in range(2):
                    response = self.client.get("/api/geometry/demo")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["source"], "synthetic_demo")
                demo.assert_called_once()
        finally:
            api.DEMO_CACHE.pop("geometry", None)
            if prior is not None:
                api.DEMO_CACHE["geometry"] = prior


if __name__ == "__main__":
    unittest.main()


class GeometryUploadLimitIntegrationTests(unittest.TestCase):
    """The ASGI body limiter must actually be registered on the running app."""

    def setUp(self):
        self.client = TestClient(api.app)

    def test_geometry_route_registered_limiter_rejects_oversized_body(self):
        clip = wav()
        response = self.client.post(
            "/api/geometry/reconstruct",
            files=[("audio", ("probe.wav", clip, "audio/wav")),
                   ("junk", ("junk.bin", b"x" * 6_500_000, "application/octet-stream"))])
        self.assertEqual(response.status_code, 413, response.text)

    def test_other_routes_are_not_limited_by_geometry_middleware(self):
        response = self.client.post("/api/geometry/review", json={"status": "insufficient_evidence"})
        self.assertNotEqual(response.status_code, 413)

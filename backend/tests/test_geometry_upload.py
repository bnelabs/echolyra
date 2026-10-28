"""ASGI-level checks: rejected bodies never reach multipart parsing or disk spooling."""
import unittest

from geometry_upload import GeometryUploadLimit, MAX_GEOMETRY_REQUEST_BYTES


class GeometryUploadTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, messages, *, headers=(), method="POST", path="/api/geometry/reconstruct",
                     root_path="", max_bytes=10, read_disconnect=False):
        scope = {"type": "http", "method": method, "path": path,
                 "root_path": root_path, "headers": list(headers)}
        captured = {"called": False, "receive_calls": 0, "body": b"", "messages": [], "sent": []}
        queue = list(messages)

        async def receive():
            captured["receive_calls"] += 1
            return queue.pop(0) if queue else {"type": "http.disconnect"}

        async def send(message):
            captured["sent"].append(message)

        async def downstream(scope, receive, send):
            captured["called"] = True
            while True:
                message = await receive()
                captured["messages"].append(message)
                if message["type"] == "http.disconnect":
                    break
                captured["body"] += message.get("body", b"")
                if not message.get("more_body", False):
                    break
            if read_disconnect:
                captured["following_message"] = await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        await GeometryUploadLimit(downstream, max_bytes=max_bytes)(scope, receive, send)
        return captured

    def status(self, result):
        return next(message["status"] for message in result["sent"] if message["type"] == "http.response.start")

    async def test_declared_oversize_is_rejected_without_reading_or_parsing(self):
        result = await self.invoke([], headers=[(b"content-length", b"8000000")],
                                   max_bytes=MAX_GEOMETRY_REQUEST_BYTES)
        self.assertEqual(self.status(result), 413)
        self.assertFalse(result["called"])
        self.assertEqual(result["receive_calls"], 0)

    async def test_chunked_oversize_never_reaches_downstream(self):
        result = await self.invoke([
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"78901", "more_body": True},
            {"type": "http.request", "body": b"never read", "more_body": False},
        ])
        self.assertEqual(self.status(result), 413)
        self.assertFalse(result["called"])
        self.assertEqual(result["receive_calls"], 2)

    async def test_false_small_length_does_not_bypass_stream_limit(self):
        for length in (b"1", b"not-a-length"):
            with self.subTest(length=length):
                result = await self.invoke([{"type": "http.request", "body": b"x"*11}],
                                           headers=[(b"content-length", length)])
                self.assertEqual(self.status(result), 413)
                self.assertFalse(result["called"])

    async def test_exact_limit_is_buffered_and_replayed_once(self):
        result = await self.invoke([
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"", "more_body": True},
            {"type": "http.request", "body": b"4567890", "more_body": False},
            {"type": "http.disconnect"},
        ], headers=[(b"content-length", b"10")], read_disconnect=True)
        self.assertEqual(self.status(result), 200)
        self.assertEqual(result["body"], b"1234567890")
        self.assertEqual(result["messages"], [{"type": "http.request", "body": b"1234567890", "more_body": False}])
        self.assertEqual(result["following_message"], {"type": "http.disconnect"})

    async def test_empty_body_is_replayed(self):
        result = await self.invoke([{"type": "http.request", "body": b"", "more_body": False}])
        self.assertEqual(self.status(result), 200)
        self.assertTrue(result["called"])
        self.assertEqual(result["body"], b"")

    async def test_disconnect_abandons_partial_upload_without_response(self):
        result = await self.invoke([
            {"type": "http.request", "body": b"partial", "more_body": True},
            {"type": "http.disconnect"},
        ])
        self.assertFalse(result["called"])
        self.assertEqual(result["sent"], [])

    async def test_other_routes_and_methods_pass_through_original_chunks(self):
        messages = [{"type": "http.request", "body": b"x"*8, "more_body": True},
                    {"type": "http.request", "body": b"y"*8, "more_body": False}]
        for method, path in (("GET", "/api/geometry/reconstruct"), ("POST", "/api/detect"),
                             ("POST", "/api/geometry/review")):
            with self.subTest(method=method, path=path):
                result = await self.invoke(messages, method=method, path=path,
                                           headers=[(b"content-length", b"999999999")])
                self.assertEqual(self.status(result), 200)
                self.assertEqual(result["messages"], messages)
                self.assertEqual(result["body"], b"x"*8+b"y"*8)

    async def test_non_http_protocol_is_passed_through(self):
        calls=[]
        async def downstream(scope, receive, send):
            calls.append(scope["type"])
        async def unused():
            raise AssertionError("This protocol should not be read by the limiter")
        await GeometryUploadLimit(downstream)({"type": "lifespan"}, unused, unused)
        self.assertEqual(calls, ["lifespan"])

    async def test_root_path_deployment_is_still_limited(self):
        for path in ("/prefix/api/geometry/reconstruct", "/api/geometry/reconstruct"):
            with self.subTest(path=path):
                result = await self.invoke([], path=path, root_path="/prefix",
                                           headers=[(b"content-length", b"11")])
                self.assertEqual(self.status(result), 413)
                self.assertFalse(result["called"])

    async def test_length_comparison_handles_leading_zeroes_and_huge_headers(self):
        for length in (b"00000011", b"9"*5000):
            with self.subTest(length_size=len(length)):
                result = await self.invoke([], headers=[(b"content-length", length)])
                self.assertEqual(self.status(result), 413)
                self.assertEqual(result["receive_calls"], 0)
        result = await self.invoke([{"type": "http.request", "body": b"0123456789"}],
                                   headers=[(b"content-length", b"00000010")])
        self.assertEqual(self.status(result), 200)


if __name__ == "__main__":
    unittest.main()

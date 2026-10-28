"""Bound geometry uploads before FastAPI's multipart parser receives any body.

The endpoint still validates each file. This outer limit also caps the combined
multipart request, including extra fields/files, before parsing or file spooling.
Other endpoints, methods and ASGI protocols are passed through unchanged.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_GEOMETRY_REQUEST_BYTES = 6_100_000
_ERROR = b'{"error":"Geometry upload is too large. Send up to three WAV files smaller than 2 MB each."}'


def _too_long(value: bytes, limit: int) -> bool:
    """Compare a valid decimal length without parsing an arbitrarily large int."""
    value = value.strip()
    if not value.isdigit():
        # An invalid/missing declaration never disables the actual stream limit.
        return False
    value = value.lstrip(b"0") or b"0"
    maximum = str(limit).encode("ascii")
    return len(value) > len(maximum) or (len(value) == len(maximum) and value > maximum)


class GeometryUploadLimit:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_GEOMETRY_REQUEST_BYTES):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("The geometry request limit must be a positive integer.")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        root = scope.get("root_path", "")
        # Mounted/root-path deployments may include the prefix in scope.path.
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        if scope["type"] != "http" or scope.get("method") != "POST" or path != "/api/geometry/reconstruct":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length" and _too_long(value, self.max_bytes):
                await self._reject(send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                # The client has gone away: do not invoke the parser or attempt
                # to send a response to an already disconnected connection.
                return
            if message["type"] != "http.request":
                raise RuntimeError("Unexpected ASGI message while reading a geometry request.")
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await self._reject(send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        buffered = bytes(body)
        del body, message, chunk
        pending = True

        async def replay() -> Message:
            nonlocal pending, buffered
            if pending:
                pending = False
                chunk, buffered = buffered, b""
                return {"type": "http.request", "body": chunk, "more_body": False}
            # Preserve normal disconnect behavior for downstream ASGI apps.
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(_ERROR)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": _ERROR})

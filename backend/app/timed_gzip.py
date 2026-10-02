"""Starlette GZip middleware with compression time published to request metrics."""
from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipResponder, IdentityResponder

from . import perf


class _TimedGZipResponder(GZipResponder):
    def apply_compression(self, body: bytes, *, more_body: bool) -> bytes:
        with perf.phase("gzip"):
            return super().apply_compression(body, more_body=more_body)


class TimedGZipMiddleware:
    def __init__(self, app, minimum_size=500, compresslevel=9):
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if "gzip" in headers.get("Accept-Encoding", ""):
            responder = _TimedGZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel)
        else:
            responder = IdentityResponder(self.app, self.minimum_size)
        await responder(scope, receive, send)

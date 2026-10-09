"""Helpers for running the API as a serverless function (Vercel)."""

from urllib.parse import parse_qsl, urlencode


class RestorePath:
    """Pure-ASGI middleware: restore the original request path from the rewrite's ?__path= parameter.

    vercel.json rewrites every URL to /api/index?__path=<original path>, because Vercel's Python
    runtime otherwise hands the app the function's own path. Add with app.add_middleware(RestorePath).
    """

    def __init__(self, app):
        self.inner = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            query = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
            original = [v for k, v in query if k == "__path"]
            if original:
                path = "/" + original[0].lstrip("/")
                rest = urlencode([(k, v) for k, v in query if k != "__path"])
                scope = dict(scope, path=path, raw_path=path.encode(), query_string=rest.encode())
        await self.inner(scope, receive, send)

import os
import sys

# Ensure root directory is on Python path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from main import app as fastapi_app

async def app(scope, receive, send):
    """
    ASGI adapter for Vercel Serverless:
    When Vercel rewrites /api/* to /api/index.py, the original route
    is passed in the 'x-matched-path' header. This adapter restores
    the original path so FastAPI route matching succeeds 100%.
    """
    if scope.get("type") == "http":
        headers = dict(scope.get("headers", []))
        matched_path = headers.get(b"x-matched-path")
        if matched_path:
            path_str = matched_path.decode("utf-8", errors="ignore").split("?")[0]
            scope_path = scope.get("path", "")
            if "index.py" in scope_path or scope_path in ("", "/"):
                scope["path"] = path_str
    await fastapi_app(scope, receive, send)

handler = app

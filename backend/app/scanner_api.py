"""Authenticated HTTP boundary around the local ClamAV daemon."""
import os
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from .attachments import scanner

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def verify_caller(authorization):
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    scheme, _, token = (authorization or "").partition(" ")
    audience = os.environ.get("SCANNER_AUDIENCE")
    callers = set(os.environ.get("SCANNER_CALLERS", "").split(",")) - {""}
    if scheme.lower() != "bearer" or not token or not audience or not callers: return False
    try:
        claims = id_token.verify_oauth2_token(token, Request(), audience=audience)
        return claims.get("email") in callers and claims.get("email_verified") is True
    except Exception:
        return False


@app.get("/livez")
def livez(): return {"status": "live"}


@app.post("/scan")
async def scan(request: Request, authorization: str = Header(default=None)):
    if not await run_in_threadpool(verify_caller, authorization):
        return JSONResponse({"code": "caller_refused"}, status_code=403)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 25 * 1024 * 1024:
            return JSONResponse({"code": "file_too_large"}, status_code=413)
    try:
        return await run_in_threadpool(scanner.scan, bytes(raw))
    except scanner.Infected as exc:
        return JSONResponse({"signature": exc.signature}, status_code=422)
    except scanner.ScannerUnavailable:
        return JSONResponse({"code": "scanner_unavailable"}, status_code=503)


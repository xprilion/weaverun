import json
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from .detect import is_openai_compatible
from .upstream import resolve_upstream
from .weave_log import WeaveLogger

# RFC 2616 hop-by-hop headers - must not forward
HOP_BY_HOP_HEADERS = frozenset([
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
])

_client: httpx.AsyncClient | None = None
_logger: WeaveLogger | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client, _logger
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(90.0, connect=10.0),
        follow_redirects=True,
    )
    _logger = WeaveLogger()
    yield
    await _client.aclose()


app = FastAPI(lifespan=lifespan)


def _parse_json(data: bytes):
    """Parse JSON bytes, return None on failure."""
    if not data:
        return None
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _filter_headers(headers: httpx.Headers) -> dict[str, str]:
    """Remove hop-by-hop headers."""
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy(path: str, request: Request):
    """Forward request to upstream, log OpenAI-compatible calls."""
    if _client is None:
        return Response(content=b"Proxy not initialized", status_code=503)

    # Resolve upstream URL
    try:
        upstream_url = resolve_upstream(path)
    except ValueError as e:
        print(f"weaverun: {e}", file=sys.stderr)
        return Response(content=str(e).encode(), status_code=502)

    # Prepare request
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    
    start = time.perf_counter()

    # Forward to upstream
    try:
        resp = await _client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body,
            params=request.query_params,
        )
        content = resp.content
        latency_ms = (time.perf_counter() - start) * 1000
    except httpx.TimeoutException:
        print("weaverun: Upstream timeout", file=sys.stderr)
        return Response(content=b"Upstream timeout", status_code=504)
    except httpx.ConnectError as e:
        print(f"weaverun: Connection failed: {e}", file=sys.stderr)
        return Response(content=b"Connection failed", status_code=502)
    except Exception as e:
        print(f"weaverun: Request failed: {e}", file=sys.stderr)
        return Response(content=b"Request failed", status_code=502)

    # Log OpenAI-compatible calls (best-effort)
    if _logger and is_openai_compatible(path):
        req_json = _parse_json(body)
        resp_json = _parse_json(content)
        model = req_json.get("model") if isinstance(req_json, dict) else None
        
        _logger.log(
            path=f"/{path}",
            upstream=upstream_url,
            request_json=req_json,
            response_json=resp_json,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            model=model,
        )

    return Response(
        content=content,
        status_code=resp.status_code,
        headers=_filter_headers(resp.headers),
        media_type=resp.headers.get("content-type"),
    )

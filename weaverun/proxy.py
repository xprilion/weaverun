import json
import sys
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .dashboard import router as dashboard_router, add_log as dashboard_add_log, update_trace_url
from .detect import is_openai_compatible
from .upstream import resolve_upstream, extract_path
from .weave_log import WeaveLogger

# RFC 2616 hop-by-hop headers - must not forward
HOP_BY_HOP_HEADERS = frozenset([
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
])

_client: httpx.AsyncClient | None = None
_logger: WeaveLogger | None = None


@asynccontextmanager
async def lifespan(inner_app: FastAPI):
    global _client, _logger
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(90.0, connect=10.0),
        follow_redirects=True,
    )
    _logger = WeaveLogger()
    _logger.start()  # Start background logging worker
    yield
    await _logger.stop()  # Drain queue and stop worker
    await _client.aclose()


inner_app = FastAPI(lifespan=lifespan)
inner_app.include_router(dashboard_router)


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


async def _do_proxy(request: Request, upstream_url: str):
    """Perform the actual proxy request."""
    api_path = extract_path(upstream_url)
    
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    
    start = time.perf_counter()

    try:
        resp = await _client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body,
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

    # Log OpenAI-compatible calls
    if is_openai_compatible(api_path):
        req_json = _parse_json(body)
        resp_json = _parse_json(content)
        model = req_json.get("model") if isinstance(req_json, dict) else None
        
        # Log to dashboard immediately (in-memory, no latency)
        # trace_pending=True shows spinning donut while Weave logs in background
        entry_id = dashboard_add_log(
            path=api_path,
            model=model,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            upstream=upstream_url,
            trace_url=None,
            trace_pending=_logger is not None,
            request_body=req_json,
            response_body=resp_json,
        )
        
        # Queue Weave logging in background (non-blocking)
        # Callback updates dashboard with trace URL when ready
        if _logger:
            _logger.log_async(
                path=api_path,
                upstream=upstream_url,
                request_json=req_json,
                response_json=resp_json,
                status_code=resp.status_code,
                latency_ms=latency_ms,
                model=model,
                trace_callback=lambda url, eid=entry_id: update_trace_url(eid, url),
            )

    return Response(
        content=content,
        status_code=resp.status_code,
        headers=_filter_headers(resp.headers),
        media_type=resp.headers.get("content-type"),
    )


@inner_app.api_route("/__proxy__", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_handler(request: Request):
    """Handle proxy-style requests (full URL in path)."""
    if _client is None:
        return Response(content=b"Proxy not initialized", status_code=503)
    
    proxy_url = getattr(request.state, 'proxy_url', None)
    if not proxy_url:
        return Response(content=b"No proxy URL", status_code=400)
    return await _do_proxy(request, proxy_url)


@inner_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy(path: str, request: Request):
    """Forward request to upstream, log OpenAI-compatible calls."""
    if path.startswith("__weaverun__"):
        return Response(status_code=404)
    
    if _client is None:
        return Response(content=b"Proxy not initialized", status_code=503)

    try:
        upstream_url = resolve_upstream(path)
    except ValueError as e:
        print(f"weaverun: {e}", file=sys.stderr)
        return Response(content=str(e).encode(), status_code=502)

    return await _do_proxy(request, upstream_url)


class ProxyApp:
    """ASGI app that handles HTTP proxy-style requests."""
    
    def __init__(self, app: ASGIApp):
        self.app = app
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            
            # Ensure state dict exists
            if "state" not in scope:
                scope["state"] = {}
            
            # Handle proxy-style paths (full URL as path)
            if path.startswith("http://") or path.startswith("https://"):
                scope["state"]["proxy_url"] = path
                scope["path"] = "/__proxy__"
            elif path.startswith("//"):
                scope["state"]["proxy_url"] = f"http:{path}"
                scope["path"] = "/__proxy__"
            elif path.startswith("/http://") or path.startswith("/https://"):
                scope["state"]["proxy_url"] = path[1:]
                scope["path"] = "/__proxy__"
        
        await self.app(scope, receive, send)


# Wrap the FastAPI app with our proxy handler
app = ProxyApp(inner_app)

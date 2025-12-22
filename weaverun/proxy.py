import json
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Response
from starlette.responses import StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import is_debug_mode
from .dashboard import router as dashboard_router, add_log as dashboard_add_log, update_trace_url, update_log_entry
from .detect import is_capturable_endpoint
from .trace_context import extract_trace_context
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


def _is_streaming_request(body: bytes) -> bool:
    """Check if request has stream: true."""
    try:
        data = json.loads(body)
        return isinstance(data, dict) and data.get("stream") is True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


def _parse_sse_chunks(chunks: list[bytes]) -> dict | None:
    """
    Parse SSE chunks from streaming response and reconstruct the complete response.
    Returns a dict with aggregated content for logging.
    """
    all_content = ""
    model = None
    finish_reason = None
    usage = None
    response_id = None
    
    for chunk in chunks:
        try:
            text = chunk.decode("utf-8", errors="ignore")
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        if not response_id:
                            response_id = data.get("id")
                        if not model:
                            model = data.get("model")
                        
                        # Extract content from choices
                        choices = data.get("choices", [])
                        for choice in choices:
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                all_content += content
                            if choice.get("finish_reason"):
                                finish_reason = choice.get("finish_reason")
                        
                        # Some APIs include usage in the final chunk
                        if data.get("usage"):
                            usage = data.get("usage")
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
    
    if not all_content and not response_id:
        return None
    
    # Reconstruct a response-like object for logging
    return {
        "id": response_id,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": all_content},
            "finish_reason": finish_reason,
        }],
        "usage": usage,
        "_streamed": True,
    }


async def _do_proxy(request: Request, upstream_url: str):
    """Perform the actual proxy request."""
    api_path = extract_path(upstream_url)
    
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    
    # Check if this is a streaming request and if endpoint should be captured
    is_streaming = _is_streaming_request(body)
    should_capture, provider = is_capturable_endpoint(api_path, upstream_url)
    
    start = time.perf_counter()

    if is_streaming:
        # Handle streaming request
        return await _do_streaming_proxy(
            request, upstream_url, api_path, body, headers, start, should_capture, provider
        )
    
    # Non-streaming request
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

    # Log capturable API calls (OpenAI, Anthropic, Gemini, Bedrock, Azure, etc.)
    if should_capture:
        req_json = _parse_json(body)
        resp_json = _parse_json(content)
        model = req_json.get("model") if isinstance(req_json, dict) else None
        
        # Extract trace context for hierarchical grouping
        trace_ctx = extract_trace_context(headers, req_json)
        
        # Check if we're in debug mode (observe without logging to Weave)
        debug = is_debug_mode()
        
        # Log to dashboard immediately (in-memory, no latency)
        # trace_pending=True shows spinning donut while Weave logs in background
        # In debug mode, trace_pending=False since we won't be logging
        entry_id = dashboard_add_log(
            path=api_path,
            model=model,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            upstream=upstream_url,
            trace_url=None,
            trace_pending=_logger is not None and not debug,
            request_body=req_json,
            response_body=resp_json,
            provider=provider,
            trace_id=trace_ctx.trace_id,
            span_id=trace_ctx.span_id,
            parent_span_id=trace_ctx.parent_span_id,
            debug_mode=debug,
        )
        
        # Queue Weave logging in background (non-blocking)
        # Skip logging in debug mode - just observe traffic
        # Callback updates dashboard with trace URL when ready
        if _logger and not debug:
            _logger.log_async(
                path=api_path,
                upstream=upstream_url,
                request_json=req_json,
                response_json=resp_json,
                status_code=resp.status_code,
                latency_ms=latency_ms,
                model=model,
                provider=provider,
                trace_id=trace_ctx.trace_id,
                span_id=trace_ctx.span_id,
                parent_span_id=trace_ctx.parent_span_id,
                trace_callback=lambda url, eid=entry_id: update_trace_url(eid, url),
            )

    return Response(
        content=content,
        status_code=resp.status_code,
        headers=_filter_headers(resp.headers),
        media_type=resp.headers.get("content-type"),
    )


async def _do_streaming_proxy(
    request: Request,
    upstream_url: str,
    api_path: str,
    body: bytes,
    headers: dict,
    start: float,
    should_capture: bool,
    provider: str | None,
):
    """Handle streaming proxy request."""
    req_json = _parse_json(body) if should_capture else None
    model = req_json.get("model") if isinstance(req_json, dict) else None
    
    # Extract trace context for hierarchical grouping
    trace_ctx = extract_trace_context(headers, req_json) if should_capture else None
    
    # Check if we're in debug mode (observe without logging to Weave)
    debug = is_debug_mode() if should_capture else False
    
    # For streaming, we log immediately with placeholder response
    # and update with full content when stream completes
    entry_id = None
    if should_capture:
        entry_id = dashboard_add_log(
            path=api_path,
            model=model,
            status_code=200,  # Optimistic, will be accurate for most cases
            latency_ms=0,  # Will update when first chunk arrives
            upstream=upstream_url,
            trace_url=None,
            trace_pending=_logger is not None and not debug,
            request_body=req_json,
            response_body={"_streaming": True, "_status": "in_progress"},
            provider=provider,
            trace_id=trace_ctx.trace_id if trace_ctx else None,
            span_id=trace_ctx.span_id if trace_ctx else None,
            parent_span_id=trace_ctx.parent_span_id if trace_ctx else None,
            debug_mode=debug,
        )
    
    # State shared between generator and completion callback
    state = {
        "chunks": [],
        "status_code": 200,
        "headers": {},
        "first_chunk_time": None,
        "error": None,
    }
    
    async def stream_generator() -> AsyncGenerator[bytes, None]:
        """Stream chunks from upstream to client while accumulating for logging."""
        try:
            async with _client.stream(
                method=request.method,
                url=upstream_url,
                headers=headers,
                content=body,
            ) as resp:
                state["status_code"] = resp.status_code
                state["headers"] = dict(resp.headers)
                
                async for chunk in resp.aiter_bytes():
                    if state["first_chunk_time"] is None:
                        state["first_chunk_time"] = time.perf_counter()
                    state["chunks"].append(chunk)
                    yield chunk
                    
        except httpx.TimeoutException:
            state["error"] = "timeout"
            yield b"data: {\"error\": \"Upstream timeout\"}\n\n"
        except httpx.ConnectError as e:
            state["error"] = "connect"
            yield b"data: {\"error\": \"Connection failed\"}\n\n"
        except Exception as e:
            state["error"] = str(e)
            yield b"data: {\"error\": \"Request failed\"}\n\n"
        finally:
            # Log completed stream
            if should_capture and entry_id:
                end_time = time.perf_counter()
                ttfb = ((state["first_chunk_time"] or end_time) - start) * 1000
                total_time = (end_time - start) * 1000
                
                # Parse accumulated chunks to reconstruct response
                resp_json = _parse_sse_chunks(state["chunks"])
                if resp_json:
                    resp_json["_ttfb_ms"] = round(ttfb, 1)
                    resp_json["_total_ms"] = round(total_time, 1)
                
                # Update dashboard entry with final response (sends SSE update)
                update_log_entry(
                    entry_id,
                    response_body=resp_json,
                    latency_ms=ttfb,
                    status_code=state["status_code"],
                )
                
                # Queue Weave logging (skip in debug mode)
                if _logger and not debug:
                    _logger.log_async(
                        path=api_path,
                        upstream=upstream_url,
                        request_json=req_json,
                        response_json=resp_json,
                        status_code=state["status_code"],
                        latency_ms=ttfb,
                        model=model,
                        provider=provider,
                        trace_id=trace_ctx.trace_id if trace_ctx else None,
                        span_id=trace_ctx.span_id if trace_ctx else None,
                        parent_span_id=trace_ctx.parent_span_id if trace_ctx else None,
                        trace_callback=lambda url, eid=entry_id: update_trace_url(eid, url),
                    )
    
    # Return streaming response immediately
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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

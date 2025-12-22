import asyncio
import json
import uuid
from collections import deque
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

_logs: deque = deque(maxlen=100)
_logs_by_id: dict[str, "LogEntry"] = {}
_subscribers: list[asyncio.Queue] = []


@dataclass
class LogEntry:
    id: str
    timestamp: str
    method: str
    path: str
    model: str | None
    status_code: int
    latency_ms: float
    upstream: str
    trace_url: str | None
    trace_pending: bool
    request_body: dict | list | None
    response_body: dict | list | None
    provider: str | None = None
    # Trace context for hierarchical grouping
    trace_id: str | None = None       # Groups related calls together
    span_id: str | None = None        # This call's unique span
    parent_span_id: str | None = None # Parent call's span (for tree structure)
    # Debug mode indicator
    debug_mode: bool = False          # True when in debug mode (would-be-logged)


@dataclass
class TraceUpdate:
    """Event for updating trace URL on an existing log entry."""
    type: str = field(default="trace_update", init=False)
    id: str = ""
    trace_url: str | None = None


def add_log(
    *,
    path: str,
    model: str | None,
    status_code: int,
    latency_ms: float,
    upstream: str,
    trace_url: str | None = None,
    trace_pending: bool = False,
    request_body: dict | list | None = None,
    response_body: dict | list | None = None,
    provider: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    debug_mode: bool = False,
) -> str:
    """Add log entry and notify subscribers. Returns the entry ID."""
    entry_id = str(uuid.uuid4())[:8]
    # Generate span_id if not provided (use entry_id)
    if span_id is None:
        span_id = entry_id
    entry = LogEntry(
        id=entry_id,
        timestamp=datetime.now().strftime("%H:%M:%S"),
        method="POST",
        path=path,
        model=model,
        status_code=status_code,
        latency_ms=round(latency_ms, 1),
        upstream=upstream,
        trace_url=trace_url,
        trace_pending=trace_pending,
        request_body=request_body,
        response_body=response_body,
        provider=provider,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        debug_mode=debug_mode,
    )
    _logs.append(entry)
    _logs_by_id[entry_id] = entry

    # Clean up old entries from the lookup dict
    while len(_logs_by_id) > 100:
        oldest = next(iter(_logs_by_id))
        del _logs_by_id[oldest]

    for queue in _subscribers:
        try:
            queue.put_nowait({"type": "log", "data": entry})
        except asyncio.QueueFull:
            pass

    return entry_id


def update_trace_url(entry_id: str, trace_url: str | None):
    """Update trace URL for an existing log entry and notify subscribers."""
    entry = _logs_by_id.get(entry_id)
    if entry:
        entry.trace_url = trace_url
        entry.trace_pending = False

        update = TraceUpdate(id=entry_id, trace_url=trace_url)
        for queue in _subscribers:
            try:
                queue.put_nowait({"type": "trace_update", "data": update})
            except asyncio.QueueFull:
                pass


def update_log_entry(
    entry_id: str,
    *,
    response_body: dict | list | None = None,
    latency_ms: float | None = None,
    status_code: int | None = None,
):
    """Update a log entry's fields and notify subscribers."""
    entry = _logs_by_id.get(entry_id)
    if not entry:
        return

    if response_body is not None:
        entry.response_body = response_body
    if latency_ms is not None:
        entry.latency_ms = round(latency_ms, 1)
    if status_code is not None:
        entry.status_code = status_code

    # Send full entry update to subscribers
    for queue in _subscribers:
        try:
            queue.put_nowait({"type": "log_update", "data": entry})
        except asyncio.QueueFull:
            pass


async def _event_stream() -> AsyncGenerator[str, None]:
    """SSE event stream for real-time updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(queue)

    try:
        # Send existing logs
        for entry in _logs:
            payload = {"type": "log", **asdict(entry)}
            yield f"data: {json.dumps(payload)}\n\n"

        while True:
            msg = await queue.get()
            if msg["type"] == "log":
                payload = {"type": "log", **asdict(msg["data"])}
            elif msg["type"] == "log_update":
                payload = {"type": "log_update", **asdict(msg["data"])}
            else:
                payload = {"type": "trace_update", "id": msg["data"].id, "trace_url": msg["data"].trace_url}
            yield f"data: {json.dumps(payload)}\n\n"
    finally:
        _subscribers.remove(queue)


@router.get("/__weaverun__/events")
async def events():
    """SSE endpoint for real-time log updates."""
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/__weaverun__")
async def dashboard(request: Request):
    """Dashboard page (Jinja template)."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/__weaverun__/config")
async def get_dashboard_config():
    """
    Return the currently loaded config for display in the dashboard.
    Only includes safe, non-secret fields.
    """
    from .config import get_config

    cfg = get_config()
    return JSONResponse({
        "capture_all_requests": cfg.capture_all_requests,
        "config_path": cfg.config_path,
        "debug": cfg.debug,
        "providers": [
            {
                "name": p.name,
                "path_patterns": p.path_patterns,
                "host_patterns": p.host_patterns,
                "is_regex": p.is_regex,
            }
            for p in cfg.providers
        ],
    })

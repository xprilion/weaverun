import asyncio
import json
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

router = APIRouter()

_logs: deque = deque(maxlen=100)
_subscribers: list[asyncio.Queue] = []


@dataclass
class LogEntry:
    timestamp: str
    method: str
    path: str
    model: str | None
    status_code: int
    latency_ms: float
    upstream: str
    trace_url: str | None


def add_log(
    *,
    path: str,
    model: str | None,
    status_code: int,
    latency_ms: float,
    upstream: str,
    trace_url: str | None = None,
):
    """Add log entry and notify subscribers."""
    entry = LogEntry(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        method="POST",
        path=path,
        model=model,
        status_code=status_code,
        latency_ms=round(latency_ms, 1),
        upstream=upstream,
        trace_url=trace_url,
    )
    _logs.append(entry)
    
    for queue in _subscribers:
        try:
            queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass


async def _event_stream() -> AsyncGenerator[str, None]:
    """SSE event stream for real-time updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(queue)
    
    try:
        for entry in _logs:
            yield f"data: {json.dumps(asdict(entry))}\n\n"
        
        while True:
            entry = await queue.get()
            yield f"data: {json.dumps(asdict(entry))}\n\n"
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
async def dashboard():
    """Minimal real-time dashboard."""
    return HTMLResponse(DASHBOARD_HTML)


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>weaverun</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
            background: #0a0a0f;
            color: #e4e4e7;
            min-height: 100vh;
            padding: 24px;
        }
        
        .header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid #27272a;
        }
        
        .logo {
            font-size: 20px;
            font-weight: 600;
            background: linear-gradient(135deg, #06b6d4, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .status {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: #71717a;
        }
        
        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #22c55e;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .count {
            margin-left: auto;
            font-size: 13px;
            color: #71717a;
        }
        
        .logs {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .log {
            display: grid;
            grid-template-columns: 70px 60px 1fr auto auto auto auto;
            gap: 16px;
            align-items: center;
            padding: 12px 16px;
            background: #18181b;
            border-radius: 8px;
            font-size: 13px;
            animation: slideIn 0.2s ease-out;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .time { color: #71717a; }
        
        .method {
            font-weight: 600;
            color: #22c55e;
        }
        
        .path {
            color: #e4e4e7;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .model {
            color: #8b5cf6;
            font-size: 12px;
        }
        
        .status-code {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .status-2xx { background: #14532d; color: #4ade80; }
        .status-4xx { background: #713f12; color: #fbbf24; }
        .status-5xx { background: #7f1d1d; color: #f87171; }
        
        .latency {
            color: #71717a;
            font-size: 12px;
            text-align: right;
            min-width: 60px;
        }
        
        .trace-link {
            font-size: 12px;
            text-decoration: none;
            padding: 2px 8px;
            border-radius: 4px;
            background: #1e1b4b;
            color: #a78bfa;
            transition: background 0.15s;
        }
        
        .trace-link:hover {
            background: #312e81;
        }
        
        .trace-none {
            font-size: 12px;
            color: #52525b;
        }
        
        .empty {
            text-align: center;
            padding: 48px;
            color: #52525b;
        }
        
        @media (max-width: 768px) {
            .log {
                grid-template-columns: 1fr;
                gap: 8px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <span class="logo">weaverun</span>
        <span class="status"><span class="dot"></span> live</span>
        <span class="count" id="count">0 requests</span>
    </div>
    
    <div class="logs" id="logs">
        <div class="empty">Waiting for requests...</div>
    </div>
    
    <script>
        const logs = document.getElementById('logs');
        const count = document.getElementById('count');
        let total = 0;
        
        function statusClass(code) {
            if (code >= 200 && code < 300) return 'status-2xx';
            if (code >= 400 && code < 500) return 'status-4xx';
            return 'status-5xx';
        }
        
        function traceLink(url) {
            if (url) {
                return `<a href="${url}" target="_blank" class="trace-link">🍩 trace</a>`;
            }
            return `<span class="trace-none">-</span>`;
        }
        
        function addLog(entry) {
            if (total === 0) logs.innerHTML = '';
            total++;
            count.textContent = `${total} request${total === 1 ? '' : 's'}`;
            
            const el = document.createElement('div');
            el.className = 'log';
            el.innerHTML = `
                <span class="time">${entry.timestamp}</span>
                <span class="method">${entry.method}</span>
                <span class="path">${entry.path}</span>
                <span class="model">${entry.model || '-'}</span>
                <span class="status-code ${statusClass(entry.status_code)}">${entry.status_code}</span>
                <span class="latency">${entry.latency_ms}ms</span>
                ${traceLink(entry.trace_url)}
            `;
            logs.insertBefore(el, logs.firstChild);
            
            while (logs.children.length > 50) {
                logs.removeChild(logs.lastChild);
            }
        }
        
        const evtSource = new EventSource('/__weaverun__/events');
        evtSource.onmessage = (e) => addLog(JSON.parse(e.data));
        evtSource.onerror = () => console.log('SSE reconnecting...');
    </script>
</body>
</html>
"""

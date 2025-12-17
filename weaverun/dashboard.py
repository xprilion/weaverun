import asyncio
import json
import uuid
from collections import deque
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

router = APIRouter()

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
) -> str:
    """Add log entry and notify subscribers. Returns the entry ID."""
    entry_id = str(uuid.uuid4())[:8]
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
        
        .log-wrapper {
            animation: slideIn 0.2s ease-out;
        }
        
        .log {
            display: grid;
            grid-template-columns: 24px 70px 60px 1fr auto auto auto auto;
            gap: 16px;
            align-items: center;
            padding: 12px 16px;
            background: #18181b;
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            transition: background 0.15s;
        }
        
        .log:hover {
            background: #1f1f23;
        }
        
        .log-wrapper.expanded .log {
            border-radius: 8px 8px 0 0;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .expand-icon {
            color: #52525b;
            font-size: 10px;
            transition: transform 0.2s;
            user-select: none;
        }
        
        .log-wrapper.expanded .expand-icon {
            transform: rotate(90deg);
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
        
        .trace-pending {
            font-size: 12px;
            display: inline-block;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        .stream-badge {
            font-size: 9px;
            padding: 1px 4px;
            border-radius: 3px;
            background: #312e81;
            color: #a78bfa;
            margin-left: 4px;
            vertical-align: middle;
        }
        
        .streaming-indicator {
            display: inline-block;
            width: 6px;
            height: 6px;
            background: #8b5cf6;
            border-radius: 50%;
            margin-left: 4px;
            animation: pulse 1s infinite;
        }
        
        .details {
            display: none;
            background: #111114;
            border-radius: 0 0 8px 8px;
            border-top: 1px solid #27272a;
            overflow: hidden;
        }
        
        .log-wrapper.expanded .details {
            display: block;
        }
        
        .details-panels {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1px;
            background: #27272a;
        }
        
        .panel {
            background: #111114;
            padding: 16px;
            max-height: 400px;
            overflow: auto;
        }
        
        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
        }
        
        .panel-title {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .panel-title.request {
            color: #06b6d4;
        }
        
        .panel-title.response {
            color: #22c55e;
        }
        
        .copy-btn {
            font-size: 11px;
            padding: 3px 8px;
            border: none;
            border-radius: 4px;
            background: #27272a;
            color: #a1a1aa;
            cursor: pointer;
            transition: all 0.15s;
        }
        
        .copy-btn:hover {
            background: #3f3f46;
            color: #e4e4e7;
        }
        
        .copy-btn.copied {
            background: #14532d;
            color: #4ade80;
        }
        
        .json-view {
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-all;
            color: #a1a1aa;
        }
        
        .json-view .key { color: #06b6d4; }
        .json-view .string { color: #fbbf24; }
        .json-view .number { color: #a78bfa; }
        .json-view .boolean { color: #f472b6; }
        .json-view .null { color: #71717a; }
        
        .empty-body {
            color: #52525b;
            font-style: italic;
        }
        
        .empty {
            text-align: center;
            padding: 48px;
            color: #52525b;
        }
        
        @media (max-width: 900px) {
            .log {
                grid-template-columns: 24px 1fr auto auto;
                gap: 12px;
            }
            .log .time, .log .method, .log .path { display: none; }
            .details-panels {
                grid-template-columns: 1fr;
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
        
        function isStreaming(entry) {
            return entry.request_body && entry.request_body.stream === true;
        }
        
        function streamBadge(entry) {
            if (!isStreaming(entry)) return '';
            const resp = entry.response_body;
            if (resp && resp._streaming && resp._status === 'in_progress') {
                return '<span class="streaming-indicator" title="Streaming"></span>';
            }
            return '<span class="stream-badge">stream</span>';
        }
        
        function traceLink(entry) {
            if (entry.trace_url) {
                return `<a href="${entry.trace_url}" target="_blank" class="trace-link" onclick="event.stopPropagation()">🍩 trace</a>`;
            }
            if (entry.trace_pending) {
                return `<span class="trace-pending" title="Logging to Weave...">🍩</span>`;
            }
            return `<span class="trace-none">-</span>`;
        }
        
        function syntaxHighlight(json) {
            if (json === null || json === undefined) {
                return '<span class="empty-body">No body</span>';
            }
            const str = JSON.stringify(json, null, 2);
            return str.replace(/("(\\\\u[a-zA-Z0-9]{4}|\\\\[^u]|[^\\\\"])*"(\\s*:)?|\\b(true|false|null)\\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g, (match) => {
                let cls = 'number';
                if (/^"/.test(match)) {
                    if (/:$/.test(match)) {
                        cls = 'key';
                        match = match.slice(0, -1) + '</span><span>:';
                    } else {
                        cls = 'string';
                    }
                } else if (/true|false/.test(match)) {
                    cls = 'boolean';
                } else if (/null/.test(match)) {
                    cls = 'null';
                }
                return `<span class="${cls}">${match}</span>`;
            });
        }
        
        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }
        
        function copyToClipboard(btn, data) {
            event.stopPropagation();
            const text = data ? JSON.stringify(data, null, 2) : '';
            navigator.clipboard.writeText(text).then(() => {
                btn.classList.add('copied');
                btn.textContent = 'Copied!';
                setTimeout(() => {
                    btn.classList.remove('copied');
                    btn.textContent = 'Copy';
                }, 1500);
            });
        }
        
        function toggleExpand(wrapper) {
            wrapper.classList.toggle('expanded');
        }
        
        function addLog(entry) {
            if (total === 0) logs.innerHTML = '';
            total++;
            count.textContent = `${total} request${total === 1 ? '' : 's'}`;
            
            const wrapper = document.createElement('div');
            wrapper.className = 'log-wrapper';
            wrapper.id = 'entry-' + entry.id;
            
            wrapper.innerHTML = `
                <div class="log" onclick="toggleExpand(this.parentElement)">
                    <span class="expand-icon">▶</span>
                    <span class="time">${escapeHtml(entry.timestamp)}</span>
                    <span class="method">${escapeHtml(entry.method)}${streamBadge(entry)}</span>
                    <span class="path">${escapeHtml(entry.path)}</span>
                    <span class="model">${escapeHtml(entry.model || '-')}</span>
                    <span class="status-code ${statusClass(entry.status_code)}">${entry.status_code}</span>
                    <span class="latency">${entry.latency_ms}ms</span>
                    <span class="trace-slot" data-id="${entry.id}">${traceLink(entry)}</span>
                </div>
                <div class="details">
                    <div class="details-panels">
                        <div class="panel">
                            <div class="panel-header">
                                <span class="panel-title request">Request</span>
                                <button class="copy-btn" id="copy-req-${entry.id}">Copy</button>
                            </div>
                            <div class="json-view">${syntaxHighlight(entry.request_body)}</div>
                        </div>
                        <div class="panel">
                            <div class="panel-header">
                                <span class="panel-title response">Response</span>
                                <button class="copy-btn" id="copy-res-${entry.id}">Copy</button>
                            </div>
                            <div class="json-view">${syntaxHighlight(entry.response_body)}</div>
                        </div>
                    </div>
                </div>
            `;
            
            logs.insertBefore(wrapper, logs.firstChild);
            
            // Attach copy handlers after insertion
            const reqBtn = document.getElementById('copy-req-' + entry.id);
            const resBtn = document.getElementById('copy-res-' + entry.id);
            if (reqBtn) reqBtn.onclick = () => copyToClipboard(reqBtn, entry.request_body);
            if (resBtn) resBtn.onclick = () => copyToClipboard(resBtn, entry.response_body);
            
            while (logs.children.length > 50) {
                logs.removeChild(logs.lastChild);
            }
        }
        
        function updateTraceUrl(id, traceUrl) {
            const slot = document.querySelector(`.trace-slot[data-id="${id}"]`);
            if (slot) {
                if (traceUrl) {
                    slot.innerHTML = `<a href="${traceUrl}" target="_blank" class="trace-link" onclick="event.stopPropagation()">🍩 trace</a>`;
                } else {
                    slot.innerHTML = `<span class="trace-none">-</span>`;
                }
            }
        }
        
        function updateLogEntry(entry) {
            const wrapper = document.getElementById('entry-' + entry.id);
            if (!wrapper) return;
            
            // Update latency
            const latencyEl = wrapper.querySelector('.latency');
            if (latencyEl) latencyEl.textContent = entry.latency_ms + 'ms';
            
            // Update status code
            const statusEl = wrapper.querySelector('.status-code');
            if (statusEl) {
                statusEl.textContent = entry.status_code;
                statusEl.className = 'status-code ' + statusClass(entry.status_code);
            }
            
            // Update method badge (remove streaming indicator)
            const methodEl = wrapper.querySelector('.method');
            if (methodEl) {
                methodEl.innerHTML = escapeHtml(entry.method) + streamBadge(entry);
            }
            
            // Update response panel
            const panels = wrapper.querySelectorAll('.panel');
            if (panels.length >= 2) {
                const responsePanel = panels[1];
                const jsonView = responsePanel.querySelector('.json-view');
                if (jsonView) {
                    jsonView.innerHTML = syntaxHighlight(entry.response_body);
                }
                // Update copy button handler
                const copyBtn = responsePanel.querySelector('.copy-btn');
                if (copyBtn) {
                    copyBtn.onclick = () => copyToClipboard(copyBtn, entry.response_body);
                }
            }
        }
        
        function handleEvent(data) {
            if (data.type === 'log') {
                addLog(data);
            } else if (data.type === 'log_update') {
                updateLogEntry(data);
            } else if (data.type === 'trace_update') {
                updateTraceUrl(data.id, data.trace_url);
            }
        }
        
        const evtSource = new EventSource('/__weaverun__/events');
        evtSource.onmessage = (e) => handleEvent(JSON.parse(e.data));
        evtSource.onerror = () => console.log('SSE reconnecting...');
    </script>
</body>
</html>
"""

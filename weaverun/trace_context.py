"""
Trace context extraction for hierarchical call grouping.

Extracts trace IDs from various sources:
- W3C Trace Context headers (traceparent, tracestate)
- OpenTelemetry headers
- Custom headers (x-request-id, x-trace-id, x-correlation-id)
- Request body metadata fields
"""
import re
import uuid
from dataclasses import dataclass


@dataclass
class TraceContext:
    """Extracted trace context for correlating related API calls."""
    trace_id: str | None = None       # Groups related calls (e.g., all calls for one user query)
    span_id: str | None = None        # This specific call's ID
    parent_span_id: str | None = None # Parent call's span ID


# W3C Trace Context format: 00-{trace_id}-{parent_id}-{flags}
# Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
W3C_TRACEPARENT_REGEX = re.compile(
    r'^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$'
)


def _parse_w3c_traceparent(value: str) -> tuple[str | None, str | None]:
    """Parse W3C traceparent header. Returns (trace_id, parent_span_id)."""
    if not value:
        return None, None
    match = W3C_TRACEPARENT_REGEX.match(value.strip().lower())
    if match:
        return match.group(2), match.group(3)
    return None, None


def _extract_from_headers(headers: dict[str, str]) -> TraceContext:
    """Extract trace context from HTTP headers."""
    # Normalize header names to lowercase
    h = {k.lower(): v for k, v in headers.items()}
    
    trace_id = None
    parent_span_id = None
    
    # 1. W3C Trace Context (OpenTelemetry standard)
    if 'traceparent' in h:
        trace_id, parent_span_id = _parse_w3c_traceparent(h['traceparent'])
    
    # 2. Common custom headers (fallbacks)
    if not trace_id:
        for header in ['x-trace-id', 'x-request-id', 'x-correlation-id', 'x-b3-traceid']:
            if header in h and h[header]:
                trace_id = h[header][:32]  # Truncate to 32 chars
                break
    
    # 3. Parent span from custom headers
    if not parent_span_id:
        for header in ['x-parent-id', 'x-b3-parentspanid', 'x-parent-span-id']:
            if header in h and h[header]:
                parent_span_id = h[header][:16]
                break
    
    # Generate new span ID for this call
    span_id = uuid.uuid4().hex[:16]
    
    return TraceContext(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
    )


def _extract_from_body(body: dict | list | None) -> TraceContext | None:
    """Extract trace context from request body metadata."""
    if not isinstance(body, dict):
        return None
    
    trace_id = None
    parent_span_id = None
    
    # Check common metadata locations
    metadata = body.get('metadata', {})
    if isinstance(metadata, dict):
        trace_id = metadata.get('trace_id') or metadata.get('traceId')
        parent_span_id = metadata.get('parent_id') or metadata.get('parentId') or metadata.get('span_id')
    
    # LangChain-style run_id
    if not trace_id:
        run_id = body.get('run_id') or body.get('runId')
        if run_id:
            trace_id = str(run_id)[:32]
    
    # Session/conversation ID as fallback trace ID
    if not trace_id:
        session_id = (
            body.get('session_id') or 
            body.get('sessionId') or 
            body.get('conversation_id') or
            body.get('conversationId') or
            body.get('thread_id') or
            body.get('threadId')
        )
        if session_id:
            trace_id = str(session_id)[:32]
    
    if trace_id:
        return TraceContext(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=parent_span_id,
        )
    
    return None


def extract_trace_context(
    headers: dict[str, str],
    body: dict | list | None = None,
) -> TraceContext:
    """
    Extract trace context from request headers and/or body.
    
    Priority:
    1. W3C Trace Context headers (traceparent)
    2. Custom trace headers (x-trace-id, x-request-id, etc.)
    3. Request body metadata fields
    4. Generate new trace ID if none found
    
    Returns TraceContext with trace_id, span_id, and parent_span_id.
    """
    # Try headers first
    ctx = _extract_from_headers(headers)
    
    # If no trace_id from headers, try body
    if not ctx.trace_id and body:
        body_ctx = _extract_from_body(body)
        if body_ctx and body_ctx.trace_id:
            ctx.trace_id = body_ctx.trace_id
            if body_ctx.parent_span_id and not ctx.parent_span_id:
                ctx.parent_span_id = body_ctx.parent_span_id
    
    # If still no trace_id, generate one (isolated call)
    if not ctx.trace_id:
        ctx.trace_id = uuid.uuid4().hex[:32]
    
    return ctx


def should_group_calls() -> bool:
    """Check if call grouping is enabled (always true for now)."""
    return True


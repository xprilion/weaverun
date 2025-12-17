import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable


def _resolve_project() -> str | None:
    """
    Resolve Weave project from env vars.
    
    Supported formats:
    - WEAVE_PROJECT=entity/project or WEAVE_PROJECT=project
    - WEAVE_PROJECT_ID=project + optional WEAVE_ENTITY=entity
    - WANDB_PROJECT_ID=project (legacy)
    """
    weave_project = os.getenv("WEAVE_PROJECT")
    if weave_project:
        return weave_project
    
    project_id = os.getenv("WEAVE_PROJECT_ID")
    if project_id:
        entity = os.getenv("WEAVE_ENTITY")
        return f"{entity}/{project_id}" if entity else project_id
    
    wandb_project = os.getenv("WANDB_PROJECT_ID")
    if wandb_project:
        return wandb_project
    
    return None


@dataclass
class LogTask:
    """A single logging task to be processed in the background."""
    path: str
    upstream: str
    request_json: dict | list | None
    response_json: dict | list | None
    status_code: int
    latency_ms: float
    model: str | None
    provider: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    trace_callback: Callable[[str | None], None] | None = None


class WeaveLogger:
    """Handles Weave initialization and async background logging. Best-effort, never crashes."""
    
    def __init__(self):
        self._initialized = False
        self._failed = False
        self._warned = False
        self._queue: asyncio.Queue[LogTask] = asyncio.Queue(maxsize=1000)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="weave-log")
        self._worker_task: asyncio.Task | None = None
    
    def _ensure_init(self) -> bool:
        """Lazy init Weave with user's project."""
        if self._initialized or self._failed:
            return self._initialized
        
        project = _resolve_project()
        
        if not project:
            if not self._warned:
                print(
                    "weaverun: Weave logging disabled (set WEAVE_PROJECT, "
                    "WEAVE_PROJECT_ID, or WANDB_PROJECT_ID)",
                    file=sys.stderr
                )
                self._warned = True
            self._failed = True
            return False
        
        try:
            import weave
            weave.init(project)
            self._initialized = True
            return True
        except Exception as e:
            if not self._warned:
                print(f"weaverun: Weave init failed: {e}", file=sys.stderr)
                self._warned = True
            self._failed = True
            return False
    
    def _do_log_sync(self, task: LogTask) -> str | None:
        """Synchronous logging - runs in thread pool."""
        try:
            if not self._ensure_init():
                return None
            
            import weave
            # Use provider name in op for better organization
            provider = task.provider or "api"
            call = weave.log_call(
                op=f"{provider}{task.path}",
                inputs={"path": task.path, "model": task.model, "request": task.request_json},
                output={"status_code": task.status_code, "response": task.response_json},
                attributes={
                    "provider": task.provider,
                    "upstream": task.upstream,
                    "latency_ms": task.latency_ms,
                    "run_id": os.getenv("WEAVE_RUN_ID"),
                    "app": os.getenv("WEAVE_APP_NAME"),
                    # Trace context for hierarchical grouping
                    "trace_id": task.trace_id,
                    "span_id": task.span_id,
                    "parent_span_id": task.parent_span_id,
                },
                use_stack=False,
            )
            return getattr(call, 'ui_url', None)
        except Exception as e:
            if not self._warned:
                print(f"weaverun: Weave logging failed: {e}", file=sys.stderr)
                self._warned = True
            return None
    
    async def _worker(self):
        """Background worker that processes log tasks."""
        loop = asyncio.get_event_loop()
        while True:
            try:
                task = await self._queue.get()
                # Run blocking Weave call in thread pool
                trace_url = await loop.run_in_executor(self._executor, self._do_log_sync, task)
                # Notify callback if provided (for updating dashboard with trace URL)
                if task.trace_callback:
                    try:
                        task.trace_callback(trace_url)
                    except Exception:
                        pass
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._warned:
                    print(f"weaverun: Background worker error: {e}", file=sys.stderr)
                    self._warned = True
    
    def start(self):
        """Start the background worker. Call this during app startup."""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())
    
    async def stop(self):
        """Stop the background worker and drain the queue. Call during shutdown."""
        if self._worker_task:
            # Wait for queue to drain (with timeout)
            try:
                await asyncio.wait_for(self._queue.join(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        self._executor.shutdown(wait=False)
    
    def log_async(
        self,
        *,
        path: str,
        upstream: str,
        request_json,
        response_json,
        status_code: int,
        latency_ms: float,
        model: str | None,
        provider: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        trace_callback: Callable[[str | None], None] | None = None,
    ):
        """Queue a log entry for async processing. Non-blocking, fire-and-forget."""
        task = LogTask(
            path=path,
            upstream=upstream,
            request_json=request_json,
            response_json=response_json,
            status_code=status_code,
            latency_ms=latency_ms,
            model=model,
            provider=provider,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            trace_callback=trace_callback,
        )
        try:
            self._queue.put_nowait(task)
        except asyncio.QueueFull:
            # Drop log if queue is full - we never block
            if not self._warned:
                print("weaverun: Log queue full, dropping entry", file=sys.stderr)

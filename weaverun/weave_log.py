import os
import sys


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


class WeaveLogger:
    """Handles Weave initialization and logging. Best-effort, never crashes."""
    
    def __init__(self):
        self._initialized = False
        self._failed = False
        self._warned = False
    
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
    
    def log(
        self,
        *,
        path: str,
        upstream: str,
        request_json,
        response_json,
        status_code: int,
        latency_ms: float,
        model: str | None,
    ) -> str | None:
        """Log API call to Weave. Returns trace URL on success, None on failure."""
        try:
            if not self._ensure_init():
                return None
            
            import weave
            call = weave.log_call(
                op=f"openai{path}",
                inputs={"path": path, "model": model, "request": request_json},
                output={"status_code": status_code, "response": response_json},
                attributes={
                    "upstream": upstream,
                    "latency_ms": latency_ms,
                    "run_id": os.getenv("WEAVE_RUN_ID"),
                    "app": os.getenv("WEAVE_APP_NAME"),
                },
                use_stack=False,
            )
            return getattr(call, 'ui_url', None)
        except Exception as e:
            if not self._warned:
                print(f"weaverun: Weave logging failed: {e}", file=sys.stderr)
                self._warned = True
            return None

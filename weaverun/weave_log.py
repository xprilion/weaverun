import os
import sys


class WeaveLogger:
    """Handles Weave initialization and logging. Best-effort, never crashes."""
    
    def __init__(self):
        self._initialized = False
        self._failed = False
    
    def _ensure_init(self) -> bool:
        """Lazy init Weave with user's project ID."""
        if self._initialized or self._failed:
            return self._initialized
        
        project_id = os.getenv("WANDB_PROJECT_ID")
        if not project_id:
            print("weaverun: WANDB_PROJECT_ID not set, logging disabled", file=sys.stderr)
            self._failed = True
            return False
        
        try:
            import weave
            weave.init(project_id)
            self._initialized = True
            return True
        except Exception as e:
            print(f"weaverun: Weave init failed: {e}", file=sys.stderr)
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
    ):
        """Log API call to Weave. Never raises."""
        try:
            if not self._ensure_init():
                return
            
            import weave
            weave.log_call(
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
        except Exception as e:
            print(f"weaverun: Log failed: {e}", file=sys.stderr)

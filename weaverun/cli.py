import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import typer
import uvicorn
from dotenv import load_dotenv

app = typer.Typer(add_completion=False)


def _log(msg: str, err: bool = False):
    """Print weaverun status message."""
    stream = sys.stderr if err else sys.stdout
    print(f"\033[36mweaverun:\033[0m {msg}", file=stream)


def _load_dotenv() -> bool:
    """Load .env file from current directory if it exists. Returns True if OPENAI_BASE_URL was found."""
    env_path = Path.cwd() / ".env"
    has_base_url = False
    if env_path.exists():
        load_dotenv(env_path)
        _log(f"Loaded {env_path}")
        # Check if .env has OPENAI_BASE_URL which might conflict
        try:
            with open(env_path) as f:
                content = f.read()
                if "OPENAI_BASE_URL" in content:
                    has_base_url = True
        except Exception:
            pass
    return has_base_url


def _find_free_port(start: int = 7777, attempts: int = 100) -> int:
    """Find available port starting from `start`."""
    for offset in range(attempts):
        port = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No free port found (tried {start}-{start + attempts})")


def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Block until port accepts connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(("127.0.0.1", port))
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    return False


def _start_proxy(port: int):
    """Run uvicorn server."""
    config = uvicorn.Config(
        "weaverun.proxy:app",
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    uvicorn.Server(config).run()


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run(
    ctx: typer.Context,
    proxy_all: bool = typer.Option(
        False, "--proxy-all", "-p",
        help="Route ALL HTTP traffic through proxy (for apps with hardcoded base_url)"
    ),
):
    """Wrap a command and log OpenAI-compatible API calls to Weave."""
    cmd = ctx.args
    if not cmd:
        raise typer.BadParameter("No command provided")

    env_has_base_url = _load_dotenv()
    if env_has_base_url:
        _log("⚠️  Warning: .env contains OPENAI_BASE_URL which may override proxy settings")
        _log("   For Next.js/Node apps, consider removing it from .env temporarily")

    try:
        proxy_port = _find_free_port()
    except RuntimeError as e:
        _log(f"Error: {e}", err=True)
        raise typer.Exit(1)

    _log(f"Starting proxy on port {proxy_port}...")
    
    proxy_thread = threading.Thread(target=_start_proxy, args=(proxy_port,), daemon=True)
    proxy_thread.start()

    if not _wait_for_port(proxy_port, timeout=10.0):
        _log("Error: Proxy failed to start", err=True)
        raise typer.Exit(1)

    _log("Proxy ready")
    _log(f"Dashboard: http://127.0.0.1:{proxy_port}/__weaverun__")

    env = os.environ.copy()
    
    # Preserve original base URL for forwarding
    original_base = env.get("OPENAI_BASE_URL")
    if original_base:
        env["WEAVE_ORIGINAL_OPENAI_BASE_URL"] = original_base

    # Route SDK traffic through proxy
    env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{proxy_port}"
    env["WEAVE_RUN_ID"] = str(uuid.uuid4())
    env["WEAVE_APP_NAME"] = cmd[0]

    # For apps that hardcode base_url, use HTTP_PROXY to intercept
    if proxy_all:
        _log("Proxy mode: ALL HTTP traffic (--proxy-all)")
        env["HTTP_PROXY"] = f"http://127.0.0.1:{proxy_port}"
        env["HTTPS_PROXY"] = f"http://127.0.0.1:{proxy_port}"
        # Only exclude the proxy itself from proxying
        env["NO_PROXY"] = f"127.0.0.1:{proxy_port}"

    _log(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, env=env)
        exit_code = result.returncode
    except KeyboardInterrupt:
        exit_code = 130
    except Exception as e:
        _log(f"Error: {e}", err=True)
        exit_code = 1

    _log(f"Done (exit code: {exit_code})")
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()

import os
from urllib.parse import urlparse

# Default when no OPENAI_BASE_URL set (includes /v1 since SDK omits it)
DEFAULT_UPSTREAM = "https://api.openai.com/v1"


def resolve_upstream(path: str) -> str:
    """
    Resolve upstream URL for the request.
    
    Handles two cases:
    1. Relative path (e.g., "chat/completions") - use env vars to resolve base
    2. Absolute URL (e.g., "http://localhost:11434/v1/chat/completions") - use as-is
    """
    # Check if path is already an absolute URL (from HTTP_PROXY mode)
    if path.startswith("http://") or path.startswith("https://"):
        return path
    
    # User's original OPENAI_BASE_URL (preserved by CLI)
    original = os.getenv("WEAVE_ORIGINAL_OPENAI_BASE_URL")
    if original:
        return f"{original.rstrip('/')}/{path}"
    
    # Explicit override
    fallback = os.getenv("WEAVE_UPSTREAM_BASE")
    if fallback:
        return f"{fallback.rstrip('/')}/{path}"
    
    return f"{DEFAULT_UPSTREAM}/{path}"


def extract_path(url_or_path: str) -> str:
    """Extract just the path from a URL or return path as-is."""
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        parsed = urlparse(url_or_path)
        return parsed.path
    return url_or_path if url_or_path.startswith("/") else f"/{url_or_path}"

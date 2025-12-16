import os

# Default when no OPENAI_BASE_URL set (includes /v1 since SDK omits it)
DEFAULT_UPSTREAM = "https://api.openai.com/v1"


def resolve_upstream(path: str) -> str:
    """
    Resolve upstream URL for the request.
    
    Priority: preserved OPENAI_BASE_URL > WEAVE_UPSTREAM_BASE > default OpenAI
    """
    # User's original OPENAI_BASE_URL (preserved by CLI)
    original = os.getenv("WEAVE_ORIGINAL_OPENAI_BASE_URL")
    if original:
        return f"{original.rstrip('/')}/{path}"
    
    # Explicit override
    fallback = os.getenv("WEAVE_UPSTREAM_BASE")
    if fallback:
        return f"{fallback.rstrip('/')}/{path}"
    
    return f"{DEFAULT_UPSTREAM}/{path}"

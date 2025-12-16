# OpenAI-compatible API path suffixes
OPENAI_SUFFIXES = frozenset([
    "/chat/completions",
    "/completions",
    "/responses",
    "/embeddings",
    "/audio/transcriptions",
    "/audio/translations",
    "/audio/speech",
    "/images/generations",
    "/images/edits",
    "/images/variations",
    "/moderations",
])


def is_openai_compatible(path: str) -> bool:
    """Check if path is a known OpenAI-compatible endpoint."""
    if not path:
        return False
    
    normalized = path if path.startswith("/") else f"/{path}"
    
    # Strip /v1 prefix if present (e.g., /v1/chat/completions -> /chat/completions)
    if normalized.startswith("/v1"):
        normalized = normalized[3:]  # Remove /v1
    
    # Check exact match
    if normalized in OPENAI_SUFFIXES:
        return True
    
    # Handle query params (e.g., /chat/completions?stream=true)
    return any(normalized.startswith(f"{p}?") for p in OPENAI_SUFFIXES)

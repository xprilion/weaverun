# OpenAI-compatible API paths (SDK sends these without /v1 prefix)
OPENAI_PATHS = frozenset([
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
    
    if normalized in OPENAI_PATHS:
        return True
    
    # Handle query params and sub-paths
    return any(
        normalized.startswith(f"{p}?") or normalized.startswith(f"{p}/")
        for p in OPENAI_PATHS
    )

"""
API endpoint detection for multiple LLM providers.

Supports: OpenAI, Anthropic, Gemini, AWS Bedrock, Azure OpenAI, W&B Inference,
Cohere, Mistral, Groq, Together, Replicate, Fireworks, Perplexity, Ollama.

Custom patterns can be added via weaverun.config.yaml
"""
from urllib.parse import urlparse

from .config import get_config


def is_capturable_endpoint(path: str, url: str = "") -> tuple[bool, str | None]:
    """
    Check if the request should be captured for logging.
    
    Args:
        path: The API path (e.g., /v1/chat/completions)
        url: The full upstream URL (used for host matching)
    
    Returns:
        Tuple of (should_capture, provider_name)
    """
    host = ""
    if url:
        try:
            parsed = urlparse(url)
            host = parsed.netloc or parsed.hostname or ""
        except Exception:
            pass
    
    config = get_config()
    return config.is_capturable(path, host)


def is_openai_compatible(path: str) -> bool:
    """
    Legacy function for backwards compatibility.
    Check if path is a known capturable endpoint.
    """
    should_capture, _ = is_capturable_endpoint(path)
    return should_capture


def get_provider_name(path: str, url: str = "") -> str | None:
    """Get the provider name for a request, or None if not capturable."""
    _, provider = is_capturable_endpoint(path, url)
    return provider

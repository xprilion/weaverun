"""
Configuration loader for weaverun.

Supports loading custom provider patterns from weaverun.config.yaml
"""
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class ProviderPattern:
    """A pattern for matching API endpoints."""
    name: str
    # Path patterns (regex or suffix strings)
    path_patterns: list[str] = field(default_factory=list)
    # Host patterns (regex for matching upstream hosts)
    host_patterns: list[str] = field(default_factory=list)
    # Whether patterns are regex (True) or simple suffix match (False)
    is_regex: bool = False
    
    def matches_path(self, path: str) -> bool:
        """Check if path matches any of this provider's patterns."""
        if not path:
            return False
        normalized = path if path.startswith("/") else f"/{path}"
        
        for pattern in self.path_patterns:
            if self.is_regex:
                if re.search(pattern, normalized):
                    return True
            else:
                # Suffix match
                if normalized.endswith(pattern) or normalized.split("?")[0].endswith(pattern):
                    return True
        return False
    
    def matches_host(self, host: str) -> bool:
        """Check if host matches any of this provider's host patterns."""
        if not host or not self.host_patterns:
            return True  # No host restriction
        for pattern in self.host_patterns:
            if re.search(pattern, host, re.IGNORECASE):
                return True
        return False


# Built-in provider definitions
BUILTIN_PROVIDERS: list[ProviderPattern] = [
    # OpenAI
    ProviderPattern(
        name="openai",
        path_patterns=[
            # Chat & Completions
            r"/v1/chat/completions",
            r"/v1/completions",
            r"/v1/responses",
            r"/v1/embeddings",
            # Assistants API
            r"/v1/assistants",
            r"/v1/threads",
            r"/v1/threads/.+/messages",
            r"/v1/threads/.+/runs",
            # Audio
            r"/v1/audio/transcriptions",
            r"/v1/audio/translations",
            r"/v1/audio/speech",
            # Images
            r"/v1/images/generations",
            r"/v1/images/edits",
            r"/v1/images/variations",
            # Other
            r"/v1/moderations",
            r"/v1/files",
            r"/v1/batches",
            # Without /v1 prefix (some compatible APIs)
            r"/chat/completions$",
            r"/completions$",
            r"/embeddings$",
        ],
        host_patterns=[
            r"api\.openai\.com",
            r"localhost",
            r"127\.0\.0\.1",
            r".*",  # OpenAI-compatible endpoints can be anywhere
        ],
        is_regex=True,
    ),
    
    # Anthropic
    ProviderPattern(
        name="anthropic",
        path_patterns=[
            r"/v1/messages",
            r"/v1/complete",
        ],
        host_patterns=[
            r"api\.anthropic\.com",
        ],
        is_regex=True,
    ),
    
    # Google Gemini / Vertex AI
    ProviderPattern(
        name="gemini",
        path_patterns=[
            r"/v1beta/models/.+:generateContent",
            r"/v1beta/models/.+:streamGenerateContent",
            r"/v1beta/models/.+:countTokens",
            r"/v1beta/models/.+:embedContent",
            r"/v1/models/.+:generateContent",
            r"/v1/models/.+:streamGenerateContent",
            # Vertex AI patterns
            r"/v1/projects/.+/locations/.+/publishers/.+/models/.+:predict",
            r"/v1/projects/.+/locations/.+/publishers/.+/models/.+:streamPredict",
            r"/v1/projects/.+/locations/.+/publishers/.+/models/.+:generateContent",
        ],
        host_patterns=[
            r"generativelanguage\.googleapis\.com",
            r".*-aiplatform\.googleapis\.com",
        ],
        is_regex=True,
    ),
    
    # AWS Bedrock
    ProviderPattern(
        name="bedrock",
        path_patterns=[
            r"/model/.+/invoke",
            r"/model/.+/invoke-with-response-stream",
            r"/model/.+/converse",
            r"/model/.+/converse-stream",
        ],
        host_patterns=[
            r"bedrock-runtime\..*\.amazonaws\.com",
            r"bedrock\..*\.amazonaws\.com",
        ],
        is_regex=True,
    ),
    
    # Azure OpenAI
    ProviderPattern(
        name="azure_openai",
        path_patterns=[
            r"/openai/deployments/.+/chat/completions",
            r"/openai/deployments/.+/completions",
            r"/openai/deployments/.+/embeddings",
            r"/openai/deployments/.+/images/generations",
            r"/openai/deployments/.+/audio/transcriptions",
            r"/openai/deployments/.+/audio/translations",
        ],
        host_patterns=[
            r".*\.openai\.azure\.com",
            r".*\.azure-api\.net",
        ],
        is_regex=True,
    ),
    
    # W&B Inference (Weave)
    ProviderPattern(
        name="wandb_inference",
        path_patterns=[
            r"/v1/chat/completions",
            r"/v1/completions",
            r"/v1/embeddings",
        ],
        host_patterns=[
            r".*\.wandb\.ai",
            r"api\.wandb\.ai",
        ],
        is_regex=True,
    ),
    
    # Cohere
    ProviderPattern(
        name="cohere",
        path_patterns=[
            r"/v1/chat",
            r"/v1/generate",
            r"/v1/embed",
            r"/v1/rerank",
            r"/v1/summarize",
        ],
        host_patterns=[
            r"api\.cohere\.ai",
            r"api\.cohere\.com",
        ],
        is_regex=True,
    ),
    
    # Mistral AI
    ProviderPattern(
        name="mistral",
        path_patterns=[
            r"/v1/chat/completions",
            r"/v1/embeddings",
            r"/v1/fim/completions",
        ],
        host_patterns=[
            r"api\.mistral\.ai",
        ],
        is_regex=True,
    ),
    
    # Groq
    ProviderPattern(
        name="groq",
        path_patterns=[
            r"/openai/v1/chat/completions",
            r"/v1/chat/completions",
        ],
        host_patterns=[
            r"api\.groq\.com",
        ],
        is_regex=True,
    ),
    
    # Together AI
    ProviderPattern(
        name="together",
        path_patterns=[
            r"/v1/chat/completions",
            r"/v1/completions",
            r"/v1/embeddings",
            r"/inference",
        ],
        host_patterns=[
            r"api\.together\.xyz",
            r".*\.together\.ai",
        ],
        is_regex=True,
    ),
    
    # Replicate
    ProviderPattern(
        name="replicate",
        path_patterns=[
            r"/v1/predictions",
            r"/v1/models/.+/predictions",
        ],
        host_patterns=[
            r"api\.replicate\.com",
        ],
        is_regex=True,
    ),
    
    # Fireworks AI
    ProviderPattern(
        name="fireworks",
        path_patterns=[
            r"/inference/v1/chat/completions",
            r"/inference/v1/completions",
            r"/inference/v1/embeddings",
        ],
        host_patterns=[
            r"api\.fireworks\.ai",
        ],
        is_regex=True,
    ),
    
    # Perplexity
    ProviderPattern(
        name="perplexity",
        path_patterns=[
            r"/chat/completions",
        ],
        host_patterns=[
            r"api\.perplexity\.ai",
        ],
        is_regex=True,
    ),
    
    # Ollama (local)
    ProviderPattern(
        name="ollama",
        path_patterns=[
            r"/api/generate",
            r"/api/chat",
            r"/api/embeddings",
            r"/v1/chat/completions",  # OpenAI compatible endpoint
        ],
        host_patterns=[
            r"localhost",
            r"127\.0\.0\.1",
            r".*:11434",
        ],
        is_regex=True,
    ),
    
    # Google ADK (Agent Development Kit)
    ProviderPattern(
        name="google_adk",
        path_patterns=[
            r"/run$",
            r"/run_sse$",
            r"/api/run$",
            r"/api/run_sse$",
        ],
        host_patterns=[
            r"localhost",
            r"127\.0\.0\.1",
        ],
        is_regex=True,
    ),
]


@dataclass
class Config:
    """WeaveRun configuration."""
    providers: list[ProviderPattern] = field(default_factory=list)
    capture_all_requests: bool = False
    config_path: str | None = None
    debug: bool = False  # When True, observe traffic without logging to Weave
    
    def is_capturable(self, path: str, host: str = "") -> tuple[bool, str | None]:
        """
        Check if a request should be captured.
        Returns (should_capture, provider_name).
        """
        if self.capture_all_requests:
            return True, "custom"
        
        for provider in self.providers:
            if provider.matches_path(path) and provider.matches_host(host):
                return True, provider.name
        
        return False, None


def _load_yaml_config(path: Path) -> dict:
    """Load YAML config file."""
    try:
        import yaml
    except ImportError:
        print("weaverun: PyYAML not installed, custom config not loaded", file=sys.stderr)
        return {}
    
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"weaverun: Failed to load config from {path}: {e}", file=sys.stderr)
        return {}


def _parse_custom_providers(config_data: dict) -> list[ProviderPattern]:
    """Parse custom provider definitions from config."""
    providers = []
    custom = config_data.get("providers", [])
    
    for p in custom:
        if not isinstance(p, dict):
            continue
        
        name = p.get("name", "custom")
        path_patterns = p.get("path_patterns", [])
        host_patterns = p.get("host_patterns", [])
        is_regex = p.get("is_regex", True)
        
        if path_patterns:
            providers.append(ProviderPattern(
                name=name,
                path_patterns=path_patterns if isinstance(path_patterns, list) else [path_patterns],
                host_patterns=host_patterns if isinstance(host_patterns, list) else [host_patterns] if host_patterns else [],
                is_regex=is_regex,
            ))
    
    return providers


def load_config() -> Config:
    """
    Load configuration from weaverun.config.yaml.
    
    Search order:
    1. WEAVERUN_CONFIG env var
    2. ./weaverun.config.yaml (current directory)
    3. ~/.weaverun.config.yaml (home directory)
    """
    config = Config(providers=list(BUILTIN_PROVIDERS))
    
    # Determine config file path
    config_path = None
    
    env_path = os.getenv("WEAVERUN_CONFIG")
    if env_path and Path(env_path).exists():
        config_path = Path(env_path)
    elif Path("weaverun.config.yaml").exists():
        config_path = Path("weaverun.config.yaml")
    elif Path.home().joinpath(".weaverun.config.yaml").exists():
        config_path = Path.home().joinpath(".weaverun.config.yaml")
    
    if config_path:
        print(f"weaverun: Loading config from {config_path}", file=sys.stderr)
        config_data = _load_yaml_config(config_path)
        
        # Add custom providers (prepend so they take priority)
        custom_providers = _parse_custom_providers(config_data)
        config.providers = custom_providers + config.providers
        
        # Check for capture_all setting
        config.capture_all_requests = config_data.get("capture_all_requests", False)
        
        # Check for debug mode
        config.debug = config_data.get("debug", False)
        
        # Check for disabled built-in providers
        disabled = config_data.get("disable_providers", [])
        if disabled:
            config.providers = [p for p in config.providers if p.name not in disabled]
        
        config.config_path = str(config_path)
    else:
        config.config_path = None
    
    # Environment variable override for debug mode
    if os.getenv("WEAVERUN_DEBUG", "").lower() in ("1", "true", "yes"):
        config.debug = True
    
    return config


# Global config instance (lazy loaded)
_config: Config | None = None


def get_config() -> Config:
    """Get or load the global config."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config():
    """Force reload of configuration."""
    global _config
    _config = load_config()


def set_debug_mode(enabled: bool):
    """Enable or disable debug mode."""
    cfg = get_config()
    cfg.debug = enabled


def is_debug_mode() -> bool:
    """Check if debug mode is enabled."""
    return get_config().debug


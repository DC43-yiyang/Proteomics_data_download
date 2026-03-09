"""LLM client factory for creating appropriate client based on provider."""

from __future__ import annotations

from typing import Any

from geo_agent.config import Config
from geo_agent.llm.ollama_client import OllamaClient
from geo_agent.llm.openai_compatible_client import OpenAICompatibleClient

# Provider-specific default configurations
_PROVIDER_DEFAULTS = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "qwen3:30b-a3b",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "model": "abab6.5-chat",
    },
    "openai": {
        "base_url": "https://api.openai.com",
        "model": "gpt-4o-mini",
    },
}


def create_llm_client(
    config: Config | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 600,
    strip_think_tags: bool = True,
) -> Any:
    """Create an LLM client based on provider configuration.

    Args:
        config: Config object (if provided, overrides other params)
        provider: Provider name (ollama, deepseek, qwen, kimi, minimax, openai)
        api_key: API key (required for non-ollama providers)
        base_url: Base URL (optional, uses provider default if not specified)
        timeout: Request timeout in seconds
        strip_think_tags: Remove <think>...</think> blocks from response

    Returns:
        OllamaClient or OpenAICompatibleClient instance

    Raises:
        ValueError: If provider is unsupported or required credentials are missing

    Examples:
        # From config
        >>> from geo_agent.config import load_config
        >>> config = load_config()
        >>> client = create_llm_client(config=config)

        # Direct instantiation
        >>> client = create_llm_client(
        ...     provider="deepseek",
        ...     api_key="sk-xxx",
        ... )
    """
    # Load from config if provided
    if config:
        provider = config.llm_provider
        api_key = config.llm_api_key
        base_url = config.llm_base_url

    # Validate provider
    if not provider:
        provider = "ollama"

    provider = provider.lower()
    if provider not in _PROVIDER_DEFAULTS:
        raise ValueError(
            f"Unsupported provider: {provider}. "
            f"Supported: {', '.join(_PROVIDER_DEFAULTS.keys())}"
        )

    # Use provider default base_url if not specified
    if not base_url:
        base_url = _PROVIDER_DEFAULTS[provider]["base_url"]

    # Ollama uses local client (no API key required)
    if provider == "ollama":
        return OllamaClient(
            base_url=base_url,
            timeout=timeout,
            strip_think_tags=strip_think_tags,
        )

    # All other providers require API key
    if not api_key:
        raise ValueError(
            f"API key required for provider '{provider}'. "
            f"Set LLM_API_KEY in .env or pass api_key parameter."
        )

    return OpenAICompatibleClient(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        strip_think_tags=strip_think_tags,
    )


def get_default_model(provider: str) -> str:
    """Get the default model name for a provider.

    Args:
        provider: Provider name

    Returns:
        Default model name for the provider

    Raises:
        ValueError: If provider is unsupported
    """
    provider = provider.lower()
    if provider not in _PROVIDER_DEFAULTS:
        raise ValueError(
            f"Unsupported provider: {provider}. "
            f"Supported: {', '.join(_PROVIDER_DEFAULTS.keys())}"
        )
    return _PROVIDER_DEFAULTS[provider]["model"]

"""OpenAI-compatible LLM client for Chinese commercial APIs.

Supports: MiniMax, Kimi (Moonshot), Qwen (Alibaba), DeepSeek, and any OpenAI-compatible endpoint.

Usage::

    client = OpenAICompatibleClient(
        api_key="your-api-key",
        base_url="https://api.deepseek.com",
    )
    resp = client.messages.create(
        model="deepseek-chat",
        system="You are a bioinformatics curator.",
        messages=[{"role": "user", "content": "Hello"}],
        temperature=0.1,
    )
    text = resp.choices[0].message.content
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import requests

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class _Message:
    role: str
    content: str


@dataclass
class _Choice:
    message: _Message
    finish_reason: str = "stop"


@dataclass
class _Response:
    """Minimal response wrapper mirroring the shape callers expect."""

    choices: list[_Choice] = field(default_factory=list)
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class _MessagesNamespace:
    """Provides .messages.create() so callers can use a unified interface."""

    def __init__(self, client: "OpenAICompatibleClient") -> None:
        self._client = client

    def create(
        self,
        model: str,
        messages: list[dict[str, str]],
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> _Response:
        return self._client._chat(
            model=model,
            messages=messages,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


class OpenAICompatibleClient:
    """OpenAI-compatible client for Chinese commercial LLM APIs.

    Supported providers:
    - DeepSeek: https://api.deepseek.com
    - Qwen (Alibaba): https://dashscope.aliyuncs.com/compatible-mode/v1
    - Kimi (Moonshot): https://api.moonshot.cn/v1
    - MiniMax: https://api.minimax.chat/v1
    - Any OpenAI-compatible endpoint

    Usage::

        client = OpenAICompatibleClient(
            api_key="your-api-key",
            base_url="https://api.deepseek.com",
        )
        resp = client.messages.create(
            model="deepseek-chat",
            system="You are a bioinformatics curator.",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.1,
        )
        text = resp.choices[0].message.content
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 600,
        strip_think_tags: bool = True,
    ) -> None:
        """Initialize OpenAI-compatible client.

        Args:
            api_key: API key for the provider
            base_url: Base URL (e.g., "https://api.deepseek.com")
            timeout: Request timeout in seconds
            strip_think_tags: Remove <think>...</think> blocks from response
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._strip_think_tags = strip_think_tags
        self.messages = _MessagesNamespace(self)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        system: str | None,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        seed: int | None = None,
        think: bool | None = None,
        **extra_payload: Any,
    ) -> _Response:
        # Prepend system message when provided (Anthropic-style calling convention)
        full_messages: list[dict[str, str]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if seed is not None:
            payload["seed"] = seed

        # Some providers support 'think' parameter (e.g., DeepSeek R1)
        if think is not None:
            payload["think"] = think

        payload.update(extra_payload)

        # Build URL - avoid duplicating /v1 if already in base_url
        if self._base_url.endswith("/v1"):
            url = f"{self._base_url}/chat/completions"
        else:
            url = f"{self._base_url}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            http_resp = requests.post(url, json=payload, headers=headers, timeout=self._timeout)
            http_resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"OpenAI-compatible API request failed: {exc}") from exc

        raw = http_resp.json()
        content = raw["choices"][0]["message"]["content"]
        if self._strip_think_tags:
            content = _THINK_PATTERN.sub("", content).strip()
        finish_reason = raw["choices"][0].get("finish_reason", "stop")

        return _Response(
            choices=[_Choice(message=_Message(role="assistant", content=content), finish_reason=finish_reason)],
            model=raw.get("model", model),
            raw=raw,
        )

    def health_check(self) -> bool:
        """Return True if the API endpoint is reachable.

        Note: This is a basic connectivity check. Some providers may not support
        a dedicated health endpoint.
        """
        try:
            # Try a minimal request to check connectivity
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            # Build URL - avoid duplicating /v1
            if self._base_url.endswith("/v1"):
                url = f"{self._base_url}/models"
            else:
                url = f"{self._base_url}/v1/models"
            resp = requests.get(url, headers=headers, timeout=5)
            return resp.status_code in (200, 404)  # 404 is ok, means endpoint exists
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        """Return available models (if supported by the provider).

        Note: Not all providers support model listing. Returns empty list if unsupported.
        """
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            # Build URL - avoid duplicating /v1
            if self._base_url.endswith("/v1"):
                url = f"{self._base_url}/models"
            else:
                url = f"{self._base_url}/v1/models"
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if "data" in data:
                return [m["id"] for m in data["data"]]
            return []
        except requests.RequestException:
            return []

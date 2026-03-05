"""Ollama local LLM client.

Communicates with a running Ollama instance via its OpenAI-compatible
/v1/chat/completions endpoint.  The returned response object is a simple
dataclass so callers do not need the openai package installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import requests

_DEFAULT_BASE_URL = "http://localhost:11434"
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

    def __init__(self, client: "OllamaClient") -> None:
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


class OllamaClient:
    """Thin wrapper around the Ollama OpenAI-compatible chat completions API.

    Usage::

        client = OllamaClient()
        resp = client.messages.create(
            model="qwen3:30b-a3b",
            system="You are a bioinformatics curator.",
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.1,
        )
        text = resp.choices[0].message.content
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = 600,
        strip_think_tags: bool = True,
    ) -> None:
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
        if think is not None:
            payload["think"] = think
        payload.update(extra_payload)

        url = f"{self._base_url}/v1/chat/completions"
        try:
            http_resp = requests.post(url, json=payload, timeout=self._timeout)
            http_resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

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
        """Return True if Ollama is reachable."""
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        """Return names of locally available models."""
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except requests.RequestException:
            return []

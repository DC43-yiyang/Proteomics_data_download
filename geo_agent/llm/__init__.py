"""LLM backend adapters for geo_agent."""

from geo_agent.llm.factory import create_llm_client, get_default_model
from geo_agent.llm.ollama_client import OllamaClient
from geo_agent.llm.openai_compatible_client import OpenAICompatibleClient

__all__ = ["OllamaClient", "OpenAICompatibleClient", "create_llm_client", "get_default_model"]

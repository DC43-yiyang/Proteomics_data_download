import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration, loaded from environment / .env file."""

    api_key: Optional[str] = None
    email: str = ""
    tool_name: str = "geo_agent"
    download_dir: Path = field(default_factory=lambda: Path("./geo_downloads"))

    # Database (optional -- None means no DB persistence)
    db_path: Optional[Path] = None

    # OpenAI-compatible LLM config (for multi-omics annotation)
    # Supported providers: ollama (local), deepseek, qwen, kimi, minimax, openai
    llm_provider: str = "ollama"  # ollama | deepseek | qwen | kimi | minimax | openai
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_annotation_model: str = "qwen3:30b-a3b"  # model name for annotation

    # Rate limiting (derived from api_key presence)
    @property
    def min_request_interval(self) -> float:
        return 0.1 if self.api_key else 0.34

    @property
    def max_requests_per_second(self) -> int:
        return 10 if self.api_key else 3


def load_config(env_file: Optional[str] = None) -> Config:
    """Load config from .env file and environment variables."""
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    db_raw = os.getenv("GEO_AGENT_DB", "")

    return Config(
        api_key=os.getenv("NCBI_API_KEY") or None,
        email=os.getenv("NCBI_EMAIL", ""),
        db_path=Path(db_raw) if db_raw else None,
        # OpenAI-compatible LLM config
        llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_annotation_model=os.getenv("LLM_ANNOTATION_MODEL", "qwen3:30b-a3b"),
    )

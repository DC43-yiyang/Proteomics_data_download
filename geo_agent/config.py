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

    return Config(
        api_key=os.getenv("NCBI_API_KEY") or None,
        email=os.getenv("NCBI_EMAIL", ""),
    )

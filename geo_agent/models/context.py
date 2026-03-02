from dataclasses import dataclass, field

from geo_agent.models.dataset import GEODataset
from geo_agent.models.query import SearchQuery


@dataclass
class PipelineContext:
    """Typed context passed through the skill pipeline.

    Each skill reads and writes to specific fields. Using a dataclass instead
    of a raw dict provides IDE autocompletion and catches typos at dev time.
    """

    # Input: always set before pipeline starts
    query: SearchQuery

    # GEOSearchSkill outputs
    datasets: list[GEODataset] = field(default_factory=list)
    total_found: int = 0

    # ReportSkill outputs
    report: str = ""
    report_data: list[dict] = field(default_factory=list)

    # FilterSkill outputs (Phase 3)
    filtered_datasets: list[GEODataset] = field(default_factory=list)

    # ValidationSkill outputs (Phase 3)
    validated_datasets: list[GEODataset] = field(default_factory=list)

    # Download config (Phase 4)
    download_dir: str = "./geo_downloads"
    downloaded_files: list[str] = field(default_factory=list)

    # Error tracking
    errors: list[str] = field(default_factory=list)

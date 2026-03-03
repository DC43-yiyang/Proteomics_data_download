from dataclasses import dataclass, field
from typing import Any

from geo_agent.models.dataset import GEODataset
from geo_agent.models.query import SearchQuery
from geo_agent.models.sample import GEOSample, SampleSelection


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

    # HierarchySkill outputs
    series_hierarchy: dict[str, Any] = field(default_factory=dict)  # accession -> SeriesNode

    # ValidationSkill outputs (Phase 3)
    validated_datasets: list[GEODataset] = field(default_factory=list)

    # SampleSelectorSkill inputs/outputs
    target_library_types: list[str] = field(default_factory=lambda: ["GEX"])
    sample_metadata: dict[str, list[GEOSample]] = field(default_factory=dict)
    selected_samples: dict[str, list[SampleSelection]] = field(default_factory=dict)

    # Download config (Phase 4)
    download_dir: str = "./geo_downloads"
    downloaded_files: list[str] = field(default_factory=list)

    # Error tracking
    errors: list[str] = field(default_factory=list)

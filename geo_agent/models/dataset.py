from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SupplementaryFile:
    """A supplementary file associated with a GEO dataset."""

    name: str
    url: str
    size_bytes: Optional[int] = None


@dataclass
class GEODataset:
    """Represents a single GEO Series (GSE) entry with its metadata."""

    accession: str  # e.g. "GSE164378"
    uid: str  # NCBI internal UID
    title: str = ""
    summary: str = ""
    organism: str = ""
    platform: str = ""  # e.g. "GPL24676"
    series_type: str = ""  # e.g. "Expression profiling by high throughput sequencing"
    sample_count: int = 0
    overall_design: str = ""  # Experiment design details (often contains key protocol info)
    ftp_link: str = ""
    supplementary_files: list[SupplementaryFile] = field(default_factory=list)

    # Populated during filtering
    relevance_score: float = 0.0

    # Populated during validation
    is_valid: bool = False
    validation_notes: str = ""

    @property
    def geo_url(self) -> str:
        return f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={self.accession}"

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GEOSample:
    """Metadata for a single GSM sample within a GSE series."""

    accession: str  # e.g. "GSM9474997"
    title: str = ""
    organism: str = ""
    molecule: str = ""  # e.g. "polyA RNA", "protein", "genomic DNA"
    characteristics: dict[str, str] = field(default_factory=dict)
    library_source: str = ""  # e.g. "transcriptomic", "other"
    supplementary_files: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class SampleSelection:
    """Result of LLM classification for a single sample."""

    accession: str  # GSM accession
    library_type: str  # GEX, ADT, TCR, BCR, HTO, ATAC, OTHER
    confidence: float = 0.0  # 0.0 ~ 1.0
    reasoning: str = ""
    needs_review: bool = False
    supplementary_files: list[str] = field(default_factory=list)

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchQuery:
    """Structured representation of a GEO search request.

    Supports multi-dimensional filtering by data type, organism, disease, and tissue.
    """

    data_type: str  # e.g. "CITE-seq", "scRNA-seq", "WGS", "WES"
    organism: Optional[str] = None  # e.g. "Homo sapiens"
    disease: Optional[str] = None  # e.g. "breast cancer"
    tissue: Optional[str] = None  # e.g. "PBMC", "T cells"
    file_types: list[str] = field(
        default_factory=lambda: [".h5", ".mtx.gz", ".csv.gz"]
    )
    max_results: int = 100

    def to_geo_query(self) -> str:
        """Build an NCBI GEO search query string.

        Uses [All Fields] for data_type/disease/tissue to match GEO website behavior.
        Uses [Organism] for organism for exact species matching.

        Example output:
            CITE-seq AND "Homo sapiens"[Organism] AND gse[EntryType]
        """
        parts = [self.data_type]

        if self.organism:
            parts.append(f'"{self.organism}"[Organism]')
        if self.disease:
            parts.append(self.disease)
        if self.tissue:
            parts.append(self.tissue)

        # Restrict to GEO Series entries
        parts.append("gse[EntryType]")

        return " AND ".join(parts)

    def summary(self) -> str:
        """Human-readable summary of the query."""
        parts = [f"Data type: {self.data_type}"]
        if self.organism:
            parts.append(f"Organism: {self.organism}")
        if self.disease:
            parts.append(f"Disease: {self.disease}")
        if self.tissue:
            parts.append(f"Tissue: {self.tissue}")
        parts.append(f"Max results: {self.max_results}")
        return " | ".join(parts)

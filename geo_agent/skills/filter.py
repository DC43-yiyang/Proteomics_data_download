import logging
import re

from geo_agent.models.context import PipelineContext
from geo_agent.models.dataset import GEODataset
from geo_agent.skills.base import Skill

logger = logging.getLogger(__name__)


class FilterSkill(Skill):
    """Filter and score datasets by relevance.

    Designed to be called by AI Agents (e.g. Claude Code) or within the
    pipeline. Applies keyword matching, sample count filtering, and
    relevance scoring to produce a ranked list of datasets.

    Reads:
        context.datasets — list[GEODataset]
        context.query — SearchQuery (for keyword-based scoring)

    Writes:
        context.filtered_datasets — list[GEODataset] sorted by relevance_score desc
    """

    def __init__(
        self,
        min_samples: int = 0,
        required_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        min_score: float = 0.0,
    ):
        self._min_samples = min_samples
        self._required_keywords = [k.lower() for k in (required_keywords or [])]
        self._exclude_keywords = [k.lower() for k in (exclude_keywords or [])]
        self._min_score = min_score

    @property
    def name(self) -> str:
        return "filter"

    def execute(self, context: PipelineContext) -> PipelineContext:
        datasets = context.datasets
        query = context.query

        if not datasets:
            logger.warning("No datasets to filter")
            context.filtered_datasets = []
            return context

        logger.info(f"Filtering {len(datasets)} datasets")

        results = []
        for ds in datasets:
            # Step 1: Exclusion checks
            if ds.sample_count < self._min_samples:
                continue

            text = f"{ds.title} {ds.summary} {ds.overall_design}".lower()

            if self._exclude_keywords and any(kw in text for kw in self._exclude_keywords):
                continue

            if self._required_keywords and not any(kw in text for kw in self._required_keywords):
                continue

            # Step 2: Relevance scoring
            ds.relevance_score = self._score(ds, query)

            if ds.relevance_score >= self._min_score:
                results.append(ds)

        # Sort by relevance descending
        results.sort(key=lambda d: d.relevance_score, reverse=True)

        context.filtered_datasets = results
        logger.info(
            f"Filtered: {len(results)}/{len(datasets)} datasets passed "
            f"(min_samples={self._min_samples}, min_score={self._min_score})"
        )

        if results:
            top = results[0]
            logger.info(f"Top hit: {top.accession} (score={top.relevance_score:.2f}) — {top.title[:60]}")

        return context

    def _score(self, ds: GEODataset, query) -> float:
        """Score a dataset's relevance to the query (0.0 ~ 1.0)."""
        score = 0.0
        title_lower = ds.title.lower()
        summary_lower = ds.summary.lower()
        design_lower = ds.overall_design.lower()

        # 1. Data type match (title > overall_design > summary)
        dt = query.data_type.lower()
        if dt in title_lower:
            score += 0.30
        elif dt in design_lower:
            score += 0.25
        elif dt in summary_lower:
            score += 0.15

        # 2. Organism exact match
        if query.organism and ds.organism:
            if query.organism.lower() == ds.organism.lower():
                score += 0.20

        # 3. Disease match
        if query.disease:
            disease_lower = query.disease.lower()
            if disease_lower in title_lower:
                score += 0.20
            elif disease_lower in design_lower or disease_lower in summary_lower:
                score += 0.10

        # 4. Tissue match
        if query.tissue:
            tissue_lower = query.tissue.lower()
            if tissue_lower in title_lower:
                score += 0.15
            elif tissue_lower in design_lower or tissue_lower in summary_lower:
                score += 0.08

        # 5. Sample count bonus (more samples = more useful)
        if ds.sample_count >= 50:
            score += 0.10
        elif ds.sample_count >= 20:
            score += 0.05

        # 6. Has supplementary files
        if ds.supplementary_files:
            score += 0.05

        return min(score, 1.0)

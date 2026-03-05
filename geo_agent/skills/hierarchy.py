import json
import logging

from geo_agent.models.context import PipelineContext
from geo_agent.ncbi.client import NCBIClient
from geo_agent.ncbi.parsers import parse_soft_text
from geo_agent.skills.base import Skill
from geo_agent.utils.hierarchy import (
    build_series_hierarchy,
    serialize_families_json,
    serialize_standalone_json,
)

logger = logging.getLogger(__name__)


class HierarchySkill(Skill):
    """Build GEO series hierarchy (SuperSeries / SubSeries) from parsed relations.

    Reads:
        context.datasets — list[GEODataset] with relations populated by SearchSkill

    Writes:
        context.series_hierarchy — dict[str, SeriesNode]
    """

    def __init__(
        self,
        ncbi_client: NCBIClient | None = None,
        families_file: str | None = None,
        standalone_file: str | None = None,
    ):
        self._ncbi_client = ncbi_client
        self._families_file = families_file
        self._standalone_file = standalone_file

    @property
    def name(self) -> str:
        return "hierarchy"

    def _fill_external_titles(self, hierarchy: dict) -> None:
        """Fetch titles for external references (not in search results) via Series SOFT."""
        external = [
            acc for acc, node in hierarchy.items()
            if not node.in_search_results and not node.title
        ]
        if not external or not self._ncbi_client:
            return

        logger.info(f"Fetching titles for {len(external)} external references...")
        soft_data = self._ncbi_client.fetch_geo_soft_batch(external)

        filled = 0
        for acc, soft_text in soft_data.items():
            if soft_text:
                parsed = parse_soft_text(soft_text)
                title = parsed.get("title", "")
                if title:
                    hierarchy[acc].title = title
                    filled += 1

        logger.info(f"Filled {filled}/{len(external)} external titles")

    def execute(self, context: PipelineContext) -> PipelineContext:
        datasets = context.datasets
        if not datasets:
            logger.warning("No datasets to build hierarchy from")
            return context

        hierarchy = build_series_hierarchy(datasets)

        # Fetch titles for external references (families only — standalone are all in results)
        self._fill_external_titles(hierarchy)

        context.series_hierarchy = hierarchy

        # Count stats
        supers = sum(1 for n in hierarchy.values() if n.role == "super" and n.parent is None)
        standalone = sum(1 for n in hierarchy.values() if n.role == "standalone")
        external = sum(1 for n in hierarchy.values() if not n.in_search_results)

        logger.info(
            f"Hierarchy: {len(hierarchy)} series "
            f"({supers} families, {standalone} standalone, {external} external references)"
        )

        # Save families JSON
        if self._families_file:
            payload = serialize_families_json(hierarchy)
            with open(self._families_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"Families JSON saved to {self._families_file} ({payload['family_count']} families)")

        # Save standalone JSON
        if self._standalone_file:
            payload = serialize_standalone_json(hierarchy)
            with open(self._standalone_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.info(f"Standalone JSON saved to {self._standalone_file} ({payload['count']} series)")

        return context

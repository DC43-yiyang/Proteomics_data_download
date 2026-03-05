import logging
from pathlib import Path

from geo_agent.models.context import PipelineContext
from geo_agent.ncbi.client import NCBIClient
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)


class FetchFamilySoftSkill(Skill):
    """Fetch Family SOFT files from NCBI for standalone series only.

    Reads ``context.series_hierarchy`` (populated by HierarchySkill), filters
    for series with ``role == "standalone" and in_search_results == True``, and
    calls ``NCBIClient.fetch_family_soft_batch()`` for those accessions.

    Fetched files are saved to ``soft_dir`` as ``{GSE}_family.soft``.
    ``context.target_series_ids`` is set to the list of successfully fetched
    accessions so that FamilySoftStructurerSkill can pick them up immediately.

    SuperSeries and SubSeries are intentionally excluded — their sample
    structure requires dedicated resolution logic (deduplication across
    SubSeries, mapping samples to the correct SOFT block).
    """

    def __init__(self, ncbi_client: NCBIClient, soft_dir: str | Path) -> None:
        self._client = ncbi_client
        self._soft_dir = Path(soft_dir)

    @property
    def name(self) -> str:
        return "fetch_family_soft"

    def execute(self, context: PipelineContext) -> PipelineContext:
        if not context.series_hierarchy:
            raise SkillError(
                "FetchFamilySoftSkill: series_hierarchy is empty — run HierarchySkill first"
            )

        standalone = [
            acc
            for acc, node in context.series_hierarchy.items()
            if node.role == "standalone" and node.in_search_results
        ]

        if not standalone:
            logger.warning("FetchFamilySoftSkill: no standalone series found in hierarchy")
            return context

        total_in_hierarchy = len(context.series_hierarchy)
        skipped = total_in_hierarchy - len(standalone)
        logger.info(
            "FetchFamilySoftSkill: %d standalone series to fetch "
            "(%d super/sub skipped)",
            len(standalone),
            skipped,
        )

        self._soft_dir.mkdir(parents=True, exist_ok=True)

        raw_texts = self._client.fetch_family_soft_batch(standalone)

        fetched: list[str] = []
        for acc, text in raw_texts.items():
            if not text:
                context.errors.append(
                    f"{acc}: Family SOFT fetch returned empty response"
                )
                logger.warning("  %s: empty response — skipped", acc)
                continue

            out_path = self._soft_dir / f"{acc}_family.soft"
            out_path.write_text(text, encoding="utf-8")
            fetched.append(acc)
            logger.info("  %s: saved to %s (%d chars)", acc, out_path, len(text))

        if not fetched:
            raise SkillError(
                f"FetchFamilySoftSkill: all {len(standalone)} fetches failed"
            )

        context.target_series_ids = fetched
        logger.info(
            "FetchFamilySoftSkill: %d/%d fetched successfully",
            len(fetched),
            len(standalone),
        )
        return context

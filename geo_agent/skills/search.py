import logging
from pathlib import Path

from geo_agent.models.context import PipelineContext
from geo_agent.ncbi.client import NCBIClient
from geo_agent.ncbi.parsers import parse_esearch_response, parse_esummary_to_datasets, parse_soft_text
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)


class GEOSearchSkill(Skill):
    """Search GEO database via NCBI E-utilities.

    Reads:
        context.query — SearchQuery instance

    Writes:
        context.datasets — list[GEODataset] with metadata populated
        context.total_found — int, total matching records in GEO
    """

    def __init__(self, client: NCBIClient, fetch_details: bool = True, debug_dir: str | None = None):
        self._client = client
        self._fetch_details = fetch_details
        self._debug_dir = debug_dir

    @property
    def name(self) -> str:
        return "search"

    def execute(self, context: PipelineContext) -> PipelineContext:
        geo_query = context.query.to_geo_query()

        logger.info(f"Built query: {geo_query}")

        # Step 1: esearch to get UIDs
        try:
            search_result = self._client.esearch(
                db="gds", term=geo_query, retmax=context.query.max_results
            )
        except Exception as e:
            raise SkillError(f"esearch failed: {e}") from e

        uids, total_count = parse_esearch_response(search_result)
        logger.info(f"esearch returned {len(uids)} UIDs (total in GEO: {total_count})")

        if not uids:
            logger.warning("No matching records found")
            context.datasets = []
            context.total_found = 0
            return context

        # Step 2: esummary to get metadata
        try:
            summary_result = self._client.esummary(db="gds", ids=uids)
        except Exception as e:
            raise SkillError(f"esummary failed: {e}") from e

        datasets = parse_esummary_to_datasets(summary_result)
        logger.info(f"Populated {len(datasets)} dataset objects")

        # Step 3: Fetch SOFT metadata for Overall design
        if self._fetch_details and datasets:
            logger.info(f"Fetching detailed metadata (Overall design) for {len(datasets)} datasets...")
            accessions = [ds.accession for ds in datasets]
            soft_data = self._client.fetch_geo_soft_batch(accessions)

            # Save raw SOFT files if debug_dir is set
            if self._debug_dir:
                out = Path(self._debug_dir)
                out.mkdir(parents=True, exist_ok=True)
                for acc, text in soft_data.items():
                    if text:
                        (out / f"{acc}.soft").write_text(text, encoding="utf-8")
                logger.info(f"Saved {sum(1 for t in soft_data.values() if t)} raw SOFT files to {out}")

            for ds in datasets:
                soft_text = soft_data.get(ds.accession, "")
                if soft_text:
                    parsed = parse_soft_text(soft_text)
                    ds.overall_design = parsed.get("overall_design", "")
                    relations_str = parsed.get("relations", "")
                    if relations_str:
                        ds.relations = [r.strip() for r in relations_str.split("; ") if r.strip()]

            filled = sum(1 for ds in datasets if ds.overall_design)
            logger.info(f"Overall design populated for {filled}/{len(datasets)} datasets")

        context.datasets = datasets
        context.total_found = total_count
        return context

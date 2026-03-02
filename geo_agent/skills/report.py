import logging
from datetime import datetime

from geo_agent.models.context import PipelineContext
from geo_agent.models.dataset import GEODataset
from geo_agent.skills.base import Skill

logger = logging.getLogger(__name__)


class ReportSkill(Skill):
    """Generate a structured report from search results.

    Produces both a human-readable Markdown report and a structured data
    representation suitable for AI-driven filtering in subsequent stages.

    Reads:
        context.query — SearchQuery instance
        context.datasets — list[GEODataset]
        context.total_found — int

    Writes:
        context.report — str, human-readable Markdown report
        context.report_data — list[dict], structured per-dataset records
    """

    def __init__(self, output_file: str | None = None):
        self._output_file = output_file

    @property
    def name(self) -> str:
        return "report"

    def execute(self, context: PipelineContext) -> PipelineContext:
        datasets = context.datasets

        # Build structured data for each dataset (for AI consumption)
        report_data = []
        for ds in datasets:
            record = {
                "accession": ds.accession,
                "title": ds.title,
                "organism": ds.organism,
                "platform": ds.platform,
                "series_type": ds.series_type,
                "sample_count": ds.sample_count,
                "summary": ds.summary,
                "overall_design": ds.overall_design,
                "geo_url": ds.geo_url,
                "ftp_link": ds.ftp_link,
                "supplementary_files": [
                    {"name": f.name, "url": f.url} for f in ds.supplementary_files
                ],
            }
            report_data.append(record)

        # Build Markdown report
        report = self._build_markdown_report(context.query, datasets, context.total_found)

        context.report = report
        context.report_data = report_data

        # Optionally write to file
        if self._output_file:
            with open(self._output_file, "w", encoding="utf-8") as f:
                f.write(report)
            logger.info(f"Report written to {self._output_file}")

        logger.info(f"Report generated: {len(datasets)} datasets documented")
        return context

    def _build_markdown_report(
        self, query, datasets: list[GEODataset], total_found: int
    ) -> str:
        lines = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Header
        lines.append(f"# GEO Search Report")
        lines.append(f"")
        lines.append(f"**Generated**: {now}")
        lines.append(f"**Query**: `{query.to_geo_query()}`")
        lines.append(f"**Parameters**: {query.summary()}")
        lines.append(f"**Total in GEO**: {total_found} | **Fetched**: {len(datasets)}")
        lines.append(f"")

        if not datasets:
            lines.append("No datasets found matching the query.")
            return "\n".join(lines)

        # Summary table
        lines.append("## Dataset Overview")
        lines.append("")
        lines.append("| # | Accession | Samples | Organism | Title |")
        lines.append("|---|-----------|---------|----------|-------|")

        for i, ds in enumerate(datasets, 1):
            title = ds.title[:60] + "..." if len(ds.title) > 60 else ds.title
            organism = ds.organism or "N/A"
            link = f"[{ds.accession}]({ds.geo_url})"
            lines.append(f"| {i} | {link} | {ds.sample_count} | {organism} | {title} |")

        lines.append("")

        # Detailed sections
        lines.append("## Dataset Details")
        lines.append("")

        for ds in datasets:
            lines.append(f"### {ds.accession}: {ds.title}")
            lines.append("")
            lines.append(f"- **GEO URL**: {ds.geo_url}")
            lines.append(f"- **Organism**: {ds.organism or 'N/A'}")
            lines.append(f"- **Platform**: {ds.platform or 'N/A'}")
            lines.append(f"- **Series Type**: {ds.series_type or 'N/A'}")
            lines.append(f"- **Sample Count**: {ds.sample_count}")

            if ds.supplementary_files:
                lines.append(f"- **Supplementary Files**: {len(ds.supplementary_files)}")
                for sf in ds.supplementary_files:
                    lines.append(f"  - `{sf.name}`")

            if ds.summary:
                summary = ds.summary[:500] + "..." if len(ds.summary) > 500 else ds.summary
                lines.append(f"- **Summary**: {summary}")

            if ds.overall_design:
                design = ds.overall_design[:500] + "..." if len(ds.overall_design) > 500 else ds.overall_design
                lines.append(f"- **Overall Design**: {design}")

            lines.append("")

        return "\n".join(lines)

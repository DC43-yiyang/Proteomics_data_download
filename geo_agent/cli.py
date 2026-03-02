import sys

from geo_agent.utils.logging import setup_logging


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="geo-agent",
        description="Search and analyze GEO datasets",
    )
    sub = parser.add_subparsers(dest="command")

    # search subcommand
    search_p = sub.add_parser("search", help="Search GEO for datasets")
    search_p.add_argument(
        "--data-type", required=True,
        help='Data type to search for (e.g. "CITE-seq", "scRNA-seq", "WGS")',
    )
    search_p.add_argument(
        "--organism", default=None,
        help='Organism filter (e.g. "Homo sapiens")',
    )
    search_p.add_argument(
        "--disease", default=None,
        help='Disease filter (e.g. "breast cancer")',
    )
    search_p.add_argument(
        "--tissue", default=None,
        help='Tissue/cell type filter (e.g. "PBMC", "T cells")',
    )
    search_p.add_argument(
        "--max-results", type=int, default=100,
        help="Maximum number of results to return (default: 100)",
    )
    search_p.add_argument(
        "--report", default=None,
        help="Save report to a Markdown file (e.g. --report results.md)",
    )
    search_p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show detailed info for each dataset",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(verbose=getattr(args, "verbose", False))

    if args.command == "search":
        _run_search(args)


def _run_search(args):
    from geo_agent.agent import Agent
    from geo_agent.config import load_config
    from geo_agent.models.context import PipelineContext
    from geo_agent.models.query import SearchQuery
    from geo_agent.ncbi.client import NCBIClient
    from geo_agent.skills.search import GEOSearchSkill
    from geo_agent.skills.report import ReportSkill

    config = load_config()
    client = NCBIClient(
        api_key=config.api_key,
        email=config.email,
        tool=config.tool_name,
    )

    query = SearchQuery(
        data_type=args.data_type,
        organism=args.organism,
        disease=args.disease,
        tissue=args.tissue,
        max_results=args.max_results,
    )

    agent = Agent()
    agent.register(GEOSearchSkill(client))
    agent.register(ReportSkill(output_file=args.report))

    context = agent.run(PipelineContext(query=query))

    # Print the Markdown report to stdout
    print(context.report or "No report generated.")


if __name__ == "__main__":
    main()

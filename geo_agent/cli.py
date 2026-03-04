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
    search_p.add_argument(
        "--library-type", action="append", default=None,
        help=(
            "Filter samples by library type (e.g. GEX, ADT, TCR, BCR, HTO, ATAC). "
            "Repeatable: --library-type GEX --library-type ADT. "
            "Requires ANTHROPIC_API_KEY in .env"
        ),
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

    # When --library-type is provided, add HierarchySkill + FilterSkill + StandaloneSampleSelectorSkill
    library_types = getattr(args, "library_type", None)
    if library_types:
        from geo_agent.skills.filter import FilterSkill

        if not config.anthropic_api_key:
            print(
                "Error: --library-type requires ANTHROPIC_API_KEY in .env\n"
                "Get yours at: https://console.anthropic.com/",
                file=sys.stderr,
            )
            sys.exit(1)

        import anthropic

        anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

        from geo_agent.skills.hierarchy import HierarchySkill
        from geo_agent.skills.standalone_sample_selector import StandaloneSampleSelectorSkill

        agent.register(HierarchySkill(ncbi_client=client))
        agent.register(FilterSkill())
        agent.register(StandaloneSampleSelectorSkill(
            ncbi_client=client,
            llm_client=anthropic_client,
            model=config.llm_model,
        ))

    context = PipelineContext(query=query)
    if library_types:
        context.target_library_types = [t.upper() for t in library_types]

    context = agent.run(context)

    # Print the Markdown report to stdout
    print(context.report or "No report generated.")

    # Print sample selection summary if --library-type was used
    if library_types and context.selected_samples:
        print("\n\n## Sample Selection Summary\n")
        for gse, selections in context.selected_samples.items():
            print(f"\n### {gse} ({len(selections)} matching samples)\n")
            print("| GSM | Library Type | Confidence | Needs Review | Reasoning |")
            print("|-----|-------------|------------|--------------|-----------|")
            for s in selections:
                review = "Yes" if s.needs_review else "No"
                print(
                    f"| {s.accession} | {s.library_type} | "
                    f"{s.confidence:.2f} | {review} | {s.reasoning} |"
                )


if __name__ == "__main__":
    main()

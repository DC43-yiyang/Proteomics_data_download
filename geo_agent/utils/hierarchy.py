"""Utilities for building and displaying GEO series hierarchy (SuperSeries / SubSeries)."""

from __future__ import annotations

from dataclasses import dataclass, field

from geo_agent.models.dataset import GEODataset


@dataclass
class SeriesNode:
    """A node in the GEO series hierarchy."""

    accession: str
    title: str = ""
    role: str = "standalone"  # "super", "sub", "standalone"
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    bioproject: str = ""
    in_search_results: bool = True  # Whether this accession was in the search results


def build_series_hierarchy(datasets: list[GEODataset]) -> dict[str, SeriesNode]:
    """Build a hierarchy map from GEODataset objects with parsed relations.

    Parses ``!Series_relation`` values of the form:
        - ``SuperSeries of: GSExxxxx``
        - ``SubSeries of: GSExxxxx``
        - ``BioProject: https://...``

    Creates placeholder nodes for referenced series that are not in the search
    results (e.g. a parent SuperSeries that wasn't directly returned by GEO
    search, or a sibling SubSeries).

    Args:
        datasets: List of GEODataset objects with ``relations`` populated.

    Returns:
        Dict mapping accession -> SeriesNode with full hierarchy info.
    """
    nodes: dict[str, SeriesNode] = {}

    # First pass: create nodes for all datasets in search results
    for ds in datasets:
        node = SeriesNode(accession=ds.accession, title=ds.title)
        nodes[ds.accession] = node

        for rel in ds.relations:
            if rel.startswith("SuperSeries of: "):
                child_acc = rel.removeprefix("SuperSeries of: ").strip()
                node.role = "super"
                node.children.append(child_acc)
            elif rel.startswith("SubSeries of: "):
                parent_acc = rel.removeprefix("SubSeries of: ").strip()
                node.role = "sub"
                node.parent = parent_acc
            elif rel.startswith("BioProject: "):
                node.bioproject = rel.removeprefix("BioProject: ").strip()

    # Second pass: create placeholder nodes for referenced series not in search results
    for acc, node in list(nodes.items()):
        if node.parent and node.parent not in nodes:
            parent_node = SeriesNode(
                accession=node.parent,
                role="super",
                children=[acc],
                in_search_results=False,
            )
            nodes[node.parent] = parent_node

        for child_acc in node.children:
            if child_acc not in nodes:
                nodes[child_acc] = SeriesNode(
                    accession=child_acc,
                    role="sub",
                    parent=acc,
                    in_search_results=False,
                )

    # Third pass: ensure bidirectional consistency
    for acc, node in nodes.items():
        if node.parent and node.parent in nodes:
            parent_node = nodes[node.parent]
            if acc not in parent_node.children:
                parent_node.children.append(acc)
        for child_acc in node.children:
            if child_acc in nodes:
                child_node = nodes[child_acc]
                if child_node.parent is None:
                    child_node.parent = acc
                    child_node.role = "sub"

    return nodes


def format_families(nodes: dict[str, SeriesNode]) -> str:
    """Format only the Families section (SuperSeries -> SubSeries trees).

    Args:
        nodes: Dict from :func:`build_series_hierarchy`.

    Returns:
        Multi-line formatted string with family trees.
    """
    lines: list[str] = []

    super_roots = [
        n for n in nodes.values()
        if n.role == "super" and n.parent is None
    ]

    if not super_roots:
        lines.append("No families found.")
        return "\n".join(lines)

    lines.append(f"Families ({len(super_roots)} SuperSeries -> SubSeries):")
    lines.append("")
    for sup in sorted(super_roots, key=lambda n: n.accession):
        hit = "" if sup.in_search_results else " [not in search results]"
        title = f" -- {sup.title}" if sup.title else ""
        lines.append(f"  {sup.accession}{title}{hit}")

        sorted_children = sorted(sup.children)
        for i, child_acc in enumerate(sorted_children):
            is_last = (i == len(sorted_children) - 1)
            connector = "└── " if is_last else "├── "
            child = nodes.get(child_acc)
            if child:
                hit = "" if child.in_search_results else " [not in search results]"
                title = f" -- {child.title}" if child.title else ""
                lines.append(f"    {connector}{child.accession}{title}{hit}")
        lines.append("")

    # Summary
    n_children = sum(len(sup.children) for sup in super_roots)
    n_in_results = sum(
        1 for n in nodes.values()
        if n.in_search_results and (n.role == "super" or n.role == "sub")
        and (n.parent is not None or n.children)
    )
    n_external = len(super_roots) + n_children - n_in_results
    lines.append(
        f"Total: {len(super_roots)} families, "
        f"{n_children} sub-series | "
        f"{n_in_results} in search results, "
        f"{n_external} referenced externally"
    )

    return "\n".join(lines)


def format_standalone(nodes: dict[str, SeriesNode]) -> str:
    """Format only the Standalone section (series with no Super/Sub relations).

    Args:
        nodes: Dict from :func:`build_series_hierarchy`.

    Returns:
        Multi-line formatted string.
    """
    lines: list[str] = []

    standalone = [n for n in nodes.values() if n.role == "standalone"]

    if not standalone:
        lines.append("No standalone series found.")
        return "\n".join(lines)

    lines.append(f"Standalone ({len(standalone)} series, no Super/Sub relations):")
    lines.append("")
    for s in sorted(standalone, key=lambda n: n.accession):
        title = f" -- {s.title}" if s.title else ""
        lines.append(f"  {s.accession}{title}")

    return "\n".join(lines)


def format_series_hierarchy(nodes: dict[str, SeriesNode]) -> str:
    """Format full hierarchy as a readable tree string (families + standalone).

    Args:
        nodes: Dict from :func:`build_series_hierarchy`.

    Returns:
        Multi-line formatted string.
    """
    parts = [format_families(nodes), "", format_standalone(nodes)]

    # Overall summary
    n_total = len(nodes)
    n_in_results = sum(1 for n in nodes.values() if n.in_search_results)
    n_external = n_total - n_in_results
    super_roots = [n for n in nodes.values() if n.role == "super" and n.parent is None]
    standalone = [n for n in nodes.values() if n.role == "standalone"]
    parts.append("")
    parts.append(
        f"Total: {n_total} series ({n_in_results} in search results, "
        f"{n_external} referenced externally) | "
        f"{len(super_roots)} families, {len(standalone)} standalone"
    )

    return "\n".join(parts)

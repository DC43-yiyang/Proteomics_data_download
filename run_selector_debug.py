"""Batch selector debug runner.

Generates:
- selector_results_table.md
- selector_results_debug.json
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_agent.config import load_config
from geo_agent.ncbi.parsers import parse_family_soft
from geo_agent.skills.sample_selector import (
    heuristic_select_samples,
    preprocess_family_soft_directory,
    select_samples,
)

QUERY = os.getenv("SELECTOR_QUERY", "Extract all CITE-seq protein/ADT samples")
PHASE1_FILE = Path("debug_phase1_context.json")
FAMILY_SOFT_DIR = Path("debug_family_soft")
OUTPUT_TABLE = Path("selector_results_table.md")
OUTPUT_DEBUG = Path("selector_results_debug.json")

QUERY_STOPWORDS = {
    "all",
    "and",
    "any",
    "data",
    "dataset",
    "datasets",
    "download",
    "downloads",
    "extract",
    "for",
    "from",
    "get",
    "in",
    "me",
    "of",
    "only",
    "please",
    "retrieve",
    "sample",
    "samples",
    "select",
    "selection",
    "series",
    "show",
    "that",
    "the",
    "to",
    "what",
    "with",
}


def _build_phase1_context() -> dict[str, dict[str, Any]]:
    if PHASE1_FILE.exists():
        return json.loads(PHASE1_FILE.read_text())

    contexts = preprocess_family_soft_directory(
        input_dir=FAMILY_SOFT_DIR,
        output_file=PHASE1_FILE,
    )
    return contexts


def _build_gsm_links() -> dict[str, dict[str, list[str]]]:
    links: dict[str, dict[str, list[str]]] = {}
    for soft_file in sorted(FAMILY_SOFT_DIR.glob("*_family.soft")):
        gse_id = soft_file.stem.replace("_family", "")
        gsm_map: dict[str, list[str]] = {}
        samples = parse_family_soft(soft_file.read_text(errors="ignore"))
        for sample in samples:
            gsm_map[sample.accession] = sample.supplementary_files
        links[gse_id] = gsm_map
    return links


def _init_llm_client() -> tuple[Any | None, str | None, str]:
    config = load_config()
    model = config.llm_model

    if not config.anthropic_api_key:
        return None, model, "missing_api_key"

    try:
        import anthropic

        kwargs = {"api_key": config.anthropic_api_key}
        if config.anthropic_base_url:
            kwargs["base_url"] = config.anthropic_base_url
        return anthropic.Anthropic(**kwargs), model, "ok"
    except Exception as exc:  # pragma: no cover
        return None, model, f"client_init_failed: {exc}"


def _sample_text(sample: dict[str, Any]) -> str:
    parts = [
        str(sample.get("sample_title", "")),
        str(sample.get("molecule", "")),
        str(sample.get("library_source", "")),
    ]
    characteristics = sample.get("characteristics", {})
    if isinstance(characteristics, dict):
        parts.extend(str(v) for v in characteristics.values())
    parts.extend(str(v) for v in (sample.get("supplementary_files") or []))
    return " ".join(parts).lower()


def _extract_query_terms(query: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9+._-]{3,}", (query or "").lower())
    filtered: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in QUERY_STOPWORDS:
            continue
        if term in seen:
            continue
        seen.add(term)
        filtered.append(term)
    return filtered


def _compute_debug_counters(metadata: dict[str, Any], query_terms: list[str]) -> tuple[int, int, list[str]]:
    query_match_count = 0
    non_match_count = 0
    evidence: set[str] = set()

    for sample in metadata.get("samples", []):
        if not isinstance(sample, dict):
            continue
        text = _sample_text(sample)
        hit_terms = [kw for kw in query_terms if kw in text]

        if hit_terms:
            query_match_count += 1
            evidence.update(hit_terms)
        else:
            non_match_count += 1

    return query_match_count, non_match_count, sorted(evidence)


def _format_links(links: list[str]) -> str:
    return "<br>".join(_md_escape(link) for link in links) if links else ""


def _md_escape(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def _write_markdown_table(rows: list[dict[str, Any]], model: str | None, llm_status: str) -> None:
    header = [
        "series_id",
        "is_false_positive",
        "download_strategy",
        "selected_gsm_count",
        "selected_gsm_ids",
        "selected_links",
        "reasoning",
        "total_samples",
        "samples_with_files",
        "samples_without_files",
        "candidate_query_match_count",
        "excluded_non_match_count",
        "evidence_keywords",
        "selector_method",
        "validation_errors",
    ]

    lines = [
        "# Selector Debug Results",
        "",
        f"- query: `{QUERY}`",
        f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`",
        f"- llm_status: `{llm_status}`",
        f"- model: `{model}`",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]

    for row in rows:
        values = [
            row["series_id"],
            row["is_false_positive"],
            row["download_strategy"],
            row["selected_gsm_count"],
            "; ".join(row["selected_gsm_ids"]),
            _format_links(row["selected_links"]),
            row["reasoning"],
            row["total_samples"],
            row["samples_with_files"],
            row["samples_without_files"],
            row["candidate_query_match_count"],
            row["excluded_non_match_count"],
            ", ".join(row["evidence_keywords"]),
            row["selector_method"],
            "; ".join(row["validation_errors"]),
        ]
        lines.append("| " + " | ".join(_md_escape(v) for v in values) + " |")

    OUTPUT_TABLE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    contexts = _build_phase1_context()
    gsm_links = _build_gsm_links()
    llm_client, model, llm_status = _init_llm_client()
    query_terms = _extract_query_terms(QUERY)

    rows: list[dict[str, Any]] = []

    for series_id in sorted(contexts):
        metadata = contexts[series_id]
        validation_errors: list[str] = []
        raw_selector_output = ""
        raw_selector_json: dict[str, Any] | None = None

        if llm_client is not None:
            try:
                llm_result = select_samples(
                    query=QUERY,
                    metadata=metadata,
                    llm_client=llm_client,
                    model=model or "claude-haiku-4-5-20251001",
                    temperature=0.1,
                    include_debug=True,
                )
                selector_result = llm_result["result"]
                raw_selector_output = llm_result.get("raw_selector_output", "")
                raw_selector_json = llm_result.get("raw_selector_json")
                selector_method = "llm"
            except Exception as exc:
                selector_result = heuristic_select_samples(QUERY, metadata)
                selector_method = "heuristic_fallback"
                validation_errors.append(f"llm_failed: {exc}")
        else:
            selector_result = heuristic_select_samples(QUERY, metadata)
            selector_method = "heuristic_fallback"
            validation_errors.append(f"llm_unavailable: {llm_status}")

        selected_with_links = []
        selected_links_flat: list[str] = []

        for sample in selector_result.get("selected_samples", []):
            gsm_id = sample["gsm_id"]
            links = gsm_links.get(series_id, {}).get(gsm_id, [])
            selected_with_links.append({**sample, "supplementary_links": links})
            selected_links_flat.extend(links)

        candidate_query_match_count, excluded_non_match_count, evidence_keywords = _compute_debug_counters(
            metadata, query_terms
        )

        row = {
            "series_id": series_id,
            "is_false_positive": selector_result["is_false_positive"],
            "download_strategy": selector_result["download_strategy"],
            "selected_gsm_count": len(selector_result["selected_samples"]),
            "selected_gsm_ids": [item["gsm_id"] for item in selector_result["selected_samples"]],
            "selected_sample_titles": [item["sample_title"] for item in selector_result["selected_samples"]],
            "selected_links": selected_links_flat,
            "reasoning": selector_result["reasoning"],
            "total_samples": metadata.get("sample_count", len(metadata.get("samples", []))),
            "samples_with_files": metadata.get("samples_with_supp_files", 0),
            "samples_without_files": metadata.get("samples_without_supp_files", 0),
            "candidate_query_match_count": candidate_query_match_count,
            "excluded_non_match_count": excluded_non_match_count,
            "confidence_summary": "n/a",
            "evidence_keywords": evidence_keywords,
            "raw_selector_output": raw_selector_output,
            "raw_selector_json": raw_selector_json,
            "selected_samples_enriched": selected_with_links,
            "validation_errors": validation_errors,
            "selector_method": selector_method,
        }
        rows.append(row)

    summary = {
        "series_count": len(rows),
        "false_positive_count": sum(1 for row in rows if row["is_false_positive"]),
        "series_with_selected_samples": sum(1 for row in rows if row["selected_gsm_count"] > 0),
        "total_selected_samples": sum(row["selected_gsm_count"] for row in rows),
        "llm_status": llm_status,
        "model": model,
    }

    debug_payload = {
        "query": QUERY,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "rows": rows,
    }
    OUTPUT_DEBUG.write_text(json.dumps(debug_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    _write_markdown_table(rows, model=model, llm_status=llm_status)

    print("=" * 70)
    print(f"series_count: {summary['series_count']}")
    print(f"series_with_selected_samples: {summary['series_with_selected_samples']}")
    print(f"false_positive_count: {summary['false_positive_count']}")
    print(f"total_selected_samples: {summary['total_selected_samples']}")
    print(f"llm_status: {summary['llm_status']}")
    print(f"table: {OUTPUT_TABLE}")
    print(f"debug: {OUTPUT_DEBUG}")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""Run Family SOFT structuring debug and validate summary counts (rule-based).

Outputs are written to this directory:
- family_soft_22_structured.json
- family_soft_22_samples_table.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_agent.skills.family_soft_structurer import structure_family_soft_text

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
SOFT_DIR = PROJECT_ROOT / "debug_family_soft"
EXPECTED_FILE = HERE / "expected_22_series_summary.json"

OUTPUT_STRUCTURED = HERE / "family_soft_22_structured.json"
OUTPUT_SAMPLES_MD = HERE / "family_soft_22_samples_table.md"


def _calc_series_counts(series_data: dict[str, Any]) -> tuple[int, int, int]:
    sample_count = int(series_data.get("sample_count", 0))
    with_files = 0
    for sample in series_data.get("samples", []):
        files = sample.get("supplementary_files", []) or []
        if files:
            with_files += 1
    without_files = sample_count - with_files
    return sample_count, with_files, without_files


def _md_escape(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def _scan_series_from_soft_dir() -> list[str]:
    return sorted(path.stem.replace("_family", "") for path in SOFT_DIR.glob("*_family.soft"))


def _load_expected_map() -> dict[str, dict[str, int]]:
    if not EXPECTED_FILE.exists():
        return {}
    expected = json.loads(EXPECTED_FILE.read_text())
    out = {}
    for item in expected.get("series", []):
        sid = item.get("series_id", "")
        if sid:
            out[sid] = {
                "sample_count": int(item.get("sample_count", 0)),
                "samples_with_supp_files": int(item.get("samples_with_supp_files", 0)),
                "samples_without_supp_files": int(item.get("samples_without_supp_files", 0)),
            }
    return out


def _write_samples_table(series_payload: dict[str, dict[str, Any]], series_ids: list[str]) -> None:
    header = [
        "series_id",
        "gsm_id",
        "modality",
        "sample_title",
        "library_type",
        "library_strategy",
        "molecule",
        "organism",
        "tissue",
        "cell_type",
        "disease",
        "condition",
        "time_point",
        "age",
        "sex",
        "supp_file_count",
        "supp_file_preview",
        "sra_count",
        "biosample_count",
        "notes",
    ]
    lines = [
        "# Family SOFT Sample Table (Rule-Based)",
        "",
        f"- generated_at_utc: `{datetime.now(timezone.utc).isoformat()}`",
        "- notes: `unmapped_keywords:*` indicates tokens not currently mapped by modality rules",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]

    for series_id in series_ids:
        series = series_payload[series_id]
        for sample in series.get("samples", []):
            core = sample.get("core_characteristics", {}) or {}
            files = sample.get("supplementary_file_names", []) or []
            notes = sample.get("notes", []) or []
            row = [
                series_id,
                sample.get("gsm_id", ""),
                sample.get("inferred_library_type", ""),
                sample.get("sample_title", ""),
                sample.get("library_type", ""),
                sample.get("library_strategy", ""),
                sample.get("molecule", ""),
                sample.get("organism", ""),
                core.get("tissue", ""),
                core.get("cell type", ""),
                core.get("disease", ""),
                core.get("condition", ""),
                core.get("time point", ""),
                core.get("age", ""),
                core.get("sex", ""),
                len(files),
                "; ".join(files[:3]),
                len(sample.get("relation_sra", []) or []),
                len(sample.get("relation_biosample", []) or []),
                "; ".join(notes),
            ]
            lines.append("| " + " | ".join(_md_escape(v) for v in row) + " |")

    OUTPUT_SAMPLES_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--series-id",
        action="append",
        default=[],
        help="Run only specific GSE accession(s), e.g. --series-id GSE269123",
    )
    # Backward compatibility with previous CLI flags. They are intentionally ignored now.
    parser.add_argument("--no-llm", action="store_true", help="Deprecated: ignored in rule-based mode")
    parser.add_argument("--max-tokens", type=int, default=0, help="Deprecated: ignored in rule-based mode")
    parser.add_argument("--chunk-size", type=int, default=0, help="Deprecated: ignored in rule-based mode")
    args = parser.parse_args()

    expected_by_id = _load_expected_map()
    discovered_series_ids = _scan_series_from_soft_dir()
    all_series_ids = sorted(set(discovered_series_ids) | set(expected_by_id.keys()))

    if args.series_id:
        want = {item.strip() for item in args.series_id if item and item.strip()}
        series_ids = [sid for sid in all_series_ids if sid in want]
    else:
        series_ids = all_series_ids

    if not series_ids:
        raise SystemExit(f"No matching series IDs to run. soft_dir={SOFT_DIR}")

    if not expected_by_id:
        print(f"[info] expected summary file not found, running without baseline: {EXPECTED_FILE}", flush=True)

    if args.no_llm or args.max_tokens or args.chunk_size:
        print("[info] LLM-related flags are ignored; parser is now rule-based only", flush=True)

    print(f"[run] series_count={len(series_ids)} parser_mode=rule_based", flush=True)

    structured: dict[str, dict[str, Any]] = {}
    for idx, series_id in enumerate(series_ids, start=1):
        soft_path = SOFT_DIR / f"{series_id}_family.soft"
        if not soft_path.exists():
            raise SystemExit(f"Family SOFT file not found: {soft_path}")

        print(f"[{idx}/{len(series_ids)}] start {series_id}", flush=True)
        series_data = structure_family_soft_text(
            series_id=series_id,
            soft_text=soft_path.read_text(errors="ignore"),
            source_file=str(soft_path),
        )
        structured[series_id] = series_data
        print(
            f"[{idx}/{len(series_ids)}] done {series_id} "
            f"samples={series_data.get('sample_count', 0)} "
            f"modality_counts={series_data.get('inferred_library_type_counts', {})}",
            flush=True,
        )

    run_summary: dict[str, Any] = {}

    structured_payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parser_mode": "rule_based",
        "series_ids": series_ids,
        "series_results": structured
    }

    mismatches: list[str] = []
    series_checks: list[dict[str, Any]] = []

    total_samples = 0
    total_with_files = 0
    total_without_files = 0

    selected_expected_series = [expected_by_id[sid] for sid in series_ids if sid in expected_by_id]
    if selected_expected_series:
        expected_subset = {
            "series_count": len(selected_expected_series),
            "total_samples": sum(item["sample_count"] for item in selected_expected_series),
            "samples_with_supp_files": sum(item["samples_with_supp_files"] for item in selected_expected_series),
            "samples_without_supp_files": sum(item["samples_without_supp_files"] for item in selected_expected_series),
        }
        expected_source = str(EXPECTED_FILE)
    else:
        expected_subset = {
            "series_count": len(series_ids),
            "total_samples": 0,
            "samples_with_supp_files": 0,
            "samples_without_supp_files": 0,
        }
        expected_source = "none"

    for series_id in series_ids:
        actual_series = structured[series_id]

        actual_sample_count, actual_with_files, actual_without_files = _calc_series_counts(actual_series)
        has_expected = series_id in expected_by_id
        exp = expected_by_id.get(series_id, {})

        mismatch = False
        if has_expected:
            mismatch = (
                actual_sample_count != exp["sample_count"]
                or actual_with_files != exp["samples_with_supp_files"]
                or actual_without_files != exp["samples_without_supp_files"]
            )
            if mismatch:
                mismatches.append(
                    f"{series_id}: expected ({exp['sample_count']}, {exp['samples_with_supp_files']}, {exp['samples_without_supp_files']})"
                    f" got ({actual_sample_count}, {actual_with_files}, {actual_without_files})"
                )

        total_samples += actual_sample_count
        total_with_files += actual_with_files
        total_without_files += actual_without_files

        series_checks.append(
            {
                "series_id": series_id,
                "expected_sample_count": exp.get("sample_count", "NA"),
                "actual_sample_count": actual_sample_count,
                "expected_with_files": exp.get("samples_with_supp_files", "NA"),
                "actual_with_files": actual_with_files,
                "expected_without_files": exp.get("samples_without_supp_files", "NA"),
                "actual_without_files": actual_without_files,
                "mismatch": mismatch,
            }
        )

    actual = {
        "series_count": len(series_ids),
        "total_samples": total_samples,
        "samples_with_supp_files": total_with_files,
        "samples_without_supp_files": total_without_files,
    }

    if expected_source != "none":
        summary_mismatch = (
            actual["series_count"] != expected_subset["series_count"]
            or actual["total_samples"] != expected_subset["total_samples"]
            or actual["samples_with_supp_files"] != expected_subset["samples_with_supp_files"]
            or actual["samples_without_supp_files"] != expected_subset["samples_without_supp_files"]
        )
        if summary_mismatch:
            mismatches.append(
                "summary totals mismatch: "
                f"expected ({expected_subset['series_count']}, {expected_subset['total_samples']}, {expected_subset['samples_with_supp_files']}, {expected_subset['samples_without_supp_files']}) "
                f"got ({actual['series_count']}, {actual['total_samples']}, {actual['samples_with_supp_files']}, {actual['samples_without_supp_files']})"
            )
    else:
        expected_subset = actual.copy()

    run_summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parser_mode": "rule_based",
        "expected_source": expected_source,
        "expected": expected_subset,
        "actual": actual,
        "series_checks": series_checks,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }
    structured_payload["run_summary"] = run_summary
    OUTPUT_STRUCTURED.write_text(
        json.dumps(structured_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_samples_table(structured, series_ids)

    print(f"written: {OUTPUT_STRUCTURED}")
    print(f"written: {OUTPUT_SAMPLES_MD}")
    print(f"mismatch_count: {len(mismatches)}")


if __name__ == "__main__":
    main()

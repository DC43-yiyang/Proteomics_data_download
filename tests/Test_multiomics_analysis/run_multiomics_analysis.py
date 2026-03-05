"""Multi-omics annotation runner.

Reads a pre-parsed Family SOFT structured JSON, calls the local Ollama model
for each series, and writes:
  - multiomics_results.json        full per-sample annotation
  - multiomics_results_table.md    human-readable summary + flat sample table

Usage
-----
    python run_multiomics_analysis.py

Environment overrides (all optional):
    OLLAMA_BASE_URL   default: http://localhost:11434
    OLLAMA_MODEL      default: see AVAILABLE_MODELS below
    STRUCTURED_JSON   default: tests/Test_family_soft_parse/family_soft_22_structured.json
    TARGET_SERIES     comma-separated GSE IDs to process; default: all
    NUM_WORKERS       parallel workers (requires OLLAMA_NUM_PARALLEL >= this); default: 1
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_agent.llm.ollama_client import OllamaClient
from geo_agent.skills.multiomics_analyzer import annotate_series

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model selection — change DEFAULT_MODEL to switch models
# ---------------------------------------------------------------------------

AVAILABLE_MODELS = {
    "qwen3.5-35b-q8":  "qwen3.5:35b-a3b-q8_0",   # best quality, ~46 GiB VRAM
    "qwen3.5-35b-q4":  "qwen3.5:35b-a3b-q4_K_M",  # lighter, ~20 GiB VRAM
    "qwen3-30b":       "qwen3:30b-a3b",            # fast fallback
}

DEFAULT_MODEL = "qwen3.5-35b-q8"   # <-- change this line to switch models

# ---------------------------------------------------------------------------

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", AVAILABLE_MODELS[DEFAULT_MODEL])
NUM_WORKERS = int(os.getenv("NUM_WORKERS", "1"))  # <-- set to 2~4 to enable parallel
STRUCTURED_JSON = Path(
    os.getenv(
        "STRUCTURED_JSON",
        "../Test_family_soft_parse/family_soft_22_structured.json",
    )
)
TARGET_SERIES: list[str] = [
    s.strip()
    for s in os.getenv("TARGET_SERIES", "").split(",")
    if s.strip()
]

_prefix = TARGET_SERIES[0] if len(TARGET_SERIES) == 1 else "multiomics"
_model_slug = OLLAMA_MODEL.replace(":", "_").replace("/", "_")
OUTPUT_JSON = Path(f"{_prefix}_{_model_slug}_results.json")
OUTPUT_TABLE = Path(f"{_prefix}_{_model_slug}_results_table.md")


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _md(v: Any) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def _layers_cell(layers: list[str]) -> str:
    return ", ".join(layers) if layers else "—"


def _write_outputs(rows: list[dict[str, Any]], model: str, generated_at: str) -> None:
    lines: list[str] = [
        "# Multi-omics Annotation Results",
        "",
        f"- model: `{model}`",
        f"- generated_at_utc: `{generated_at}`",
        f"- input: `{STRUCTURED_JSON}`",
        "",
        "## Series Summary",
        "",
        "| series_id | disease | tissue | samples | layers_present | status |",
        "|---|---|---|---:|---|---|",
    ]

    for row in rows:
        if row.get("error"):
            lines.append(
                f"| {row['series_id']} | — | — | — | — | ERROR: {_md(row['error'])} |"
            )
            continue

        all_layers: set[str] = set()
        for s in row.get("samples", []):
            all_layers.update(s.get("measured_layers", []))

        lines.append(
            "| "
            + " | ".join([
                _md(row["series_id"]),
                _md(row.get("disease_normalized", "—")),
                _md(row.get("tissue_normalized", "—")),
                str(row.get("sample_count", 0)),
                _md(", ".join(sorted(all_layers))),
                "ok",
            ])
            + " |"
        )

    # Per-sample flat table
    lines += [
        "",
        "---",
        "",
        "## Per-sample Annotations",
        "",
        "| series_id | gsm_id | sample_title | measured_layers | platform | assay"
        " | disease | tissue | tissue_subtype | confidence | evidence |",
        "|---|---|---|---|---|---|---|---|---|---:|---|",
    ]

    for row in rows:
        if row.get("error"):
            continue
        sid = row["series_id"]
        for s in row.get("samples", []):
            lines.append(
                "| "
                + " | ".join([
                    _md(sid),
                    _md(s.get("gsm_id", "")),
                    _md(s.get("sample_title", "")),
                    _md(_layers_cell(s.get("measured_layers", []))),
                    _md(s.get("platform", "")),
                    _md(s.get("assay", "")),
                    _md(s.get("disease", "")),
                    _md(s.get("tissue", "")),
                    _md(s.get("tissue_subtype", "")),
                    f"{s.get('confidence', 0):.2f}",
                    _md(s.get("evidence", "")),
                ])
                + " |"
            )

    OUTPUT_TABLE.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _process_one(
    series_id: str,
    series_data: dict[str, Any],
    client: OllamaClient,
    total: int,
    counter: list[int],
    lock: threading.Lock,
) -> dict[str, Any]:
    with lock:
        counter[0] += 1
        idx = counter[0]

    n = series_data.get("sample_count", "?")
    logger.info("[%d/%d] %s  (%s samples)", idx, total, series_id, n)

    try:
        result = annotate_series(
            series_data=series_data,
            llm_client=client,
            model=OLLAMA_MODEL,
        )
    except Exception as exc:
        logger.error("  %s FAILED: %s", series_id, exc)
        return {"series_id": series_id, "error": str(exc)}

    if not result.get("error"):
        all_layers: set[str] = set()
        for s in result.get("samples", []):
            all_layers.update(s.get("measured_layers", []))
        logger.info(
            "  %s done | layers: %s | disease: %s | tissue: %s",
            series_id,
            sorted(all_layers),
            result.get("disease_normalized", "?"),
            result.get("tissue_normalized", "?"),
        )

    return result


def main() -> None:
    client = OllamaClient(base_url=OLLAMA_BASE_URL)
    if not client.health_check():
        logger.error("Ollama not reachable at %s", OLLAMA_BASE_URL)
        sys.exit(1)

    if not STRUCTURED_JSON.exists():
        logger.error("Input not found: %s", STRUCTURED_JSON)
        sys.exit(1)

    structured = json.loads(STRUCTURED_JSON.read_text(encoding="utf-8"))
    series_results = structured.get("series_results", {})
    all_ids = TARGET_SERIES if TARGET_SERIES else sorted(series_results.keys())
    series_ids = [sid for sid in all_ids if sid in series_results]

    skipped = set(all_ids) - set(series_ids)
    for sid in skipped:
        logger.warning("%s not in input, skipping", sid)

    logger.info(
        "Model: %s | Workers: %d | Series to process: %d",
        OLLAMA_MODEL, NUM_WORKERS, len(series_ids),
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    counter: list[int] = [0]
    lock = threading.Lock()

    if NUM_WORKERS <= 1:
        rows: list[dict[str, Any]] = [
            _process_one(sid, series_results[sid], client, len(series_ids), counter, lock)
            for sid in series_ids
        ]
    else:
        rows_map: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
            futures = {
                pool.submit(
                    _process_one,
                    sid, series_results[sid], client, len(series_ids), counter, lock,
                ): sid
                for sid in series_ids
            }
            for future in as_completed(futures):
                result = future.result()
                rows_map[result["series_id"]] = result
        # preserve original order
        rows = [rows_map[sid] for sid in series_ids if sid in rows_map]

    # Persist
    payload = {
        "model": OLLAMA_MODEL,
        "generated_at_utc": generated_at,
        "input_file": str(STRUCTURED_JSON),
        "series_count": len(rows),
        "results": {r["series_id"]: r for r in rows},
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_outputs(rows, model=OLLAMA_MODEL, generated_at=generated_at)

    ok = sum(1 for r in rows if not r.get("error"))
    print("=" * 60)
    print(f"processed : {len(rows)}  ok: {ok}  errors: {len(rows) - ok}")
    print(f"workers   : {NUM_WORKERS}")
    print(f"json      : {OUTPUT_JSON}")
    print(f"table     : {OUTPUT_TABLE}")
    print("=" * 60)


if __name__ == "__main__":
    main()

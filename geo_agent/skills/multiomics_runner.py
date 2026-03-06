"""Runner logic for multi-omics annotation — both per-series and per-sample modes.

Entry points
------------
    run_sample_mode(output_dir, structured_json)   -- one LLM call per GSM sample
    run_series_mode(output_dir, structured_json)   -- one LLM call per GEO series

Both functions read configuration from environment variables (see below) and
write results under the provided output_dir.

Environment variables (all optional)
-------------------------------------
    OLLAMA_BASE_URL   default: http://localhost:11434
    OLLAMA_MODEL      default: qwen3.5:35b-a3b
    OLLAMA_TIMEOUT    default: 600
    TARGET_SERIES     comma-separated GSE IDs; default: all
    NUM_WORKERS       parallel workers; sample default: 4, series default: 1
    MAX_RETRIES       retries per call; default: 2
    LLM_TEMPERATURE   default: 0.0
    RETRY_TEMP_STEP   added temperature per retry; default: 0.0
    STRICT_JSON_MODE  1/0; default: 1
    DISABLE_THINKING  1/0; default: 0
    LLM_SEED          optional integer seed
    DEBUG_RAW_LLM_DIR directory to save raw failed LLM outputs
    MAX_TOKENS        default: 16384
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
from geo_agent.skills.multiomics_analyze_sample import annotate_sample
from geo_agent.skills.multiomics_analyze_series import annotate_series

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

AVAILABLE_MODELS: dict[str, str] = {
    "qwen3.5-35b-q8": "qwen3.5:35b-a3b-q8_0",
    "qwen3.5-35b":    "qwen3.5:35b-a3b",
    "qwen3-30b":      "qwen3:30b-a3b",
}

DEFAULT_MODEL = "qwen3.5-35b"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_config(default_workers: int) -> dict[str, Any]:
    model = os.getenv("OLLAMA_MODEL", AVAILABLE_MODELS[DEFAULT_MODEL])
    seed_raw = os.getenv("LLM_SEED", "").strip()
    debug_raw = os.getenv("DEBUG_RAW_LLM_DIR", "").strip()
    return {
        "base_url":        os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "model":           model,
        "model_slug":      model.replace(":", "_").replace("/", "_"),
        "num_workers":     int(os.getenv("NUM_WORKERS", str(default_workers))),
        "timeout":         int(os.getenv("OLLAMA_TIMEOUT", "600")),
        "max_tokens":      int(os.getenv("MAX_TOKENS", "16384")),
        "max_retries":     int(os.getenv("MAX_RETRIES", "2")),
        "temperature":     float(os.getenv("LLM_TEMPERATURE", "0.0")),
        "retry_temp_step": float(os.getenv("RETRY_TEMP_STEP", "0.0")),
        "strict_json":     _env_bool("STRICT_JSON_MODE", True),
        "disable_thinking":_env_bool("DISABLE_THINKING", False),
        "seed":            int(seed_raw) if seed_raw else None,
        "debug_raw_dir":   Path(debug_raw) if debug_raw else None,
        "target_series":   [s.strip() for s in os.getenv("TARGET_SERIES", "").split(",") if s.strip()],
    }


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def _md(v: Any) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def _layers_cell(layers: list[str]) -> str:
    return ", ".join(layers) if layers else "—"


def _write_sample_table(rows: list[dict[str, Any]], output_path: Path, model: str, generated_at: str, input_file: str) -> None:
    lines: list[str] = [
        "# Multi-omics Annotation Results (per-sample)",
        "",
        f"- model: `{model}`",
        f"- generated_at_utc: `{generated_at}`",
        f"- input: `{input_file}`",
        "",
        "| series_id | gsm_id | sample_title | measured_layers | platform | experiment"
        " | assay | disease | tissue | tissue_subtype | confidence | evidence |",
        "|---|---|---|---|---|---|---|---|---|---|---:|---|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(
                f"| {_md(r.get('series_id',''))} | {_md(r.get('gsm_id',''))} "
                f"| — | — | — | — | — | — | — | — | — | ERROR: {_md(r['error'])} |"
            )
            continue
        lines.append(
            "| " + " | ".join([
                _md(r.get("series_id", "")),
                _md(r.get("gsm_id", "")),
                _md(r.get("sample_title", "")),
                _md(_layers_cell(r.get("measured_layers", []))),
                _md(r.get("platform", "")),
                _md(r.get("experiment", "")),
                _md(r.get("assay", "")),
                _md(r.get("disease", "")),
                _md(r.get("tissue", "")),
                _md(r.get("tissue_subtype", "")),
                f"{r.get('confidence', 0):.2f}",
                _md(r.get("evidence", "")),
            ]) + " |"
        )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_series_table(rows: list[dict[str, Any]], output_path: Path, model: str, generated_at: str, input_file: str) -> None:
    lines: list[str] = [
        "# Multi-omics Annotation Results (per-series)",
        "",
        f"- model: `{model}`",
        f"- generated_at_utc: `{generated_at}`",
        f"- input: `{input_file}`",
        "",
        "## Series Summary",
        "",
        "| series_id | disease | tissue | samples | layers_present | status |",
        "|---|---|---|---:|---|---|",
    ]
    for row in rows:
        if row.get("error"):
            lines.append(f"| {row['series_id']} | — | — | — | — | ERROR: {_md(row['error'])} |")
            continue
        all_layers: set[str] = set()
        for s in row.get("samples", []):
            all_layers.update(s.get("measured_layers", []))
        lines.append(
            "| " + " | ".join([
                _md(row["series_id"]),
                _md(row.get("disease_normalized", "—")),
                _md(row.get("tissue_normalized", "—")),
                str(row.get("sample_count", 0)),
                _md(", ".join(sorted(all_layers))),
                "ok",
            ]) + " |"
        )

    lines += [
        "", "---", "",
        "## Per-sample Annotations", "",
        "| series_id | gsm_id | sample_title | measured_layers | platform | experiment"
        " | assay | disease | tissue | tissue_subtype | confidence | evidence |",
        "|---|---|---|---|---|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        if row.get("error"):
            continue
        sid = row["series_id"]
        for s in row.get("samples", []):
            lines.append(
                "| " + " | ".join([
                    _md(sid),
                    _md(s.get("gsm_id", "")),
                    _md(s.get("sample_title", "")),
                    _md(_layers_cell(s.get("measured_layers", []))),
                    _md(s.get("platform", "")),
                    _md(s.get("experiment", "")),
                    _md(s.get("assay", "")),
                    _md(s.get("disease", "")),
                    _md(s.get("tissue", "")),
                    _md(s.get("tissue_subtype", "")),
                    f"{s.get('confidence', 0):.2f}",
                    _md(s.get("evidence", "")),
                ]) + " |"
            )
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

def _process_sample(
    series_id: str,
    series_data: dict[str, Any],
    sample: dict[str, Any],
    client: OllamaClient,
    cfg: dict[str, Any],
    total: int,
    counter: list[int],
    lock: threading.Lock,
) -> dict[str, Any]:
    gsm_id = sample.get("gsm_id", "unknown")
    with lock:
        counter[0] += 1
        idx = counter[0]
    logger.info("[%d/%d] %s / %s", idx, total, series_id, gsm_id)

    try:
        result = annotate_sample(
            series_data=series_data,
            sample=sample,
            llm_client=client,
            model=cfg["model"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
            max_retries=cfg["max_retries"],
            retry_temperature_step=cfg["retry_temp_step"],
            strict_json_mode=cfg["strict_json"],
            seed=cfg["seed"],
            disable_thinking=cfg["disable_thinking"],
            debug_raw_dir=cfg["debug_raw_dir"],
        )
    except Exception as exc:
        logger.error("  %s/%s FAILED: %s", series_id, gsm_id, exc)
        return {"series_id": series_id, "gsm_id": gsm_id, "error": str(exc)}

    logger.info(
        "  %s/%s done | layers: %s | disease: %s | tissue: %s",
        series_id, gsm_id,
        result.get("measured_layers"), result.get("disease"), result.get("tissue"),
    )
    return result


def _process_series(
    series_id: str,
    series_data: dict[str, Any],
    client: OllamaClient,
    cfg: dict[str, Any],
    total: int,
    counter: list[int],
    lock: threading.Lock,
) -> dict[str, Any]:
    with lock:
        counter[0] += 1
        idx = counter[0]
    logger.info("[%d/%d] %s  (%s samples)", idx, total, series_id, series_data.get("sample_count", "?"))

    try:
        result = annotate_series(
            series_data=series_data,
            llm_client=client,
            model=cfg["model"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
            max_retries=cfg["max_retries"],
            retry_temperature_step=cfg["retry_temp_step"],
            strict_json_mode=cfg["strict_json"],
            seed=cfg["seed"],
            disable_thinking=cfg["disable_thinking"],
            debug_raw_dir=cfg["debug_raw_dir"],
        )
    except Exception as exc:
        logger.error("  %s FAILED: %s", series_id, exc)
        return {"series_id": series_id, "error": str(exc)}

    all_layers: set[str] = set()
    for s in result.get("samples", []):
        all_layers.update(s.get("measured_layers", []))
    logger.info(
        "  %s done | layers: %s | disease: %s | tissue: %s",
        series_id, sorted(all_layers),
        result.get("disease_normalized", "?"), result.get("tissue_normalized", "?"),
    )
    return result


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run_sample_mode(
    output_dir: Path,
    structured_json: Path,
    output_prefix: str = "",
    target_sample_indices: list[int] | None = None,
) -> None:
    """Run per-sample annotation and write results under output_dir/series/{series_id}/{gsm_id}.json.

    Args:
        output_prefix:          prepended to combined output filenames (e.g. "GSE266455_")
        target_sample_indices:  0-based indices within each series to process; None means all
    """
    cfg = _load_config(default_workers=4)
    client = OllamaClient(base_url=cfg["base_url"], timeout=cfg["timeout"])
    if not client.health_check():
        logger.error("Ollama not reachable at %s", cfg["base_url"])
        sys.exit(1)

    series_results, series_ids = _load_input(structured_json, cfg["target_series"])

    tasks = []
    for sid in series_ids:
        samples = series_results[sid].get("samples", [])
        for i, sample in enumerate(samples):
            if target_sample_indices is None or i in target_sample_indices:
                tasks.append((sid, series_results[sid], sample))

    task_keys = [(sid, s.get("gsm_id", "")) for sid, _, s in tasks]
    total = len(tasks)

    _log_config(cfg, mode="sample", series_count=len(series_ids), sample_count=total)

    generated_at = datetime.now(timezone.utc).isoformat()
    counter: list[int] = [0]
    lock = threading.Lock()

    rows = _run_parallel(
        tasks=tasks,
        worker=lambda sid, sdata, sample: _process_sample(sid, sdata, sample, client, cfg, total, counter, lock),
        task_keys=task_keys,
        num_workers=cfg["num_workers"],
        key_fn=lambda r: (r["series_id"], r.get("gsm_id", "")),
    )

    # Per-sample JSON files
    series_dir = output_dir / "series"
    series_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        sid    = r.get("series_id", "unknown")
        gsm_id = r.get("gsm_id", "unknown")
        d = series_dir / sid
        d.mkdir(exist_ok=True)
        (d / f"{gsm_id}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

    # Combined outputs
    slug = cfg["model_slug"]
    combined = {
        "model": cfg["model"],
        "generated_at_utc": generated_at,
        "input_file": str(structured_json),
        "sample_count": len(rows),
        "results": {
            sid: {r["gsm_id"]: r for r in rows if r.get("series_id") == sid}
            for sid in series_ids
        },
    }
    (output_dir / f"{output_prefix}{slug}_results.json").write_text(
        json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_sample_table(
        rows, output_dir / f"{output_prefix}{slug}_results_table.md",
        cfg["model"], generated_at, str(structured_json),
    )

    _print_summary(rows, cfg["num_workers"], output_dir, mode="sample")


def run_series_mode(
    output_dir: Path,
    structured_json: Path,
    output_prefix: str = "",
) -> None:
    """Run per-series annotation and write results under output_dir/.

    Args:
        output_prefix: prepended to output filenames (e.g. "GSE266455_")
    """
    cfg = _load_config(default_workers=1)
    client = OllamaClient(base_url=cfg["base_url"], timeout=cfg["timeout"])
    if not client.health_check():
        logger.error("Ollama not reachable at %s", cfg["base_url"])
        sys.exit(1)

    series_results, series_ids = _load_input(structured_json, cfg["target_series"])
    total = len(series_ids)

    _log_config(cfg, mode="series", series_count=total, sample_count=None)

    generated_at = datetime.now(timezone.utc).isoformat()
    counter: list[int] = [0]
    lock = threading.Lock()

    rows = _run_parallel(
        tasks=[(sid, series_results[sid], None) for sid in series_ids],
        worker=lambda sid, sdata, _: _process_series(sid, sdata, client, cfg, total, counter, lock),
        task_keys=[(sid, None) for sid in series_ids],
        num_workers=cfg["num_workers"],
        key_fn=lambda r: (r["series_id"], None),
    )

    slug = cfg["model_slug"]
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": cfg["model"],
        "generated_at_utc": generated_at,
        "input_file": str(structured_json),
        "series_count": len(rows),
        "results": {r["series_id"]: r for r in rows},
    }
    (output_dir / f"{output_prefix}{slug}_series_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_series_table(
        rows, output_dir / f"{output_prefix}{slug}_series_results_table.md",
        cfg["model"], generated_at, str(structured_json),
    )

    _print_summary(rows, cfg["num_workers"], output_dir, mode="series")


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _load_input(structured_json: Path, target_series: list[str]) -> tuple[dict, list[str]]:
    if not structured_json.exists():
        logger.error("Input not found: %s", structured_json)
        sys.exit(1)
    data = json.loads(structured_json.read_text(encoding="utf-8"))
    series_results = data.get("series_results", {})
    all_ids = target_series if target_series else sorted(series_results.keys())
    series_ids = [sid for sid in all_ids if sid in series_results]
    for sid in set(all_ids) - set(series_ids):
        logger.warning("%s not in input, skipping", sid)
    return series_results, series_ids


def _log_config(cfg: dict[str, Any], mode: str, series_count: int, sample_count: int | None) -> None:
    count_str = f"Series: {series_count}" + (f" | Samples: {sample_count}" if sample_count is not None else "")
    logger.info(
        "Mode: %s | Model: %s | Workers: %d | %s | "
        "strict_json=%s | temp=%.2f | retry_step=%.2f | retries=%d | "
        "disable_thinking=%s | seed=%s | debug_raw=%s",
        mode, cfg["model"], cfg["num_workers"], count_str,
        cfg["strict_json"], cfg["temperature"], cfg["retry_temp_step"], cfg["max_retries"],
        cfg["disable_thinking"],
        cfg["seed"] if cfg["seed"] is not None else "none",
        str(cfg["debug_raw_dir"]) if cfg["debug_raw_dir"] else "off",
    )


def _run_parallel(
    tasks: list[tuple],
    worker,
    task_keys: list[tuple],
    num_workers: int,
    key_fn,
) -> list[dict[str, Any]]:
    if num_workers <= 1:
        return [worker(*t) for t in tasks]

    rows_map: dict[tuple, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(worker, *t): t for t in tasks}
        for future in as_completed(futures):
            r = future.result()
            rows_map[key_fn(r)] = r
    return [rows_map[k] for k in task_keys if k in rows_map]


def _print_summary(rows: list[dict[str, Any]], num_workers: int, output_dir: Path, mode: str) -> None:
    ok = sum(1 for r in rows if not r.get("error"))
    print("=" * 60)
    print(f"mode      : {mode}")
    print(f"processed : {len(rows)}  ok: {ok}  errors: {len(rows) - ok}")
    print(f"workers   : {num_workers}")
    print(f"output    : {output_dir}")
    print("=" * 60)

"""Runner logic for multi-omics annotation — both per-series and per-sample modes.

Entry points
------------
    run_sample_mode(output_dir, structured_json)   -- one LLM call per GSM sample
    run_series_mode(output_dir, structured_json)   -- one LLM call per GEO series

Both functions read configuration from environment variables (see below) and
write results under the provided output_dir.

Environment variables (all optional)
-------------------------------------
    LLM_PROVIDER      provider name (ollama, deepseek, qwen, kimi, minimax, openai); default: ollama
    LLM_API_KEY       API key (required for non-ollama providers)
    LLM_BASE_URL      base URL (optional, uses provider default if not specified)
    LLM_ANNOTATION_MODEL  model name; default: provider-specific
    LLM_TIMEOUT       request timeout in seconds; default: 600
    TARGET_SERIES     comma-separated GSE IDs; default: all
    NUM_WORKERS       parallel workers; default: 1 (serial), set >1 for parallel
    PARALLEL_MODE     1=parallel (save per-series), 0=serial (save merged); default: 0
    MAX_RETRIES       retries per call; default: 2
    LLM_TEMPERATURE   default: 0.0
    RETRY_TEMP_STEP   added temperature per retry; default: 0.0
    STRICT_JSON_MODE  1/0; default: 1
    DISABLE_THINKING  1/0; default: 0
    LLM_SEED          optional integer seed
    DEBUG_RAW_LLM_DIR directory to save raw failed LLM outputs
    MAX_TOKENS        default: 16384
    CHUNK_SIZE        max samples per LLM call; 0=no chunking; default: 15

Legacy environment variables (deprecated, use LLM_* instead):
    OLLAMA_BASE_URL   -> use LLM_BASE_URL
    OLLAMA_MODEL      -> use LLM_ANNOTATION_MODEL
    OLLAMA_TIMEOUT    -> use LLM_TIMEOUT
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

from geo_agent.llm import create_llm_client, get_default_model
from geo_agent.skills.layer_split_detector import detect_layer_split
from geo_agent.skills.multiomics_analyze_sample import annotate_sample
from geo_agent.skills.multiomics_analyze_series import (
    annotate_series,
    annotate_series_chunk,
    load_prompt,
    merge_chunk_results,
    split_series_into_chunks,
)

# Load .env file at module import time
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry (legacy, kept for backward compatibility)
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
    # Provider and credentials
    provider = os.getenv("LLM_PROVIDER", "ollama")
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "")

    # Legacy support: OLLAMA_BASE_URL -> LLM_BASE_URL
    if not base_url and os.getenv("OLLAMA_BASE_URL"):
        base_url = os.getenv("OLLAMA_BASE_URL", "")

    # Model selection with legacy support
    model = os.getenv("LLM_ANNOTATION_MODEL", "")
    if not model and os.getenv("OLLAMA_MODEL"):
        # Legacy OLLAMA_MODEL support
        model = os.getenv("OLLAMA_MODEL", AVAILABLE_MODELS[DEFAULT_MODEL])
    elif not model:
        # Use provider default
        try:
            model = get_default_model(provider)
        except ValueError:
            model = "qwen3:30b-a3b"  # fallback

    # Timeout with legacy support
    timeout_str = os.getenv("LLM_TIMEOUT") or os.getenv("OLLAMA_TIMEOUT") or "600"

    seed_raw = os.getenv("LLM_SEED", "").strip()
    debug_raw = os.getenv("DEBUG_RAW_LLM_DIR", "").strip()

    return {
        "provider":        provider,
        "api_key":         api_key or None,
        "base_url":        base_url or None,
        "model":           model,
        "model_slug":      model.replace(":", "_").replace("/", "_"),
        "num_workers":     int(os.getenv("NUM_WORKERS", str(default_workers))),
        "parallel_mode":   _env_bool("PARALLEL_MODE", False),
        "timeout":         int(timeout_str),
        "max_tokens":      int(os.getenv("MAX_TOKENS", "131072")),
        "max_retries":     int(os.getenv("MAX_RETRIES", "2")),
        "temperature":     float(os.getenv("LLM_TEMPERATURE", "0.0")),
        "retry_temp_step": float(os.getenv("RETRY_TEMP_STEP", "0.0")),
        "strict_json":     _env_bool("STRICT_JSON_MODE", True),
        "disable_thinking":_env_bool("DISABLE_THINKING", True),
        "seed":            int(seed_raw) if seed_raw else None,
        "debug_raw_dir":   Path(debug_raw) if debug_raw else None,
        "target_series":   [s.strip() for s in os.getenv("TARGET_SERIES", "").split(",") if s.strip()],
        "chunk_size":      int(os.getenv("CHUNK_SIZE", "15")),
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
        "| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for row in rows:
        if row.get("error"):
            lines.append(f"| {row['series_id']} | — | — | — | — | — | — | ERROR: {_md(row['error'])} |")
            continue
        all_layers: set[str] = set()
        for s in row.get("samples", []):
            all_layers.update(s.get("measured_layers", []))
        bio_count = row.get("biological_sample_count", row.get("sample_count", 0))
        split_ratio = row.get("layer_split_ratio", "")
        lines.append(
            "| " + " | ".join([
                _md(row["series_id"]),
                _md(row.get("disease_normalized", "—")),
                _md(row.get("tissue_normalized", "—")),
                str(row.get("sample_count", 0)),
                str(bio_count),
                _md(split_ratio) if split_ratio else "—",
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
    client: Any,
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
    client: Any,
    cfg: dict[str, Any],
    total: int,
    counter: list[int],
    lock: threading.Lock,
) -> dict[str, Any]:
    with lock:
        counter[0] += 1
        idx = counter[0]
    logger.info("[%d/%d] %s  (%s samples)", idx, total, series_id, series_data.get("sample_count", "?"))

    # Run layer-split heuristic before LLM call
    layer_hint = detect_layer_split(series_data.get("samples", []))
    if layer_hint.get("suspected_layer_split"):
        logger.info("  %s: layer-split suspected (confidence=%s, groups=%d, ratio=%s)",
                     series_id, layer_hint["confidence"],
                     layer_hint["heuristic_bio_sample_count"], layer_hint["heuristic_split_ratio"])
        series_data = {**series_data, "layer_split_hint": layer_hint}

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
            chunk_size=cfg["chunk_size"],
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
    series_context: dict[str, dict[str, str]] | None = None,
) -> None:
    """Run per-sample annotation and write results under output_dir/series/{series_id}/{gsm_id}.json.

    Args:
        output_prefix:          prepended to combined output filenames (e.g. "GSE266455_")
        target_sample_indices:  0-based indices within each series to process; None means all
        series_context:         optional dict mapping series_id -> {"summary": ..., "overall_design": ...}
    """
    cfg = _load_config(default_workers=4)
    client = create_llm_client(
        provider=cfg["provider"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout=cfg["timeout"],
    )
    if not client.health_check():
        logger.error("LLM client not reachable (provider: %s, base_url: %s)", cfg["provider"], cfg["base_url"] or "default")
        sys.exit(1)

    series_results, series_ids = _load_input(structured_json, cfg["target_series"])

    # Enrich with series-level context (summary, overall_design) if provided
    if series_context:
        for sid in series_ids:
            if sid in series_context:
                series_results[sid] = {**series_results[sid], **series_context[sid]}

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
    series_context: dict[str, dict[str, str]] | None = None,
) -> None:
    """Run per-series annotation and write results under output_dir/.

    Args:
        output_prefix: prepended to output filenames (e.g. "GSE266455_")
        series_context: optional dict mapping series_id -> {"summary": ..., "overall_design": ...}

    Modes:
        Serial (PARALLEL_MODE=0, default):
            - Process series one by one (NUM_WORKERS=1)
            - Save merged results to: {output_prefix}{model_slug}_series_results.json

        Parallel (PARALLEL_MODE=1):
            - Process multiple series concurrently (NUM_WORKERS>1)
            - Save each series immediately after processing to: series/{series_id}/{model_slug}_result.json
            - Also save merged results at the end
    """
    cfg = _load_config(default_workers=1)
    client = create_llm_client(
        provider=cfg["provider"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout=cfg["timeout"],
    )
    if not client.health_check():
        logger.error("LLM client not reachable (provider: %s, base_url: %s)", cfg["provider"], cfg["base_url"] or "default")
        sys.exit(1)

    series_results, series_ids = _load_input(structured_json, cfg["target_series"])

    # Enrich with series-level context (summary, overall_design) if provided
    if series_context:
        for sid in series_ids:
            if sid in series_context:
                series_results[sid] = {**series_results[sid], **series_context[sid]}

    total = len(series_ids)

    _log_config(cfg, mode="series", series_count=total, sample_count=None)

    generated_at = datetime.now(timezone.utc).isoformat()
    slug = cfg["model_slug"]
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prepare series directory for parallel mode
    if cfg["parallel_mode"]:
        series_dir = output_dir / "series"
        series_dir.mkdir(parents=True, exist_ok=True)

    counter: list[int] = [0]
    lock = threading.Lock()

    # Process with immediate saving in parallel mode
    if cfg["parallel_mode"] and cfg["num_workers"] > 1:
        rows = _run_parallel_with_save(
            series_ids=series_ids,
            series_results=series_results,
            client=client,
            cfg=cfg,
            output_dir=output_dir,
            generated_at=generated_at,
            structured_json=structured_json,
            total=total,
            counter=counter,
            lock=lock,
        )
    else:
        # Serial mode: collect all results first, then save
        rows = _run_parallel(
            tasks=[(sid, series_results[sid], None) for sid in series_ids],
            worker=lambda sid, sdata, _: _process_series(sid, sdata, client, cfg, total, counter, lock),
            task_keys=[(sid, None) for sid in series_ids],
            num_workers=cfg["num_workers"],
            key_fn=lambda r: (r["series_id"], None),
        )

    # Always save merged results (for both serial and parallel modes)
    payload = {
        "model": cfg["model"],
        "generated_at_utc": generated_at,
        "input_file": str(structured_json),
        "series_count": len(rows),
        "parallel_mode": cfg["parallel_mode"],
        "num_workers": cfg["num_workers"],
        "results": {r["series_id"]: r for r in rows},
    }
    merged_file = output_dir / f"{output_prefix}{slug}_series_results.json"
    merged_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

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


def _run_parallel_with_save(
    series_ids: list[str],
    series_results: dict[str, Any],
    client: Any,
    cfg: dict[str, Any],
    output_dir: Path,
    generated_at: str,
    structured_json: Path,
    total: int,
    counter: list[int],
    lock: threading.Lock,
) -> list[dict[str, Any]]:
    """Process series in parallel at chunk granularity and save results.

    Instead of submitting whole series as work items (which causes large series
    to hold workers while running chunks sequentially inside), this function:
    1. Pre-splits all series into chunks
    2. Submits individual chunks to the thread pool
    3. Merges chunk results per series after all complete

    This ensures NUM_WORKERS controls actual concurrent LLM requests.
    """
    slug = cfg["model_slug"]
    series_dir = output_dir / "series"
    chunk_size = cfg["chunk_size"]
    prompt = load_prompt()
    debug_dir = cfg["debug_raw_dir"]

    # Phase 1: Prepare — detect layer-split and expand series into chunks
    # work item: (series_id, chunk_idx, num_chunks, chunk_data)
    work_items: list[tuple[str, int, int, dict[str, Any]]] = []

    for series_id in series_ids:
        sdata = series_results[series_id]

        # Layer-split heuristic (same as _process_series did)
        layer_hint = detect_layer_split(sdata.get("samples", []))
        if layer_hint.get("suspected_layer_split"):
            logger.info("  %s: layer-split suspected (confidence=%s, groups=%d, ratio=%s)",
                        series_id, layer_hint["confidence"],
                        layer_hint["heuristic_bio_sample_count"],
                        layer_hint["heuristic_split_ratio"])
            sdata = {**sdata, "layer_split_hint": layer_hint}

        chunks = split_series_into_chunks(sdata, chunk_size)
        for ci, chunk_data in enumerate(chunks):
            work_items.append((series_id, ci, len(chunks), chunk_data))

    total_chunks = len(work_items)
    chunk_counter: list[int] = [0]

    logger.info("Expanded %d series into %d chunks (chunk_size=%d, workers=%d)",
                len(series_ids), total_chunks, chunk_size, cfg["num_workers"])

    # Phase 2: Submit chunks to thread pool — each chunk = one LLM call
    # Collector: series_id -> list of (chunk_idx, result)
    chunk_results_map: dict[str, list[tuple[int, dict[str, Any]]]] = {
        sid: [] for sid in series_ids
    }
    results_lock = threading.Lock()

    def process_chunk(
        series_id: str, chunk_idx: int, num_chunks: int,
        chunk_data: dict[str, Any],
    ) -> None:
        with lock:
            chunk_counter[0] += 1
            idx = chunk_counter[0]

        n_samples = len(chunk_data.get("samples", []))
        if num_chunks > 1:
            logger.info("[%d/%d] %s chunk %d/%d (%d samples)",
                        idx, total_chunks, series_id,
                        chunk_idx + 1, num_chunks, n_samples)
        else:
            logger.info("[%d/%d] %s (%d samples)",
                        idx, total_chunks, series_id, n_samples)

        try:
            result = annotate_series_chunk(
                series_data=chunk_data,
                llm_client=client,
                model=cfg["model"],
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
                max_retries=cfg["max_retries"],
                system_prompt=prompt,
                retry_temperature_step=cfg["retry_temp_step"],
                strict_json_mode=cfg["strict_json"],
                seed=cfg["seed"],
                disable_thinking=cfg["disable_thinking"],
                debug_raw_dir=debug_dir,
                layer_split_hint=chunk_data.get("layer_split_hint"),
            )
        except Exception as exc:
            logger.error("  %s chunk %d/%d FAILED: %s",
                         series_id, chunk_idx + 1, num_chunks, exc)
            result = {"series_id": series_id, "error": str(exc)}

        with results_lock:
            chunk_results_map[series_id].append((chunk_idx, result))

    with ThreadPoolExecutor(max_workers=cfg["num_workers"]) as pool:
        futures = [pool.submit(process_chunk, *item) for item in work_items]
        for future in as_completed(futures):
            future.result()

    # Phase 3: Merge chunks per series and save
    all_rows: list[dict[str, Any]] = []

    for series_id in series_ids:
        chunk_pairs = chunk_results_map[series_id]
        chunk_pairs.sort(key=lambda x: x[0])  # maintain sample order
        ordered_results = [r for _, r in chunk_pairs]

        # If any chunk errored, the whole series is an error
        errors = [r for r in ordered_results if r.get("error")]
        if errors:
            error_msg = "; ".join(e["error"] for e in errors)
            result = {"series_id": series_id, "error": error_msg}
        elif len(ordered_results) == 1:
            result = ordered_results[0]
        else:
            result = merge_chunk_results(ordered_results, series_id)
            logger.info("  %s: merged %d chunks -> %d samples",
                        series_id, len(ordered_results), result["sample_count"])

        # Log summary
        if not result.get("error"):
            all_layers: set[str] = set()
            for s in result.get("samples", []):
                all_layers.update(s.get("measured_layers", []))
            logger.info("  %s done | layers: %s | disease: %s | tissue: %s",
                        series_id, sorted(all_layers),
                        result.get("disease_normalized", "?"),
                        result.get("tissue_normalized", "?"))

        # Save per-series
        series_subdir = series_dir / series_id
        series_subdir.mkdir(exist_ok=True)

        series_file = series_subdir / f"{slug}_result.json"
        series_payload = {
            "model": cfg["model"],
            "generated_at_utc": generated_at,
            "series_id": series_id,
            "result": result,
        }
        series_file.write_text(
            json.dumps(series_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if not result.get("error"):
            table_file = series_subdir / f"{slug}_result_table.md"
            _write_series_table(
                [result], table_file,
                cfg["model"], generated_at, str(structured_json),
            )

        logger.info("  %s saved to %s", series_id, series_subdir)
        all_rows.append(result)

    logger.info("Parallel mode: saved %d series to %s/series/", len(all_rows), output_dir)
    return all_rows


def _print_summary(rows: list[dict[str, Any]], num_workers: int, output_dir: Path, mode: str) -> None:
    ok = sum(1 for r in rows if not r.get("error"))
    failed = [r for r in rows if r.get("error")]
    print("=" * 60)
    print(f"mode      : {mode}")
    print(f"processed : {len(rows)}  ok: {ok}  errors: {len(failed)}")
    print(f"workers   : {num_workers}")
    print(f"output    : {output_dir}")
    print("=" * 60)

    if failed:
        print(f"\n{'=' * 60}")
        print("FAILED SERIES")
        print(f"{'=' * 60}")
        print(f"  {'series_id':<14} error")
        print(f"  {'-'*14} {'-'*44}")
        for r in sorted(failed, key=lambda x: x.get("series_id", "")):
            sid = r.get("series_id", "?")
            err = str(r.get("error", ""))[:120]
            print(f"  {sid:<14} {err}")

        # Save failed series IDs for later review
        failed_ids = sorted(r.get("series_id", "") for r in failed)
        failed_file = output_dir / "failed_series.txt"
        failed_file.write_text("\n".join(failed_ids) + "\n", encoding="utf-8")
        print(f"\nFailed IDs saved to {failed_file}")

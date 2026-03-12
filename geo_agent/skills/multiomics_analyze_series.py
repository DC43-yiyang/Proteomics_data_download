"""Multi-omics series annotation skill.

Annotates all samples in a GEO series with a single LLM call per series.
Large series (40+ samples) are automatically chunked into smaller LLM calls
to avoid API gateway timeouts, then results are merged.

Library usage:
    from geo_agent.skills.multiomics_analyze_series import annotate_series
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_agent.models.context import PipelineContext
from geo_agent.skills.base import Skill
from geo_agent.skills.layer_split_detector import detect_layer_split

logger = logging.getLogger(__name__)

_PROMPT_START = "<!-- SYSTEM_PROMPT_START -->"
_PROMPT_END   = "<!-- SYSTEM_PROMPT_END -->"

_DEFAULT_MODEL      = "qwen3:30b-a3b"
_DEFAULT_MAX_TOKENS = 131072

_VALID_LAYERS = {
    "RNA", "protein_surface", "chromatin", "TCR_VDJ", "BCR_VDJ",
    "cell_label", "spatial", "histone_mod", "CRISPR", "other",
}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

def load_prompt(md_path: str | Path | None = None) -> str:
    """Load series-level system prompt from the companion .md file."""
    md_file = Path(md_path) if md_path else Path(__file__).with_name("multiomics_analyze_series.md")
    if not md_file.exists():
        raise FileNotFoundError(f"Skill markdown not found: {md_file}")
    text = md_file.read_text(encoding="utf-8")
    start = text.find(_PROMPT_START)
    end   = text.find(_PROMPT_END)
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Prompt markers not found in {md_file}")
    return text[start + len(_PROMPT_START) : end].strip()


# ---------------------------------------------------------------------------
# Input builder
# ---------------------------------------------------------------------------

def build_series_input(series_data: dict[str, Any]) -> dict[str, Any]:
    """Compact LLM-input from one structured-JSON series entry."""
    series_id   = series_data.get("series_id", "")
    samples_raw = series_data.get("samples", [])

    compact_samples = []
    for sample in samples_raw:
        entry: dict[str, Any] = {
            "gsm_id": sample.get("gsm_id", ""),
            "title":  sample.get("sample_title", ""),
        }
        chars = sample.get("characteristics") or {}
        if chars:
            entry["characteristics"] = chars
        lib_type = sample.get("library_type")
        if lib_type:
            entry["library_type"] = lib_type
        for field in ("molecule", "library_source", "library_strategy", "source_name"):
            val = sample.get(field)
            if val and val not in ("OTHER", ""):
                entry[field] = val
        desc = sample.get("description", "")
        if desc:
            entry["description"] = desc[:200]
        compact_samples.append(entry)

    result: dict[str, Any] = {
        "series_id":    series_id,
        "sample_count": len(compact_samples),
    }

    # Series-level context for disease/tissue inference
    summary = series_data.get("summary", "")
    if summary:
        result["summary"] = summary[:500]
    overall_design = series_data.get("overall_design", "")
    if overall_design:
        result["overall_design"] = overall_design[:500]

    # Inject layer-split heuristic hint if present
    hint = series_data.get("layer_split_hint")
    if hint and hint.get("suspected_layer_split"):
        result["layer_split_hint"] = {
            "suspected_layer_split": True,
            "confidence": hint.get("confidence", "low"),
            "layer_keywords_found": hint.get("layer_keywords_found", []),
            "heuristic_groups": hint.get("heuristic_groups", []),
            "heuristic_bio_sample_count": hint.get("heuristic_bio_sample_count"),
        }

    result["samples"] = compact_samples
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_json_mode_rejected(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in (
        "response_format", "json_object", "unrecognized field",
        "unknown field", "invalid request", "422", "400",
    ))


def _write_raw_debug_output(debug_dir: Path, label: str, attempt: int, error: Exception, text: str) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{label}_attempt{attempt}_{ts}"
    (debug_dir / f"{base}.txt").write_text(text, encoding="utf-8")
    (debug_dir / f"{base}.meta.json").write_text(
        json.dumps({"label": label, "attempt": attempt, "error": str(error),
                    "saved_at_utc": datetime.now(timezone.utc).isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_json(text: str, label: str) -> dict[str, Any]:
    text = _THINK_RE.sub("", text).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"{label}: no JSON object in LLM output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}: invalid JSON - {exc}") from exc


def _validate(result: dict[str, Any], payload: dict[str, Any], series_id: str,
              layer_split_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    valid_gsms = {s["gsm_id"] for s in payload.get("samples", []) if s.get("gsm_id")}
    clean: list[dict[str, Any]] = []
    seen:  set[str] = set()

    for item in result.get("samples", []):
        if not isinstance(item, dict):
            continue
        gsm_id = str(item.get("gsm_id", "")).strip()
        if not gsm_id or gsm_id in seen:
            continue
        seen.add(gsm_id)

        raw_layers = item.get("measured_layers", [])
        if isinstance(raw_layers, str):
            raw_layers = [raw_layers]
        layers = [l for l in raw_layers if l in _VALID_LAYERS] or ["other"]

        try:
            conf = float(item.get("confidence", 0.9))
            conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = 0.9

        clean.append({
            "gsm_id":         gsm_id,
            "sample_title":   str(item.get("sample_title", "")).strip(),
            "measured_layers": layers,
            "platform":       str(item.get("platform", "")).strip(),
            "experiment":     str(item.get("experiment", "")).strip(),
            "assay":          str(item.get("assay", "")).strip(),
            "disease":        str(item.get("disease", "")).strip(),
            "tissue":         str(item.get("tissue", "")).strip(),
            "tissue_subtype": str(item.get("tissue_subtype", "")).strip(),
            "confidence":     conf,
            "evidence":       str(item.get("evidence", "")).strip(),
            "in_input":       gsm_id in valid_gsms,
        })

    validated = {
        "series_id":         series_id,
        "disease_normalized": str(result.get("disease_normalized", "")).strip(),
        "tissue_normalized":  str(result.get("tissue_normalized", "")).strip(),
        "sample_count":      len(clean),
        "samples":           clean,
        "reasoning":         str(result.get("reasoning", "")).strip(),
    }

    # Layer-split fields: prefer heuristic (deterministic) over LLM (unreliable arithmetic)
    if layer_split_hint and layer_split_hint.get("suspected_layer_split"):
        validated["is_layer_split"] = True
        validated["biological_sample_count"] = layer_split_hint.get("heuristic_bio_sample_count", len(clean))
        validated["layer_split_ratio"] = layer_split_hint.get("heuristic_split_ratio", "")
    else:
        is_ls = result.get("is_layer_split", False)
        if isinstance(is_ls, str):
            is_ls = is_ls.lower() in ("true", "yes", "1")
        validated["is_layer_split"] = bool(is_ls)
        validated["biological_sample_count"] = len(clean)
        validated["layer_split_ratio"] = ""

    return validated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def annotate_series_chunk(
    series_data: dict[str, Any],
    llm_client: Any,
    model: str,
    temperature: float,
    max_tokens: int,
    max_retries: int,
    system_prompt: str,
    retry_temperature_step: float,
    strict_json_mode: bool,
    seed: int | None,
    disable_thinking: bool,
    debug_raw_dir: Path | None,
    layer_split_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single LLM call to annotate one (possibly chunked) series payload."""
    series_id      = series_data.get("series_id", "unknown")
    payload        = build_series_input(series_data)
    user_content   = json.dumps(payload, ensure_ascii=False)
    last_exc: Exception | None = None
    use_strict     = strict_json_mode

    # Dynamic max_tokens: ~150 tokens per sample + 512 overhead
    sample_count = len(payload.get("samples", []))
    min_tokens = 512 + sample_count * 150
    if min_tokens > max_tokens:
        logger.info("%s: bumping max_tokens %d -> %d for %d samples",
                    series_id, max_tokens, min_tokens, sample_count)
        max_tokens = min_tokens

    for attempt in range(1 + max_retries):
        attempt_temp = min(temperature + attempt * retry_temperature_step, 0.5)
        try:
            response = llm_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=attempt_temp,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                response_format={"type": "json_object"} if use_strict else None,
                seed=seed,
                think=False if disable_thinking else None,
            )
        except Exception as exc:
            if use_strict and _is_json_mode_rejected(exc):
                logger.warning("%s: JSON mode rejected, falling back: %s", series_id, exc)
                use_strict = False
                last_exc = exc
                continue
            raise RuntimeError(f"LLM call failed for {series_id}: {exc}") from exc

        raw_text = response.choices[0].message.content
        try:
            parsed = _parse_json(raw_text, series_id)
            result = _validate(parsed, payload, series_id, layer_split_hint)
        except (ValueError, KeyError) as exc:
            last_exc = exc
            if debug_raw_dir:
                _write_raw_debug_output(debug_raw_dir, series_id, attempt + 1, exc, raw_text)
            if attempt < max_retries:
                logger.warning("%s: parse/validate failed (attempt %d/%d): %s - retrying",
                               series_id, attempt + 1, 1 + max_retries, exc)
            continue

        return result

    raise RuntimeError(
        f"Could not parse LLM output after {1 + max_retries} attempts for {series_id}: {last_exc}"
    )


def merge_chunk_results(chunks: list[dict[str, Any]], series_id: str) -> dict[str, Any]:
    """Merge results from multiple chunk LLM calls into a single series result."""
    if len(chunks) == 1:
        return chunks[0]

    # Series-level fields from first chunk (all chunks see the same summary/overall_design)
    merged = {
        "series_id":          series_id,
        "disease_normalized": chunks[0].get("disease_normalized", ""),
        "tissue_normalized":  chunks[0].get("tissue_normalized", ""),
        "is_layer_split":     chunks[0].get("is_layer_split", False),
        "biological_sample_count": chunks[0].get("biological_sample_count", 0),
        "layer_split_ratio":  chunks[0].get("layer_split_ratio", ""),
    }

    # Concatenate samples, deduplicate by gsm_id
    all_samples: list[dict[str, Any]] = []
    seen_gsms: set[str] = set()
    for chunk in chunks:
        for sample in chunk.get("samples", []):
            gsm_id = sample.get("gsm_id", "")
            if gsm_id and gsm_id not in seen_gsms:
                seen_gsms.add(gsm_id)
                all_samples.append(sample)

    merged["samples"] = all_samples
    merged["sample_count"] = len(all_samples)

    # Join reasoning from all chunks
    reasonings = [c.get("reasoning", "") for c in chunks if c.get("reasoning")]
    merged["reasoning"] = " | ".join(reasonings)

    return merged


def split_series_into_chunks(
    series_data: dict[str, Any],
    chunk_size: int = 15,
) -> list[dict[str, Any]]:
    """Split a series into chunk-sized sub-series dicts.

    Returns a list of series_data dicts, each with a subset of samples
    but the same series-level context (summary, overall_design, layer_split_hint).
    If no chunking needed, returns [series_data] unchanged.
    """
    samples = series_data.get("samples", [])
    n = len(samples)

    if chunk_size <= 0 or n <= chunk_size:
        return [series_data]

    num_chunks = math.ceil(n / chunk_size)
    base, extra = divmod(n, num_chunks)
    chunk_sizes = [base + (1 if i < extra else 0) for i in range(num_chunks)]

    chunks = []
    offset = 0
    for cs in chunk_sizes:
        chunks.append({**series_data, "samples": samples[offset:offset + cs]})
        offset += cs
    return chunks


def annotate_series(
    series_data: dict[str, Any],
    llm_client: Any,
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.0,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    max_retries: int = 2,
    system_prompt: str | None = None,
    retry_temperature_step: float = 0.0,
    strict_json_mode: bool = True,
    seed: int | None = None,
    disable_thinking: bool = False,
    debug_raw_dir: str | Path | None = None,
    chunk_size: int = 15,
) -> dict[str, Any]:
    """Annotate all samples in one series, chunking if needed.

    When a series has more samples than *chunk_size*, the samples are split
    into chunks of *chunk_size* and each chunk is sent as a separate LLM call.
    Results are merged transparently so the caller sees a single result dict.

    Args:
        chunk_size: Max samples per LLM call. 0 disables chunking.

    Returns a dict with keys:
      series_id, disease_normalized, tissue_normalized, sample_count, samples, reasoning
    """
    series_id      = series_data.get("series_id", "unknown")
    prompt         = system_prompt if system_prompt else load_prompt()
    debug_dir_path = Path(debug_raw_dir) if debug_raw_dir else None
    samples        = series_data.get("samples", [])
    hint           = series_data.get("layer_split_hint")

    # Decide whether to chunk
    need_chunking = chunk_size > 0 and len(samples) > chunk_size

    if not need_chunking:
        return annotate_series_chunk(
            series_data=series_data,
            llm_client=llm_client,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            system_prompt=prompt,
            retry_temperature_step=retry_temperature_step,
            strict_json_mode=strict_json_mode,
            seed=seed,
            disable_thinking=disable_thinking,
            debug_raw_dir=debug_dir_path,
            layer_split_hint=hint,
        )

    # --- Chunked path (even distribution) ---
    n = len(samples)
    num_chunks = math.ceil(n / chunk_size)
    # Distribute evenly: e.g. 46 samples / 3 chunks → 16, 15, 15
    base, extra = divmod(n, num_chunks)
    # First `extra` chunks get (base+1) samples, the rest get `base`
    chunk_sizes = [base + (1 if i < extra else 0) for i in range(num_chunks)]
    logger.info("%s: splitting %d samples into %d chunks (%s)",
                series_id, n, num_chunks,
                "+".join(str(s) for s in chunk_sizes))

    chunk_results: list[dict[str, Any]] = []
    offset = 0
    for i, cs in enumerate(chunk_sizes):
        start = offset
        end   = offset + cs
        offset = end
        chunk_samples = samples[start:end]

        logger.info("%s: chunk %d/%d (samples %d-%d)",
                    series_id, i + 1, num_chunks, start + 1, end)

        # Build a modified series_data with only this chunk's samples
        # but the same series-level context (summary, overall_design, layer_split_hint)
        chunk_data = {**series_data, "samples": chunk_samples}

        chunk_result = annotate_series_chunk(
            series_data=chunk_data,
            llm_client=llm_client,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            system_prompt=prompt,
            retry_temperature_step=retry_temperature_step,
            strict_json_mode=strict_json_mode,
            seed=seed,
            disable_thinking=disable_thinking,
            debug_raw_dir=debug_dir_path,
            layer_split_hint=hint,
        )
        chunk_results.append(chunk_result)

    merged = merge_chunk_results(chunk_results, series_id)
    logger.info("%s: merged %d chunks -> %d samples",
                series_id, num_chunks, merged["sample_count"])
    return merged


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------

class MultiomicsSeriesAnalyzerSkill(Skill):
    """Annotate all samples in a series with a single LLM call per series."""

    def __init__(
        self,
        llm_client: Any,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.0,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        max_retries: int = 2,
        system_prompt: str | None = None,
        retry_temperature_step: float = 0.0,
        strict_json_mode: bool = True,
        seed: int | None = None,
        disable_thinking: bool = False,
        debug_raw_dir: str | Path | None = None,
    ):
        self._llm_client           = llm_client
        self._model                = model
        self._temperature          = temperature
        self._max_tokens           = max_tokens
        self._max_retries          = max_retries
        self._system_prompt        = system_prompt
        self._retry_temperature_step = retry_temperature_step
        self._strict_json_mode     = strict_json_mode
        self._seed                 = seed
        self._disable_thinking     = disable_thinking
        self._debug_raw_dir        = debug_raw_dir

    @property
    def name(self) -> str:
        return "multiomics_series_analyzer"

    def execute(self, context: PipelineContext) -> PipelineContext:
        if not context.family_soft_structured:
            logger.warning("No family_soft_structured data to annotate")
            return context

        # Build lookup for series-level context (summary, overall_design)
        # from GEODataset objects — family_soft_structured doesn't have these.
        series_context: dict[str, dict[str, str]] = {}
        for ds in context.datasets:
            series_context[ds.accession] = {
                "summary": ds.summary or "",
                "overall_design": ds.overall_design or "",
            }

        series_ids = (context.target_series_ids
                      if context.target_series_ids
                      else sorted(context.family_soft_structured.keys()))
        results: dict[str, dict[str, Any]] = {}

        for series_id in series_ids:
            series_data = context.family_soft_structured.get(series_id)
            if not isinstance(series_data, dict):
                context.errors.append(f"{series_id}: missing structured series data")
                continue

            # Inject series-level context for disease/tissue inference
            enriched = {**series_data, **series_context.get(series_id, {})}

            # Run layer-split heuristic
            hint = detect_layer_split(enriched.get("samples", []))
            if hint.get("suspected_layer_split"):
                enriched["layer_split_hint"] = hint

            try:
                results[series_id] = annotate_series(
                    series_data=enriched,
                    llm_client=self._llm_client,
                    model=self._model,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    max_retries=self._max_retries,
                    system_prompt=self._system_prompt,
                    retry_temperature_step=self._retry_temperature_step,
                    strict_json_mode=self._strict_json_mode,
                    seed=self._seed,
                    disable_thinking=self._disable_thinking,
                    debug_raw_dir=self._debug_raw_dir,
                )
            except Exception as exc:
                context.errors.append(f"{series_id}: {exc}")
                results[series_id] = {"series_id": series_id, "error": str(exc)}

        context.multiomics_annotations = results

        # Persist to DB if available
        if context.db is not None and context.pipeline_run_id is not None:
            run_id = context.pipeline_run_id
            for series_id, result in results.items():
                if result.get("error"):
                    continue
                context.db.save_series_annotation(
                    series_id, run_id, self._model, result,
                )
                context.db.save_sample_annotations_batch(
                    series_id, run_id, self._model,
                    result.get("samples", []),
                )
            logger.info("Persisted series annotations to database")

        return context

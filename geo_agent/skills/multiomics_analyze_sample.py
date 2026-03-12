"""Multi-omics sample annotation skill.

Annotates each GSM sample with an individual LLM call per sample.

Library usage:
    from geo_agent.skills.multiomics_analyze_sample import annotate_sample
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_agent.models.context import PipelineContext
from geo_agent.skills.base import Skill

logger = logging.getLogger(__name__)

_PROMPT_START = "<!-- SAMPLE_PROMPT_START -->"
_PROMPT_END   = "<!-- SAMPLE_PROMPT_END -->"

_DEFAULT_MODEL      = "qwen3:30b-a3b"
_DEFAULT_MAX_TOKENS = 16384

_VALID_LAYERS = {
    "RNA", "protein_surface", "chromatin", "TCR_VDJ", "BCR_VDJ",
    "cell_label", "spatial", "histone_mod", "CRISPR", "other",
}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

def load_prompt(md_path: str | Path | None = None) -> str:
    """Load per-sample system prompt from the companion .md file."""
    md_file = Path(md_path) if md_path else Path(__file__).with_name("multiomics_analyze_sample.md")
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

def build_sample_input(series_data: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    """Compact LLM-input for a single GSM sample with series context (no field_inventory)."""
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

    result: dict[str, Any] = {
        "series_id":    series_data.get("series_id", ""),
        "sample_count": series_data.get("sample_count", 0),
    }

    # Series-level context for disease/tissue inference
    summary = series_data.get("summary", "")
    if summary:
        result["summary"] = summary[:500]
    overall_design = series_data.get("overall_design", "")
    if overall_design:
        result["overall_design"] = overall_design[:500]

    result["sample"] = entry
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


def _validate_sample(result: dict[str, Any], sample: dict[str, Any], series_id: str) -> dict[str, Any]:
    gsm_id = sample.get("gsm_id", "")

    raw_layers = result.get("measured_layers", [])
    if isinstance(raw_layers, str):
        raw_layers = [raw_layers]
    layers = [l for l in raw_layers if l in _VALID_LAYERS] or ["other"]

    try:
        conf = float(result.get("confidence", 0.9))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.9

    return {
        "series_id":      series_id,
        "gsm_id":         gsm_id,
        "sample_title":   str(result.get("sample_title", sample.get("sample_title", ""))).strip(),
        "measured_layers": layers,
        "platform":       str(result.get("platform", "")).strip(),
        "experiment":     str(result.get("experiment", "")).strip(),
        "assay":          str(result.get("assay", "")).strip(),
        "disease":        str(result.get("disease", "")).strip(),
        "tissue":         str(result.get("tissue", "")).strip(),
        "tissue_subtype": str(result.get("tissue_subtype", "")).strip(),
        "confidence":     conf,
        "evidence":       str(result.get("evidence", "")).strip(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def annotate_sample(
    series_data: dict[str, Any],
    sample: dict[str, Any],
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
) -> dict[str, Any]:
    """Annotate a single GSM sample within a series.

    Returns a flat dict with keys:
      series_id, gsm_id, sample_title, measured_layers, platform, experiment,
      assay, disease, tissue, tissue_subtype, confidence, evidence
    """
    series_id      = series_data.get("series_id", "unknown")
    gsm_id         = sample.get("gsm_id", "unknown")
    prompt         = system_prompt if system_prompt else load_prompt()
    payload        = build_sample_input(series_data, sample)
    user_content   = json.dumps(payload, ensure_ascii=False)
    last_exc: Exception | None = None
    use_strict     = strict_json_mode
    debug_dir_path = Path(debug_raw_dir) if debug_raw_dir else None

    for attempt in range(1 + max_retries):
        attempt_temp = min(temperature + attempt * retry_temperature_step, 0.5)
        try:
            response = llm_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=attempt_temp,
                system=prompt,
                messages=[{"role": "user", "content": user_content}],
                response_format={"type": "json_object"} if use_strict else None,
                seed=seed,
                think=False if disable_thinking else None,
            )
        except Exception as exc:
            if use_strict and _is_json_mode_rejected(exc):
                logger.warning("%s/%s: JSON mode rejected, falling back: %s", series_id, gsm_id, exc)
                use_strict = False
                last_exc = exc
                continue
            raise RuntimeError(f"LLM call failed for {gsm_id}: {exc}") from exc

        raw_text = response.choices[0].message.content
        try:
            parsed = _parse_json(raw_text, gsm_id)
            result = _validate_sample(parsed, sample, series_id)
        except (ValueError, KeyError) as exc:
            last_exc = exc
            if debug_dir_path:
                _write_raw_debug_output(debug_dir_path, gsm_id, attempt + 1, exc, raw_text)
            if attempt < max_retries:
                logger.warning("%s/%s: parse/validate failed (attempt %d/%d): %s - retrying",
                               series_id, gsm_id, attempt + 1, 1 + max_retries, exc)
            continue

        return result

    raise RuntimeError(
        f"Could not parse LLM output after {1 + max_retries} attempts for {gsm_id}: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------

class MultiomicsSampleAnalyzerSkill(Skill):
    """Annotate each GSM sample with an individual LLM call (one call per sample)."""

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
        self._llm_client             = llm_client
        self._model                  = model
        self._temperature            = temperature
        self._max_tokens             = max_tokens
        self._max_retries            = max_retries
        self._system_prompt          = system_prompt
        self._retry_temperature_step = retry_temperature_step
        self._strict_json_mode       = strict_json_mode
        self._seed                   = seed
        self._disable_thinking       = disable_thinking
        self._debug_raw_dir          = debug_raw_dir

    @property
    def name(self) -> str:
        return "multiomics_sample_analyzer"

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

            sample_results: list[dict[str, Any]] = []
            for sample in series_data.get("samples", []):
                gsm_id = sample.get("gsm_id", "unknown")
                try:
                    sample_results.append(annotate_sample(
                        series_data=enriched,
                        sample=sample,
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
                    ))
                except Exception as exc:
                    context.errors.append(f"{series_id}/{gsm_id}: {exc}")
                    sample_results.append({"series_id": series_id, "gsm_id": gsm_id, "error": str(exc)})

            results[series_id] = {
                "series_id":    series_id,
                "sample_count": len(sample_results),
                "samples":      sample_results,
            }

            # Persist to DB if available
            if context.db is not None and context.pipeline_run_id is not None:
                context.db.save_sample_annotations_batch(
                    series_id, context.pipeline_run_id,
                    self._model, sample_results,
                )
                logger.info("Persisted %d sample annotations for %s to database",
                            len(sample_results), series_id)

        context.multiomics_annotations = results
        return context

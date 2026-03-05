#!/usr/bin/env python3
"""Multi-omics sample annotation skill.

This module supports both:
1) library usage via annotate_series(...)
2) executable usage via:
   python -m geo_agent.skills.multiomics_analyzer --input <structured.json>
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_agent.llm.ollama_client import OllamaClient
from geo_agent.models.context import PipelineContext
from geo_agent.skills.base import Skill

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_START = "<!-- SYSTEM_PROMPT_START -->"
_SYSTEM_PROMPT_END = "<!-- SYSTEM_PROMPT_END -->"
_DEFAULT_MODEL = "qwen3:30b-a3b"
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
_DEFAULT_MAX_TOKENS = 16384

# ---------------------------------------------------------------------------
# Valid measured_layers
# ---------------------------------------------------------------------------

_VALID_LAYERS = {
    "RNA",
    "protein_surface",
    "chromatin",
    "TCR_VDJ",
    "BCR_VDJ",
    "cell_label",
    "spatial",
    "histone_mod",
    "CRISPR",
    "other",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_series_input(series_data: dict[str, Any]) -> dict[str, Any]:
    """Compact LLM-input from one structured-JSON series entry."""
    series_id = series_data.get("series_id", "")
    samples_raw = series_data.get("samples", [])

    compact_samples = []
    for sample in samples_raw:
        entry: dict[str, Any] = {
            "gsm_id": sample.get("gsm_id", ""),
            "title": sample.get("sample_title", ""),
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

    return {
        "series_id": series_id,
        "sample_count": len(compact_samples),
        "samples": compact_samples,
    }


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
) -> dict[str, Any]:
    """Annotate all samples in one series.

    Returns a dict with keys:
      series_id, disease_normalized, tissue_normalized, samples, reasoning
    Each sample dict contains:
      gsm_id, sample_title, measured_layers, platform, assay,
      disease, tissue, tissue_subtype, confidence, evidence
    """
    series_id = series_data.get("series_id", "unknown")
    prompt = system_prompt if system_prompt else load_system_prompt()
    payload = build_series_input(series_data)
    user_content = json.dumps(payload, ensure_ascii=False)

    last_exc: Exception | None = None
    use_strict_json_mode = strict_json_mode
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
                response_format={"type": "json_object"} if use_strict_json_mode else None,
                seed=seed,
                think=False if disable_thinking else None,
            )
        except Exception as exc:
            if use_strict_json_mode and _is_json_mode_rejected(exc):
                logger.warning(
                    "%s: JSON mode rejected by Ollama, falling back to legacy mode: %s",
                    series_id,
                    exc,
                )
                use_strict_json_mode = False
                last_exc = exc
                continue
            raise RuntimeError(f"LLM call failed for {series_id}: {exc}") from exc

        raw_text = response.choices[0].message.content
        try:
            parsed = _parse_json(raw_text, series_id)
            result = _validate(parsed, payload, series_id)
        except (ValueError, KeyError) as exc:
            last_exc = exc
            if debug_dir_path:
                _write_raw_debug_output(
                    debug_dir=debug_dir_path,
                    series_id=series_id,
                    attempt=attempt + 1,
                    error=exc,
                    text=raw_text,
                )
            if attempt < max_retries:
                logger.warning(
                    "%s: parse/validate failed (attempt %d/%d): %s - retrying",
                    series_id,
                    attempt + 1,
                    1 + max_retries,
                    exc,
                )
            continue

        return result

    raise RuntimeError(
        f"Could not parse LLM output after {1 + max_retries} attempts "
        f"for {series_id}: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _is_json_mode_rejected(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "response_format" in msg
        or "json_object" in msg
        or "unrecognized field" in msg
        or "unknown field" in msg
        or "invalid request" in msg
        or "422" in msg
        or "400" in msg
    )


def _write_raw_debug_output(
    debug_dir: Path,
    series_id: str,
    attempt: int,
    error: Exception,
    text: str,
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{series_id}_attempt{attempt}_{ts}"
    raw_file = debug_dir / f"{base}.txt"
    meta_file = debug_dir / f"{base}.meta.json"
    raw_file.write_text(text, encoding="utf-8")
    meta_file.write_text(
        json.dumps(
            {
                "series_id": series_id,
                "attempt": attempt,
                "error": str(error),
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                "raw_file": str(raw_file),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_system_prompt(md_path: str | Path | None = None) -> str:
    """Load system prompt from the companion markdown skill file."""
    if md_path is None:
        md_file = Path(__file__).with_suffix(".md")
    else:
        md_file = Path(md_path)

    if not md_file.exists():
        raise FileNotFoundError(f"Skill markdown not found: {md_file}")

    text = md_file.read_text(encoding="utf-8")
    start = text.find(_SYSTEM_PROMPT_START)
    end = text.find(_SYSTEM_PROMPT_END)
    if start == -1 or end == -1 or end <= start:
        raise ValueError(
            f"System prompt markers not found in {md_file}. "
            f"Expected {_SYSTEM_PROMPT_START} ... {_SYSTEM_PROMPT_END}"
        )

    return text[start + len(_SYSTEM_PROMPT_START) : end].strip()


def _parse_json(text: str, series_id: str) -> dict[str, Any]:
    text = _THINK_RE.sub("", text).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"{series_id}: no JSON object in LLM output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{series_id}: invalid JSON - {exc}") from exc


def _validate(result: dict[str, Any], payload: dict[str, Any], series_id: str) -> dict[str, Any]:
    valid_gsms = {sample["gsm_id"] for sample in payload.get("samples", []) if sample.get("gsm_id")}

    clean: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in result.get("samples", []):
        if not isinstance(item, dict):
            continue
        gsm_id = str(item.get("gsm_id", "")).strip()
        if not gsm_id or gsm_id in seen:
            continue
        seen.add(gsm_id)

        # measured_layers: keep only valid strings
        raw_layers = item.get("measured_layers", [])
        if isinstance(raw_layers, str):
            raw_layers = [raw_layers]
        layers = [layer for layer in raw_layers if layer in _VALID_LAYERS] or ["other"]

        try:
            conf = float(item.get("confidence", 0.9))
            conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = 0.9

        clean.append(
            {
                "gsm_id": gsm_id,
                "sample_title": str(item.get("sample_title", "")).strip(),
                "measured_layers": layers,
                "platform": str(item.get("platform", "")).strip(),
                "experiment": str(item.get("experiment", "")).strip(),
                "assay": str(item.get("assay", "")).strip(),
                "disease": str(item.get("disease", "")).strip(),
                "tissue": str(item.get("tissue", "")).strip(),
                "tissue_subtype": str(item.get("tissue_subtype", "")).strip(),
                "confidence": conf,
                "evidence": str(item.get("evidence", "")).strip(),
                "in_input": gsm_id in valid_gsms,
            }
        )

    return {
        "series_id": series_id,
        "disease_normalized": str(result.get("disease_normalized", "")).strip(),
        "tissue_normalized": str(result.get("tissue_normalized", "")).strip(),
        "sample_count": len(clean),
        "samples": clean,
        "reasoning": str(result.get("reasoning", "")).strip(),
    }


class MultiomicsAnalyzerSkill(Skill):
    """Annotate Family SOFT structured samples with multi-omics labels."""

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
        self._llm_client = llm_client
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._system_prompt = system_prompt
        self._retry_temperature_step = retry_temperature_step
        self._strict_json_mode = strict_json_mode
        self._seed = seed
        self._disable_thinking = disable_thinking
        self._debug_raw_dir = debug_raw_dir

    @property
    def name(self) -> str:
        return "multiomics_analyzer"

    def execute(self, context: PipelineContext) -> PipelineContext:
        if not context.family_soft_structured:
            logger.warning("No family_soft_structured data to annotate")
            return context

        series_ids = context.target_series_ids if context.target_series_ids else sorted(context.family_soft_structured.keys())
        results: dict[str, dict[str, Any]] = {}

        for series_id in series_ids:
            series_data = context.family_soft_structured.get(series_id)
            if not isinstance(series_data, dict):
                context.errors.append(f"{series_id}: missing structured series data")
                continue
            try:
                results[series_id] = annotate_series(
                    series_data=series_data,
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
        return context


def _md_escape(v: Any) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def _layers_cell(layers: list[str]) -> str:
    return ", ".join(layers) if layers else "-"


def _write_markdown_table(
    rows: list[dict[str, Any]],
    output_path: Path,
    model: str,
    generated_at: str,
    input_path: Path,
) -> None:
    lines: list[str] = [
        "# Multi-omics Annotation Results",
        "",
        f"- model: `{model}`",
        f"- generated_at_utc: `{generated_at}`",
        f"- input: `{input_path}`",
        "",
        "## Series Summary",
        "",
        "| series_id | disease | tissue | samples | layers_present | status |",
        "|---|---|---|---:|---|---|",
    ]

    for row in rows:
        if row.get("error"):
            lines.append(
                f"| {row['series_id']} | - | - | - | - | ERROR: {_md_escape(row['error'])} |"
            )
            continue

        all_layers: set[str] = set()
        for sample in row.get("samples", []):
            all_layers.update(sample.get("measured_layers", []))

        lines.append(
            "| "
            + " | ".join(
                [
                    _md_escape(row["series_id"]),
                    _md_escape(row.get("disease_normalized", "-")),
                    _md_escape(row.get("tissue_normalized", "-")),
                    str(row.get("sample_count", 0)),
                    _md_escape(", ".join(sorted(all_layers))),
                    "ok",
                ]
            )
            + " |"
        )

    lines += [
        "",
        "---",
        "",
        "## Per-sample Annotations",
        "",
        "| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |",
        "|---|---|---|---|---|---|---|---|---|---|---:|---|",
    ]

    for row in rows:
        if row.get("error"):
            continue
        sid = row["series_id"]
        for sample in row.get("samples", []):
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_escape(sid),
                        _md_escape(sample.get("gsm_id", "")),
                        _md_escape(sample.get("sample_title", "")),
                        _md_escape(_layers_cell(sample.get("measured_layers", []))),
                        _md_escape(sample.get("platform", "")),
                        _md_escape(sample.get("experiment", "")),
                        _md_escape(sample.get("assay", "")),
                        _md_escape(sample.get("disease", "")),
                        _md_escape(sample.get("tissue", "")),
                        _md_escape(sample.get("tissue_subtype", "")),
                        f"{sample.get('confidence', 0):.2f}",
                        _md_escape(sample.get("evidence", "")),
                    ]
                )
                + " |"
            )

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Annotate multi-omics labels from structured Family SOFT JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to structured JSON file.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("multiomics_results.json"),
        help="Output JSON path.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("multiomics_results_table.md"),
        help="Output markdown summary path.",
    )
    parser.add_argument(
        "--series",
        nargs="*",
        default=[],
        help="Optional series IDs (GSE...) to process. Defaults to all.",
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Ollama model name (default: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=_DEFAULT_OLLAMA_BASE_URL,
        help=f"Ollama base URL (default: {_DEFAULT_OLLAMA_BASE_URL})",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retries on parse/validation failures per series.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Base temperature per request (default: 0.0).",
    )
    parser.add_argument(
        "--retry-temperature-step",
        type=float,
        default=0.0,
        help="Added temperature per retry attempt (default: 0.0).",
    )
    parser.add_argument(
        "--strict-json-mode",
        action="store_true",
        default=True,
        help="Use response_format=json_object (default: enabled).",
    )
    parser.add_argument(
        "--no-strict-json-mode",
        action="store_false",
        dest="strict_json_mode",
        help="Disable response_format=json_object and use legacy free-form output.",
    )
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        default=False,
        help="Send think=false if the Ollama endpoint supports it.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional deterministic seed.",
    )
    parser.add_argument(
        "--debug-raw-dir",
        type=Path,
        default=None,
        help="Directory to save raw LLM output when parse/validate fails.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    args = _parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Input not found: {args.input}")

    client = OllamaClient(base_url=args.ollama_base_url)
    if not client.health_check():
        raise RuntimeError(f"Ollama not reachable at {args.ollama_base_url}")

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("series_results"), dict):
        series_results = raw["series_results"]
    elif isinstance(raw, dict) and raw.get("series_id") and raw.get("samples"):
        series_id = str(raw["series_id"])
        series_results = {series_id: raw}
    else:
        raise ValueError("Unsupported input JSON format. Expected series_results or one series object.")

    series_ids = args.series if args.series else sorted(series_results.keys())
    generated_at = datetime.now(timezone.utc).isoformat()

    rows: list[dict[str, Any]] = []
    for series_id in series_ids:
        series_data = series_results.get(series_id)
        if not isinstance(series_data, dict):
            rows.append({"series_id": series_id, "error": "series not in input"})
            continue
        try:
            result = annotate_series(
                series_data=series_data,
                llm_client=client,
                model=args.model,
                temperature=args.temperature,
                max_retries=args.max_retries,
                retry_temperature_step=args.retry_temperature_step,
                strict_json_mode=args.strict_json_mode,
                seed=args.seed,
                disable_thinking=args.disable_thinking,
                debug_raw_dir=args.debug_raw_dir,
            )
        except Exception as exc:
            result = {"series_id": series_id, "error": str(exc)}
        rows.append(result)

    payload = {
        "model": args.model,
        "generated_at_utc": generated_at,
        "input_file": str(args.input),
        "series_count": len(rows),
        "results": {row["series_id"]: row for row in rows},
    }
    args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_markdown_table(
        rows=rows,
        output_path=args.output_md,
        model=args.model,
        generated_at=generated_at,
        input_path=args.input,
    )

    ok = sum(1 for row in rows if not row.get("error"))
    print(f"processed={len(rows)} ok={ok} errors={len(rows) - ok}")
    print(f"json={args.output_json}")
    print(f"markdown={args.output_md}")


if __name__ == "__main__":
    main()

import json
import logging
import re
from typing import Any

from geo_agent.models.context import PipelineContext
from geo_agent.models.sample import GEOSample, SampleSelection
from geo_agent.ncbi.parsers import parse_family_soft
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)

VALID_LIBRARY_TYPES = {"GEX", "ADT", "TCR", "BCR", "HTO", "ATAC", "OTHER"}

_SYSTEM_PROMPT = """\
You classify GEO GSM samples into library types.

Return strict JSON array (no markdown), each item:
{
  "accession": "GSMxxxx",
  "library_type": "GEX|ADT|TCR|BCR|HTO|ATAC|OTHER",
  "confidence": 0.0-1.0,
  "reasoning": "short reason"
}
"""


class StandaloneSampleSelectorSkill(Skill):
    """Classify GSM library types for standalone GEO series only."""

    def __init__(
        self,
        ncbi_client: Any,
        llm_client: Any,
        model: str = "claude-haiku-4-5-20251001",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        confidence_threshold: float = 0.7,
    ):
        self._ncbi_client = ncbi_client
        self._llm_client = llm_client
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._confidence_threshold = confidence_threshold

    @property
    def name(self) -> str:
        return "standalone_sample_selector"

    def execute(self, context: PipelineContext) -> PipelineContext:
        accessions = self._resolve_series_accessions(context)
        if not accessions:
            return context

        soft_texts = self._ncbi_client.fetch_family_soft_batch(accessions)
        target_types = _normalize_target_types(context.target_library_types)

        for accession in accessions:
            soft_text = soft_texts.get(accession, "")
            if not soft_text:
                context.errors.append(f"{accession}: empty Family SOFT response")
                continue

            try:
                samples = parse_family_soft(soft_text)
            except Exception as exc:  # pragma: no cover
                context.errors.append(f"{accession}: failed to parse Family SOFT: {exc}")
                continue

            context.sample_metadata[accession] = samples

            try:
                selected = self._classify_and_select(samples=samples, target_types=target_types)
            except SkillError as exc:
                context.errors.append(f"{accession}: {exc}")
                continue

            context.selected_samples[accession] = selected

        return context

    def _resolve_series_accessions(self, context: PipelineContext) -> list[str]:
        if context.series_hierarchy:
            standalone = sorted(
                acc
                for acc, node in context.series_hierarchy.items()
                if getattr(node, "role", "") == "standalone" and getattr(node, "in_search_results", False)
            )
            if standalone:
                return standalone
            logger.warning("No standalone series found in hierarchy")
            return []

        datasets = context.filtered_datasets or context.datasets
        if not datasets:
            logger.warning("No datasets to run standalone sample selector")
            return []
        return sorted({ds.accession for ds in datasets if ds.accession})

    def _classify_and_select(
        self,
        samples: list[GEOSample],
        target_types: set[str],
    ) -> list[SampleSelection]:
        sample_lookup = {s.accession: s for s in samples}
        llm_rows = self._classify_with_llm(samples=samples)

        selected: list[SampleSelection] = []
        for row in llm_rows:
            accession = str(row.get("accession", "")).strip()
            if not accession or accession not in sample_lookup:
                continue

            library_type_raw = str(row.get("library_type", "")).strip()
            library_type, forced_other = _normalize_library_type(library_type_raw)
            if library_type not in target_types:
                continue

            confidence = _clamp_confidence(row.get("confidence", 0.0))
            reasoning = str(row.get("reasoning", "")).strip()
            needs_review = forced_other or confidence < self._confidence_threshold

            selected.append(
                SampleSelection(
                    accession=accession,
                    library_type=library_type,
                    confidence=confidence,
                    reasoning=reasoning,
                    needs_review=needs_review,
                    supplementary_files=sample_lookup[accession].supplementary_files,
                )
            )

        return selected

    def _classify_with_llm(self, samples: list[GEOSample]) -> list[dict[str, Any]]:
        sample_payload = [
            {
                "accession": s.accession,
                "title": s.title,
                "molecule": s.molecule,
                "library_source": s.library_source,
                "characteristics": s.characteristics,
                "description": s.description,
                "supplementary_files": s.supplementary_files,
            }
            for s in samples
        ]
        payload = {"samples": sample_payload}

        try:
            response = self._llm_client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(payload, separators=(",", ":"))}],
            )
            text = response.content[0].text
        except Exception as exc:
            raise SkillError(f"LLM call failed: {exc}") from exc

        return _parse_llm_json_list(text)


def _parse_llm_json_list(raw_text: str) -> list[dict[str, Any]]:
    text = (raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SkillError(f"LLM returned invalid JSON: {exc}") from exc

    if isinstance(parsed, dict):
        if isinstance(parsed.get("samples"), list):
            parsed = parsed["samples"]
        else:
            raise SkillError("LLM JSON must be a list of sample classification objects")

    if not isinstance(parsed, list):
        raise SkillError("LLM JSON must be a list")

    rows: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _normalize_target_types(target_types: list[str] | None) -> set[str]:
    values = target_types or ["GEX"]
    normalized = {_normalize_library_type(v)[0] for v in values}
    return {v for v in normalized if v in VALID_LIBRARY_TYPES} or {"GEX"}


def _normalize_library_type(library_type: str) -> tuple[str, bool]:
    value = (library_type or "").strip().upper()
    aliases = {
        "RNA": "GEX",
        "MRNA": "GEX",
        "SCRNA": "GEX",
        "SCRNA-SEQ": "GEX",
        "SURFACE": "ADT",
        "ABSEQ": "ADT",
        "VDJ": "TCR",
    }
    value = aliases.get(value, value)
    if value in VALID_LIBRARY_TYPES:
        return value, False
    return "OTHER", True


def _clamp_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value

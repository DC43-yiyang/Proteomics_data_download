import json
import logging
import re
from pathlib import Path
from typing import Any

from geo_agent.models.context import PipelineContext
from geo_agent.models.sample import GEOSample
from geo_agent.ncbi.client import NCBIClient
from geo_agent.ncbi.parsers import parse_family_soft
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)

_CORE_CHARACTERISTICS = {
    "library type",
    "cell type",
    "tissue",
    "sample type",
    "disease",
    "disease state",
    "time point",
    "batch",
    "condition",
    "treatment",
}

VALID_DOWNLOAD_STRATEGIES = {
    "GSM_Level_Separated",
    "GSE_Level_Bundled",
    "Integrated_Object",
    "None",
}

_INTEGRATED_KEYWORDS = (
    "integrated",
    "multiome",
    ".h5ad",
    ".rds",
    "raw_feature_bc_matrix",
    ".h5",
)

_QUERY_STOPWORDS = {
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

SELECTOR_SYSTEM_PROMPT = """\
You are an expert Bioinformatics Data Curator and an AI module for GEO sample selection.

Task:
- Read the provided JSON metadata for one GSE series.
- Read `user_query` and infer what sample type the user wants.
- Select only samples that match the user query using sample-level evidence.
- Diagnose data locus and output strict JSON.

Output schema (strict JSON object, no markdown):
{
  "is_false_positive": boolean,
  "download_strategy": "GSM_Level_Separated" | "GSE_Level_Bundled" | "Integrated_Object" | "None",
  "selected_samples": [
    {
      "gsm_id": "GSMXXXXXXX",
      "sample_title": "Original title",
      "selection_label": "short label of why this sample matches query"
    }
  ],
  "reasoning": "Concise justification."
}

Rules:
- Selection must be driven by `user_query`, not fixed modality assumptions.
- If no sample/file evidence supports the query target, mark false positive with empty selected_samples.
- Prefer sample-level evidence when present (title, characteristics, molecule, library_source, files).
- Use GSE_Level_Bundled when samples are split but files are only available at series level.
- Keep reasoning concise.
"""


class SampleSelectorSkill(Skill):
    """Phase 1 preprocessor for LLM-driven sample selection.

    This phase only builds compact metadata context for LLM input.
    It does not run LLM classification yet.
    """

    def __init__(
        self,
        ncbi_client: NCBIClient | None,
        max_chars: int = 140,
        max_files_per_sample: int = 4,
        max_characteristics_per_sample: int = 6,
    ):
        self._ncbi_client = ncbi_client
        self._max_chars = max_chars
        self._max_files_per_sample = max_files_per_sample
        self._max_characteristics_per_sample = max_characteristics_per_sample

    @property
    def name(self) -> str:
        return "sample_selector"

    def execute(self, context: PipelineContext) -> PipelineContext:
        if self._ncbi_client is None:
            context.errors.append("SampleSelectorSkill requires ncbi_client for execute()")
            logger.warning("SampleSelectorSkill requires ncbi_client for execute()")
            return context

        datasets = context.filtered_datasets or context.datasets
        if not datasets:
            logger.warning("No datasets to preprocess for sample selector")
            return context

        accessions = [ds.accession for ds in datasets]
        soft_texts = self._ncbi_client.fetch_family_soft_batch(accessions)

        for accession, soft_text in soft_texts.items():
            if not soft_text:
                context.errors.append(f"Failed to fetch Family SOFT for {accession}")
                continue

            try:
                samples = parse_family_soft(soft_text)
            except Exception as exc:
                context.errors.append(f"Failed to parse Family SOFT for {accession}: {exc}")
                logger.warning("Failed to parse Family SOFT for %s: %s", accession, exc)
                continue

            context.sample_metadata[accession] = samples

            compact = self.build_series_context(accession, samples)
            context.sample_selector_context[accession] = compact
            context.sample_selector_context_json[accession] = json.dumps(
                compact,
                separators=(",", ":"),
                sort_keys=True,
            )

            logger.info(
                "%s: preprocessed %s samples for LLM context",
                accession,
                len(samples),
            )

        return context

    def build_series_context(self, accession: str, samples: list[GEOSample]) -> dict[str, Any]:
        """Build compact JSON-safe metadata used in Phase 1 prompts."""
        compact_samples: list[dict[str, Any]] = []
        samples_with_files = 0
        unique_characteristic_keys: set[str] = set()

        for sample in samples:
            compact_characteristics = self._compact_characteristics(sample.characteristics)
            compact_files = self._compact_supplementary_files(sample.supplementary_files)

            if compact_files:
                samples_with_files += 1

            unique_characteristic_keys.update(compact_characteristics.keys())

            entry: dict[str, Any] = {
                "gsm_id": sample.accession,
                "sample_title": self._truncate(sample.title),
            }

            if compact_characteristics:
                entry["characteristics"] = compact_characteristics
            if compact_files:
                entry["supplementary_files"] = compact_files
            if sample.molecule:
                entry["molecule"] = self._truncate(sample.molecule)
            if sample.library_source:
                entry["library_source"] = self._truncate(sample.library_source)

            compact_samples.append(entry)

        return {
            "series_id": accession,
            "sample_count": len(samples),
            "samples_with_supp_files": samples_with_files,
            "samples_without_supp_files": len(samples) - samples_with_files,
            "characteristic_keys": sorted(unique_characteristic_keys),
            "samples": compact_samples,
        }

    def build_series_context_json(self, accession: str, samples: list[GEOSample]) -> str:
        """Return minified JSON string for prompt injection."""
        return json.dumps(
            self.build_series_context(accession, samples),
            separators=(",", ":"),
            sort_keys=True,
        )

    def _compact_characteristics(self, characteristics: dict[str, str]) -> dict[str, str]:
        if not characteristics:
            return {}

        ranked_keys = []
        for key in characteristics:
            low_key = key.strip().lower()
            is_core = low_key in _CORE_CHARACTERISTICS
            ranked_keys.append((0 if is_core else 1, low_key, key))

        ranked_keys.sort()

        compact: dict[str, str] = {}
        for _, low_key, original_key in ranked_keys:
            if len(compact) >= self._max_characteristics_per_sample:
                break
            value = characteristics.get(original_key, "")
            compact[low_key] = self._truncate(value)

        return compact

    def _compact_supplementary_files(self, supplementary_files: list[str]) -> list[str]:
        if not supplementary_files:
            return []

        compact_files = []
        for raw in supplementary_files[: self._max_files_per_sample]:
            file_name = Path(raw).name if "/" in raw else raw
            compact_files.append(self._truncate(file_name))
        return compact_files

    def _truncate(self, text: str) -> str:
        text = (text or "").strip()
        if len(text) <= self._max_chars:
            return text
        return text[: self._max_chars - 3].rstrip() + "..."


def preprocess_family_soft_directory(
    input_dir: str | Path,
    output_file: str | Path | None = None,
    max_chars: int = 140,
    max_files_per_sample: int = 4,
    max_characteristics_per_sample: int = 6,
) -> dict[str, dict[str, Any]]:
    """Build Phase 1 context for all local *_family.soft files in a directory."""
    input_path = Path(input_dir)
    files = sorted(input_path.glob("*_family.soft"))

    skill = SampleSelectorSkill(
        ncbi_client=None,
        max_chars=max_chars,
        max_files_per_sample=max_files_per_sample,
        max_characteristics_per_sample=max_characteristics_per_sample,
    )

    contexts: dict[str, dict[str, Any]] = {}
    for soft_file in files:
        accession = soft_file.stem.replace("_family", "")
        samples = parse_family_soft(soft_file.read_text(errors="ignore"))
        contexts[accession] = skill.build_series_context(accession, samples)

    if output_file:
        output_path = Path(output_file)
        output_path.write_text(
            json.dumps(contexts, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    return contexts


def select_samples(
    query: str,
    metadata: dict[str, Any],
    llm_client: Any,
    model: str = "claude-haiku-4-5-20251001",
    temperature: float = 0.1,
    max_tokens: int = 2048,
    include_debug: bool = False,
) -> dict[str, Any]:
    """Phase 2: call LLM to select query-matching samples from one series."""
    if not query or not query.strip():
        raise SkillError("query must be a non-empty string")
    if not isinstance(metadata, dict):
        raise SkillError("metadata must be a dict")

    payload = {
        "user_query": query.strip(),
        "metadata": metadata,
    }

    try:
        response = llm_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=SELECTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, separators=(",", ":"))}],
        )
    except Exception as exc:
        raise SkillError(f"LLM call failed: {exc}") from exc

    try:
        text = response.content[0].text
    except Exception as exc:
        raise SkillError(f"LLM response format is invalid: {exc}") from exc

    result = _parse_json_object_from_llm_text(text)
    validated = _validate_selection_output(result, metadata)
    if not include_debug:
        return validated
    return {
        "result": validated,
        "raw_selector_output": text,
        "raw_selector_json": result,
    }


def heuristic_select_samples(query: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Fallback selector used when LLM is unavailable during debug runs."""
    query_terms = _extract_query_terms(query)
    if not query_terms:
        return {
            "is_false_positive": True,
            "download_strategy": "None",
            "selected_samples": [],
            "reasoning": "Heuristic fallback: query has no discriminative terms to match samples.",
        }

    selected_samples: list[dict[str, str]] = []
    sample_entries = metadata.get("samples", [])

    for sample in sample_entries:
        if not isinstance(sample, dict):
            continue
        gsm_id = str(sample.get("gsm_id", "")).strip()
        title = str(sample.get("sample_title", "")).strip()
        if not gsm_id:
            continue

        text_parts = [title, str(sample.get("molecule", "")), str(sample.get("library_source", ""))]
        characteristics = sample.get("characteristics", {})
        if isinstance(characteristics, dict):
            text_parts.extend(str(v) for v in characteristics.values())
        text_parts.extend(sample.get("supplementary_files", []) or [])
        blob = " ".join(text_parts).lower()

        matched_terms = [term for term in query_terms if term in blob]
        integrated_like = any(keyword in blob for keyword in _INTEGRATED_KEYWORDS)

        if matched_terms:
            selected_samples.append(
                {
                    "gsm_id": gsm_id,
                    "sample_title": title,
                    "selection_label": (
                        "Integrated_Object"
                        if integrated_like
                        else f"query-match:{','.join(matched_terms[:3])}"
                    ),
                }
            )

    if not selected_samples:
        return {
            "is_false_positive": True,
            "download_strategy": "None",
            "selected_samples": [],
            "reasoning": "Heuristic fallback: no sample text matched query terms.",
        }

    samples_with_files = 0
    integrated_selected = False
    sample_lookup = {
        str(item.get("gsm_id", "")): item
        for item in sample_entries
        if isinstance(item, dict)
    }
    for selected in selected_samples:
        src = sample_lookup.get(selected["gsm_id"], {})
        files = src.get("supplementary_files", []) or []
        if files:
            samples_with_files += 1
        text_blob = " ".join([selected["sample_title"], *[str(f) for f in files]]).lower()
        if any(keyword in text_blob for keyword in _INTEGRATED_KEYWORDS):
            integrated_selected = True

    if integrated_selected:
        strategy = "Integrated_Object"
    elif samples_with_files == 0:
        strategy = "GSE_Level_Bundled"
    else:
        strategy = "GSM_Level_Separated"

    return {
        "is_false_positive": False,
        "download_strategy": strategy,
        "selected_samples": selected_samples,
        "reasoning": (
            "Heuristic fallback: selected samples by query-term text matching "
            f"({', '.join(query_terms[:6])})."
        ),
    }


def _parse_json_object_from_llm_text(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SkillError(f"LLM returned invalid JSON object: {exc}") from exc

    if not isinstance(obj, dict):
        raise SkillError("LLM output must be a JSON object")
    return obj


def _validate_selection_output(result: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    sample_lookup = {
        str(item.get("gsm_id", "")): str(item.get("sample_title", ""))
        for item in metadata.get("samples", [])
        if isinstance(item, dict) and item.get("gsm_id")
    }

    if "is_false_positive" not in result or not isinstance(result["is_false_positive"], bool):
        raise SkillError("Output field `is_false_positive` must be boolean")
    if "download_strategy" not in result or not isinstance(result["download_strategy"], str):
        raise SkillError("Output field `download_strategy` must be string")
    if "selected_samples" not in result or not isinstance(result["selected_samples"], list):
        raise SkillError("Output field `selected_samples` must be list")
    if "reasoning" not in result or not isinstance(result["reasoning"], str):
        raise SkillError("Output field `reasoning` must be string")

    strategy = _normalize_strategy(result["download_strategy"])
    if strategy not in VALID_DOWNLOAD_STRATEGIES:
        raise SkillError(f"Unsupported download_strategy: {result['download_strategy']}")

    cleaned_samples: list[dict[str, str]] = []
    seen_gsm: set[str] = set()
    for item in result["selected_samples"]:
        if not isinstance(item, dict):
            raise SkillError("Each selected sample must be an object")

        gsm_id = str(item.get("gsm_id", "")).strip()
        sample_title = str(item.get("sample_title", "")).strip()
        selection_label = str(item.get("selection_label", "")).strip()
        if not selection_label:
            # Backward compatibility for older prompt outputs.
            selection_label = str(item.get("modality_inferred", "")).strip()

        if not gsm_id:
            raise SkillError("selected_samples[].gsm_id is required")
        if sample_lookup and gsm_id not in sample_lookup:
            raise SkillError(f"selected sample {gsm_id} is not in metadata")
        if gsm_id in seen_gsm:
            continue
        seen_gsm.add(gsm_id)
        if not sample_title and gsm_id in sample_lookup:
            sample_title = sample_lookup[gsm_id]
        if not sample_title:
            raise SkillError(f"selected sample {gsm_id} is missing sample_title")
        if not selection_label:
            raise SkillError(f"selected sample {gsm_id} is missing selection_label")

        cleaned_samples.append(
            {
                "gsm_id": gsm_id,
                "sample_title": sample_title,
                "selection_label": selection_label[:120],
                # Backward-compatible alias for legacy downstream code.
                "modality_inferred": selection_label[:120],
            }
        )

    if result["is_false_positive"]:
        strategy = "None"
        cleaned_samples = []

    return {
        "is_false_positive": result["is_false_positive"],
        "download_strategy": strategy,
        "selected_samples": cleaned_samples,
        "reasoning": result["reasoning"].strip(),
    }


def _normalize_strategy(strategy: str) -> str:
    normalized = strategy.strip()
    aliases = {
        "gsm_level_separated": "GSM_Level_Separated",
        "gse_level_bundled": "GSE_Level_Bundled",
        "integrated_object": "Integrated_Object",
        "none": "None",
    }
    key = normalized.lower()
    if key in aliases:
        return aliases[key]
    return normalized


def _extract_query_terms(query: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9+._-]{3,}", (query or "").lower())
    filtered: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in _QUERY_STOPWORDS:
            continue
        if term in seen:
            continue
        seen.add(term)
        filtered.append(term)
    return filtered

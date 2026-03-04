import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from geo_agent.models.context import PipelineContext
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)

VALID_LIBRARY_TYPES = {"GEX", "ADT", "TCR", "BCR", "HTO", "ATAC", "OTHER"}

# NOTE:
# This parser is intentionally rule-based (no LLM calls) for large-scale runs.

# Priority used when scores tie.
_MODALITY_PRIORITY = ["HTO", "ADT", "TCR", "BCR", "ATAC", "GEX", "OTHER"]

# Field weights for modality inference.
_FIELD_WEIGHT = {
    "library_type": 10,
    "library_strategy": 6,
    "molecule": 5,
    "description": 4,
    "characteristics_rows": 3,
    "sample_title": 3,
    "supplementary_file_names": 2,
}

# Keyword inventory based on observed GEO patterns + user requirements.
_MODALITY_TERMS: dict[str, tuple[str, ...]] = {
    "HTO": ("hto", "hashtag", "hashing"),
    "ADT": ("adt", "surface", "abseq", "ab-seq", "antibody", "cite-seq"),
    "TCR": (
        "tcr",
        "vdj",
        "gdtcr",
        "abtcr",
        "gd tcr",
        "ab tcr",
        "gamma delta",
        "vdj - gd tcr",
        "vdj - ab tcr",
    ),
    "BCR": ("bcr", "immunoglobulin", "igh", "igk", "igl"),
    "ATAC": ("atac", "chromatin accessibility"),
    "GEX": (
        "gex",
        "gene expression",
        "mrna",
        "5'gex",
        "5gex",
        "rna-seq",
        "scrna",
        "sc rna",
        "total rna",
        "polya rna",
    ),
}

# Tokens that should not be surfaced as unknown keywords.
_COMMON_STOPWORDS = {
    "sample",
    "samples",
    "library",
    "type",
    "strategy",
    "source",
    "single",
    "cell",
    "seq",
    "sequencing",
    "other",
    "unknown",
    "data",
    "genomics",
    "annotation",
    "annotations",
    "contig",
    "matrix",
    "features",
    "barcodes",
    "csv",
    "tsv",
    "mtx",
    "gz",
    "human",
    "mouse",
    "homo",
    "sapiens",
}


class FamilySoftStructurerSkill(Skill):
    """Parse local Family SOFT files into sample-level structured metadata."""

    def __init__(
        self,
        soft_dir: str | Path,
        llm_client: Any | None = None,
        model: str = "claude-haiku-4-5-20251001",
        temperature: float = 0.0,
        max_tokens: int = 2048,
        llm_chunk_size: int = 20,
        include_raw_fields: bool = False,
    ):
        self._soft_dir = Path(soft_dir)
        self._include_raw_fields = include_raw_fields

        # Backward compatibility with previous signature; values are intentionally unused.
        if llm_client is not None:
            logger.warning("FamilySoftStructurerSkill now uses rule-based parsing only; llm_client is ignored")
        _ = (model, temperature, max_tokens, llm_chunk_size)

    @property
    def name(self) -> str:
        return "family_soft_structurer"

    def execute(self, context: PipelineContext) -> PipelineContext:
        series_ids = _resolve_series_ids(context)
        if not series_ids:
            logger.warning("FamilySoftStructurerSkill: no target series IDs")
            return context

        for series_id in series_ids:
            soft_path = self._soft_dir / f"{series_id}_family.soft"
            if not soft_path.exists():
                context.errors.append(f"{series_id}: Family SOFT file not found at {soft_path}")
                continue

            try:
                soft_text = soft_path.read_text(errors="ignore")
                structured = structure_family_soft_text(
                    series_id=series_id,
                    soft_text=soft_text,
                    include_raw_fields=self._include_raw_fields,
                    source_file=str(soft_path),
                )
            except Exception as exc:  # pragma: no cover - defensive
                context.errors.append(f"{series_id}: failed to structure Family SOFT: {exc}")
                logger.exception("Failed to structure %s", series_id)
                continue

            context.family_soft_structured[series_id] = structured
            context.family_soft_structured_json[series_id] = json.dumps(
                structured,
                sort_keys=True,
                separators=(",", ":"),
            )

        return context


def structure_family_soft_series(
    series_ids: list[str],
    soft_dir: str | Path,
    llm_client: Any | None = None,
    model: str = "claude-haiku-4-5-20251001",
    temperature: float = 0.0,
    max_tokens: int = 2048,
    llm_chunk_size: int = 20,
    debug_print: bool = False,
    include_raw_fields: bool = False,
    output_file: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Batch structure local Family SOFT files using target series IDs (rule-based)."""
    if llm_client is not None:
        logger.warning("structure_family_soft_series is rule-based; llm_client is ignored")
    _ = (model, temperature, max_tokens, llm_chunk_size)

    soft_dir_path = Path(soft_dir)
    results: dict[str, dict[str, Any]] = {}

    normalized = [item.strip() for item in series_ids if item and item.strip()]
    for idx, series_id in enumerate(dict.fromkeys(normalized), start=1):
        soft_path = soft_dir_path / f"{series_id}_family.soft"
        if not soft_path.exists():
            raise SkillError(f"{series_id}: Family SOFT file not found at {soft_path}")

        if debug_print:
            print(f"[parse] {idx}/{len(normalized)} start {series_id}", flush=True)

        structured = structure_family_soft_text(
            series_id=series_id,
            soft_text=soft_path.read_text(errors="ignore"),
            include_raw_fields=include_raw_fields,
            source_file=str(soft_path),
        )
        results[series_id] = structured

        if debug_print:
            print(
                f"[parse] {idx}/{len(normalized)} done {series_id} "
                f"samples={structured.get('sample_count', 0)}",
                flush=True,
            )

    if output_file:
        Path(output_file).write_text(
            json.dumps(results, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    return results


def structure_family_soft_text(
    series_id: str,
    soft_text: str,
    llm_client: Any | None = None,
    model: str = "claude-haiku-4-5-20251001",
    temperature: float = 0.0,
    max_tokens: int = 2048,
    llm_chunk_size: int = 20,
    debug_print: bool = False,
    include_raw_fields: bool = False,
    source_file: str = "",
) -> dict[str, Any]:
    """Structure one Family SOFT text into sample-level records (rule-based)."""
    if llm_client is not None and debug_print:
        print("[parse] llm_client provided but ignored (rule-based mode)", flush=True)
    _ = (llm_client, model, temperature, max_tokens, llm_chunk_size)

    blocks = _parse_sample_blocks(soft_text)
    samples = [
        _build_structured_sample(block, fallback_series_id=series_id, include_raw_fields=include_raw_fields)
        for block in blocks
    ]

    library_type_counts: dict[str, int] = {}
    unknown_counter: Counter[str] = Counter()

    for sample in samples:
        modality = _infer_modality(sample)
        sample["modality"] = modality
        sample["inferred_library_type"] = modality["inferred_library_type"]
        sample["inference_evidence"] = modality["evidence"]

        notes = list(sample.get("notes", []))
        if modality["inferred_library_type"] == "OTHER":
            notes.append("modality_uncertain")
        if not sample.get("library_type", ""):
            notes.append("missing_library_type")
        if not sample.get("supplementary_files", []):
            notes.append("no_supplementary_files")

        if modality["unmapped_keywords"]:
            notes.append("unmapped_keywords:" + ",".join(modality["unmapped_keywords"]))
            unknown_counter.update(modality["unmapped_keywords"])

        # Keep notes concise and deterministic.
        sample["notes"] = list(dict.fromkeys(notes))[:8]

        inferred = modality["inferred_library_type"]
        library_type_counts[inferred] = library_type_counts.get(inferred, 0) + 1

    field_inventory = _build_field_inventory(blocks)
    keyword_watchlist = [
        {"keyword": keyword, "count": count}
        for keyword, count in unknown_counter.most_common(100)
    ]

    return {
        "series_id": series_id,
        "source_file": source_file,
        "parser_mode": "rule_based",
        "sample_count": len(samples),
        "field_inventory": field_inventory,
        "inferred_library_type_counts": library_type_counts,
        "keyword_watchlist": keyword_watchlist,
        "samples": samples,
    }


def _resolve_series_ids(context: PipelineContext) -> list[str]:
    if context.target_series_ids:
        unique_ids = []
        seen: set[str] = set()
        for value in context.target_series_ids:
            accession = (value or "").strip()
            if not accession or accession in seen:
                continue
            seen.add(accession)
            unique_ids.append(accession)
        return unique_ids

    datasets = context.filtered_datasets or context.datasets
    return sorted({item.accession for item in datasets if item.accession})


def _parse_sample_blocks(soft_text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    parts = re.split(r"^\^SAMPLE\s*=\s*", soft_text, flags=re.MULTILINE)
    for raw_block in parts:
        block = raw_block.strip()
        if not block:
            continue

        lines = block.splitlines()
        gsm_id = lines[0].strip()
        if not gsm_id.startswith("GSM"):
            continue

        raw_fields: dict[str, list[str]] = {}
        for line in lines[1:]:
            text = line.strip()
            if not text.startswith("!") or " = " not in text:
                continue
            key, _, value = text.partition(" = ")
            key = key.strip()
            value = value.strip()
            raw_fields.setdefault(key, []).append(value)

        blocks.append({"gsm_id": gsm_id, "raw_fields": raw_fields})
    return blocks


def _build_structured_sample(
    block: dict[str, Any],
    fallback_series_id: str,
    include_raw_fields: bool,
) -> dict[str, Any]:
    gsm_id = str(block.get("gsm_id", "")).strip()
    raw_fields = block.get("raw_fields", {}) or {}

    characteristics_rows = _collect_values_by_prefix(raw_fields, "!Sample_characteristics_ch")
    characteristics = _parse_characteristics(characteristics_rows)

    supplementary_urls = _collect_supplementary_urls(raw_fields)
    supplementary_file_names = [_extract_file_name(url) for url in supplementary_urls]
    relations = _collect_relations(raw_fields)

    core_characteristics = {}
    for key in ("tissue", "cell type", "disease", "condition", "time point", "age", "sex"):
        if key in characteristics:
            core_characteristics[key] = characteristics[key]

    record: dict[str, Any] = {
        "gsm_id": gsm_id,
        "sample_geo_accession": _first_value(raw_fields, "!Sample_geo_accession") or gsm_id,
        "sample_series_id": _first_value(raw_fields, "!Sample_series_id") or fallback_series_id,
        "sample_title": _first_value(raw_fields, "!Sample_title"),
        "sample_status": _first_value(raw_fields, "!Sample_status"),
        "organism": _first_value_by_prefix(raw_fields, "!Sample_organism_ch"),
        "source_name": _first_value_by_prefix(raw_fields, "!Sample_source_name_ch"),
        "library_strategy": _first_value(raw_fields, "!Sample_library_strategy"),
        "library_source": _first_value(raw_fields, "!Sample_library_source"),
        "molecule": _first_value_by_prefix(raw_fields, "!Sample_molecule_ch"),
        "platform_id": _first_value(raw_fields, "!Sample_platform_id"),
        "description": _join_values(raw_fields, "!Sample_description"),
        "characteristics": characteristics,
        "core_characteristics": core_characteristics,
        "characteristics_rows": characteristics_rows,
        "library_type": characteristics.get("library type", ""),
        "supplementary_files": supplementary_urls,
        "supplementary_file_names": supplementary_file_names,
        "relation_sra": relations["sra"],
        "relation_biosample": relations["biosample"],
        "relation_other": relations["other"],
        "observed_sample_fields": sorted(raw_fields.keys()),
        "notes": [],
    }
    record["biology"] = {
        "organism": record["organism"],
        "source_name": record["source_name"],
        "sample_title": record["sample_title"],
        "characteristics": record["characteristics"],
        "core_characteristics": record["core_characteristics"],
    }
    record["file_locator"] = {
        "supplementary_files": record["supplementary_files"],
        "supplementary_file_names": record["supplementary_file_names"],
        "relation_sra": record["relation_sra"],
        "relation_biosample": record["relation_biosample"],
        "relation_other": record["relation_other"],
    }
    if include_raw_fields:
        record["raw_sample_fields"] = raw_fields

    return record


def _build_field_inventory(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    sample_count = len(blocks)
    presence_counts: dict[str, int] = {}
    value_counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}

    for block in blocks:
        raw_fields = block.get("raw_fields", {}) or {}
        for key, values in raw_fields.items():
            presence_counts[key] = presence_counts.get(key, 0) + 1
            value_counts[key] = value_counts.get(key, 0) + len(values)
            bucket = examples.setdefault(key, [])
            for value in values:
                if value not in bucket:
                    bucket.append(value)
                if len(bucket) >= 2:
                    break

    all_fields = sorted(presence_counts.keys())
    common_fields = [key for key in all_fields if presence_counts.get(key, 0) == sample_count]
    variable_fields = [key for key in all_fields if presence_counts.get(key, 0) < sample_count]
    field_roles = _classify_field_roles(all_fields)
    analysis_fields = [
        key
        for key in all_fields
        if "administrative" not in field_roles["roles_by_field"].get(key, [])
    ]

    return {
        "all_fields": all_fields,
        "analysis_fields": analysis_fields,
        "common_fields": common_fields,
        "variable_fields": variable_fields,
        "field_presence_counts": presence_counts,
        "field_value_counts": value_counts,
        "field_examples": examples,
        "field_roles": field_roles,
    }


def _classify_field_roles(fields: list[str]) -> dict[str, Any]:
    roles_by_field: dict[str, list[str]] = {}
    grouped = {
        "technical": [],
        "biological": [],
        "download": [],
        "linkage": [],
        "administrative": [],
        "other": [],
    }

    for field in fields:
        low = field.lower()
        roles: list[str] = []

        if "supplementary_file" in low or "relation" in low:
            roles.append("download")
        if (
            "characteristics" in low
            or "library_" in low
            or "molecule" in low
            or "description" in low
            or low.endswith("_title")
        ):
            roles.append("technical")
        if "organism_" in low or "source_name_" in low or "characteristics" in low or low.endswith("_title"):
            roles.append("biological")
        if low in {
            "!sample_geo_accession",
            "!sample_series_id",
            "!sample_status",
            "!sample_title",
        }:
            roles.append("linkage")
        if (
            "contact_" in low
            or "submission_date" in low
            or "last_update_date" in low
            or "data_row_count" in low
            or "channel_count" in low
            or "extract_protocol" in low
            or "data_processing" in low
        ):
            roles.append("administrative")
        if not roles:
            roles.append("other")

        roles_by_field[field] = roles
        for role in roles:
            grouped[role].append(field)

    for role in grouped:
        grouped[role] = sorted(set(grouped[role]))

    return {
        "roles_by_field": roles_by_field,
        "technical_fields": grouped["technical"],
        "biological_fields": grouped["biological"],
        "download_fields": grouped["download"],
        "linkage_fields": grouped["linkage"],
        "administrative_fields": grouped["administrative"],
        "other_fields": grouped["other"],
    }


def _collect_values_by_prefix(raw_fields: dict[str, list[str]], prefix: str) -> list[str]:
    values: list[str] = []
    for key in sorted(raw_fields.keys()):
        if key.startswith(prefix):
            values.extend(item for item in raw_fields[key] if item)
    return values


def _collect_supplementary_urls(raw_fields: dict[str, list[str]]) -> list[str]:
    urls: list[str] = []
    for key in sorted(raw_fields.keys()):
        if not key.startswith("!Sample_supplementary_file"):
            continue
        for value in raw_fields[key]:
            if not value or value.lower() == "none":
                continue
            urls.append(value)
    return urls


def _collect_relations(raw_fields: dict[str, list[str]]) -> dict[str, list[str]]:
    relations = {"sra": [], "biosample": [], "other": []}
    for value in raw_fields.get("!Sample_relation", []):
        low = value.lower()
        if low.startswith("sra:"):
            relations["sra"].append(value.split(":", 1)[1].strip())
        elif low.startswith("biosample:"):
            relations["biosample"].append(value.split(":", 1)[1].strip())
        else:
            relations["other"].append(value.strip())
    return relations


def _parse_characteristics(rows: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in rows:
        if ": " in raw:
            key, _, value = raw.partition(": ")
            norm_key = key.strip().lower()
            value = value.strip()
            if norm_key in parsed and parsed[norm_key] != value:
                parsed[norm_key] = f"{parsed[norm_key]}; {value}"
            else:
                parsed[norm_key] = value
        else:
            norm_key = raw.strip().lower()
            parsed[norm_key] = raw.strip()
    return parsed


def _first_value(raw_fields: dict[str, list[str]], key: str) -> str:
    values = raw_fields.get(key, [])
    return values[0].strip() if values else ""


def _first_value_by_prefix(raw_fields: dict[str, list[str]], prefix: str) -> str:
    values = _collect_values_by_prefix(raw_fields, prefix)
    return values[0].strip() if values else ""


def _join_values(raw_fields: dict[str, list[str]], key: str) -> str:
    values = [item.strip() for item in raw_fields.get(key, []) if item and item.strip()]
    return "; ".join(values)


def _extract_file_name(path_value: str) -> str:
    return Path(path_value).name if "/" in path_value else path_value


def _infer_modality(sample: dict[str, Any]) -> dict[str, Any]:
    field_blobs = {
        "library_type": str(sample.get("library_type", "")).lower(),
        "library_strategy": str(sample.get("library_strategy", "")).lower(),
        "molecule": str(sample.get("molecule", "")).lower(),
        "description": str(sample.get("description", "")).lower(),
        "characteristics_rows": " ".join(sample.get("characteristics_rows", []) or []).lower(),
        "sample_title": str(sample.get("sample_title", "")).lower(),
        "supplementary_file_names": " ".join(sample.get("supplementary_file_names", []) or []).lower(),
    }

    score = {key: 0 for key in VALID_LIBRARY_TYPES}
    evidence: dict[str, list[str]] = {key: [] for key in VALID_LIBRARY_TYPES}

    for modality, terms in _MODALITY_TERMS.items():
        for field_name, blob in field_blobs.items():
            if not blob:
                continue
            weight = _FIELD_WEIGHT.get(field_name, 1)
            for term in terms:
                if term in blob:
                    score[modality] += weight
                    evidence[modality].append(f"{field_name}:{term}")

    # Tie-break and default.
    ranked = sorted(
        ((mod, sc) for mod, sc in score.items() if mod != "OTHER"),
        key=lambda x: x[1],
        reverse=True,
    )
    if not ranked or ranked[0][1] <= 0:
        inferred = "OTHER"
    else:
        top_score = ranked[0][1]
        tied = [mod for mod, sc in ranked if sc == top_score]
        inferred = next((mod for mod in _MODALITY_PRIORITY if mod in tied), "OTHER")

    ev = list(dict.fromkeys(evidence.get(inferred, [])))[:12]
    unknown_tokens = _collect_unmapped_keywords(sample)

    return {
        "inferred_library_type": inferred,
        "score": score.get(inferred, 0),
        "evidence": ev,
        "unmapped_keywords": unknown_tokens,
    }


def _collect_unmapped_keywords(sample: dict[str, Any]) -> list[str]:
    known_tokens: set[str] = set()
    for terms in _MODALITY_TERMS.values():
        for term in terms:
            known_tokens.update(re.findall(r"[a-z][a-z0-9+-]{1,}", term.lower()))
    known_tokens.update(_COMMON_STOPWORDS)

    text = " ".join(
        [
            str(sample.get("library_type", "")),
            str(sample.get("library_strategy", "")),
            str(sample.get("molecule", "")),
            str(sample.get("description", "")),
        ]
    ).lower()

    unknown: list[str] = []
    for token in re.findall(r"[a-z][a-z0-9+._-]{2,}", text):
        compact = token.strip("._-")
        if not compact:
            continue
        if "." in compact or "_" in compact:
            continue
        if compact in known_tokens:
            continue
        if compact.startswith("gsm"):
            continue
        if compact.isdigit():
            continue
        if compact not in unknown:
            unknown.append(compact)

    return unknown[:15]

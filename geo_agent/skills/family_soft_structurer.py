import json
import logging
import re
from pathlib import Path
from typing import Any

from geo_agent.models.context import PipelineContext
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)


class FamilySoftStructurerSkill(Skill):
    """Parse local Family SOFT files into sample-level structured metadata."""

    def __init__(
        self,
        soft_dir: str | Path,
        include_raw_fields: bool = False,
    ):
        self._soft_dir = Path(soft_dir)
        self._include_raw_fields = include_raw_fields

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
                structured = structure_family_soft_text(
                    series_id=series_id,
                    soft_text=soft_path.read_text(errors="ignore"),
                    include_raw_fields=self._include_raw_fields,
                    source_file=str(soft_path),
                )
            except Exception as exc:  # pragma: no cover
                context.errors.append(f"{series_id}: failed to structure Family SOFT: {exc}")
                logger.exception("Failed to structure %s", series_id)
                continue

            context.family_soft_structured[series_id] = structured
            context.family_soft_structured_json[series_id] = json.dumps(
                structured,
                sort_keys=True,
                separators=(",", ":"),
            )

            # Persist to DB if available
            if context.db is not None and context.pipeline_run_id is not None:
                context.db.save_samples_batch(
                    series_id, context.pipeline_run_id,
                    structured.get("samples", []),
                )
                logger.info("Persisted %d samples for %s to database",
                            structured.get("sample_count", 0), series_id)

                # Replace series supplementary files with accurate SOFT-parsed data
                series_supp = structured.get("series_supplementary_files", [])
                if series_supp:
                    context.db.replace_series_supplementary_files(
                        series_id, context.pipeline_run_id, series_supp,
                    )
                    logger.info("Updated %d series supplementary files for %s",
                                len(series_supp), series_id)

        return context


def structure_family_soft_series(
    series_ids: list[str],
    soft_dir: str | Path,
    debug_print: bool = False,
    include_raw_fields: bool = False,
    output_file: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Batch structure local Family SOFT files into structured metadata."""
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
    include_raw_fields: bool = False,
    source_file: str = "",
) -> dict[str, Any]:
    """Structure one Family SOFT text into sample-level records."""
    blocks = _parse_sample_blocks(soft_text)
    samples = [
        _build_structured_sample(block, fallback_series_id=series_id, include_raw_fields=include_raw_fields)
        for block in blocks
    ]

    for sample in samples:
        notes = list(sample.get("notes", []))
        if not sample.get("supplementary_files", []):
            notes.append("no_supplementary_files")
        sample["notes"] = list(dict.fromkeys(notes))

    field_inventory = _build_field_inventory(blocks)

    return {
        "series_id": series_id,
        "source_file": source_file,
        "sample_count": len(samples),
        "field_inventory": field_inventory,
        "series_supplementary_files": _parse_series_supplementary_files(soft_text),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
            raw_fields.setdefault(key.strip(), []).append(value.strip())

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
    relations = _collect_relations(raw_fields)

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
        "characteristics_rows": characteristics_rows,
        "library_type": characteristics.get("library type", ""),
        "supplementary_files": supplementary_urls,
        "supplementary_file_names": [_extract_file_name(u) for u in supplementary_urls],
        "relation_sra": relations["sra"],
        "relation_biosample": relations["biosample"],
        "relation_other": relations["other"],
        "notes": [],
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
    common_fields = [k for k in all_fields if presence_counts.get(k, 0) == sample_count]
    variable_fields = [k for k in all_fields if presence_counts.get(k, 0) < sample_count]

    return {
        "all_fields": all_fields,
        "common_fields": common_fields,
        "variable_fields": variable_fields,
        "field_presence_counts": presence_counts,
        "field_value_counts": value_counts,
        "field_examples": examples,
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
            if value and value.lower() != "none":
                urls.append(value)
    return urls


def _collect_relations(raw_fields: dict[str, list[str]]) -> dict[str, list[str]]:
    relations: dict[str, list[str]] = {"sra": [], "biosample": [], "other": []}
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


def _parse_series_supplementary_files(soft_text: str) -> list[dict[str, str]]:
    """Extract series-level supplementary file URLs from the ^SERIES block."""
    parts = re.split(r"^\^SAMPLE\s*=\s*", soft_text, maxsplit=1, flags=re.MULTILINE)
    series_block = parts[0] if parts else ""

    files = []
    for line in series_block.splitlines():
        text = line.strip()
        if not text.startswith("!Series_supplementary_file"):
            continue
        if " = " not in text:
            continue
        _, _, value = text.partition(" = ")
        value = value.strip()
        if not value or value.lower() == "none":
            continue
        files.append({
            "url": value,
            "file_name": _extract_file_name(value),
        })
    return files


def _extract_file_name(path_value: str) -> str:
    return Path(path_value).name if "/" in path_value else path_value

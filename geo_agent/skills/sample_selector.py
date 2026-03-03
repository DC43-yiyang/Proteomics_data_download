import json
import logging
import re
from typing import Any

from geo_agent.models.context import PipelineContext
from geo_agent.models.sample import GEOSample, SampleSelection
from geo_agent.ncbi.client import NCBIClient
from geo_agent.ncbi.parsers import parse_family_soft
from geo_agent.skills.base import Skill, SkillError

logger = logging.getLogger(__name__)

VALID_LIBRARY_TYPES = {"GEX", "ADT", "TCR", "BCR", "HTO", "ATAC", "OTHER"}

SYSTEM_PROMPT = """\
You are a bioinformatics expert classifying GEO samples by library type.

Classify each sample into exactly ONE category: GEX, ADT, TCR, BCR, HTO, ATAC, or OTHER.

## How to judge — use fields in this order

1. characteristics "library type" field — most reliable. If it says "mRNA" → GEX, "ADT" → ADT, "TCR" → TCR.
2. molecule field — "polyA RNA" or "total RNA" → GEX, "protein" → ADT, "genomic DNA" → TCR/BCR/ATAC.
3. library_source — "transcriptomic" → GEX, "other" → usually ADT.
4. Title keywords — but be careful, naming varies wildly (see mistakes below).
5. description — least reliable, often missing or irrelevant.

## Common mistakes to avoid

WRONG: Title contains "scRNAseq" → must be GEX.
RIGHT: ADT samples often have "scRNAseq" in the title too (e.g. "Patient 10-02_ADT timepoint T01 scRNAseq"). Look at molecule and library_source instead.

WRONG: Title doesn't contain "_ADT" → not ADT.
RIGHT: Some series use "Surface" (GSE268991) or "ADT/HTO mixed" (GSE303197) instead of "_ADT". Check molecule=protein.

WRONG: Title doesn't contain "_GEX" → not GEX.
RIGHT: Variants include "5'GEX", "_RNA", "_mRNA", ", GEX", "gene expression". Check molecule=polyA RNA.

## Naming variants I've seen across real GEO series

- GEX: "_GEX", ", GEX", "_RNA", "_mRNA", "5'GEX", "gene expression"
- ADT: "_ADT", ", ADT", "Surface", "ADT/HTO mixed"
- TCR: "_VDJ", "_TCR", "gdTCR", "abTCR", "library type: TCR"
- HTO: "_HTO", "ADT/HTO mixed"

## Confidence

- 0.9+: Multiple fields agree (characteristics + molecule + library_source all point the same way)
- 0.7-0.9: One strong field matches (e.g. characteristics says "library type: ADT" but title is ambiguous)
- 0.5-0.7: Signals conflict or are mostly missing
- <0.5: Cannot determine → classify as OTHER

## False positive series detection

If ALL samples in a batch look like the same type (e.g. all GEX, zero ADT/TCR/HTO), add a note in the reasoning of the first sample: "WARNING: no multi-library diversity detected — this series may not be genuine CITE-seq". This helps downstream tools flag false positives from GEO search.

## Output format

Return a JSON array (no markdown fences):
[{"accession": "GSM...", "library_type": "GEX", "confidence": 0.95, "reasoning": "brief explanation"}]
"""


BATCH_SIZE = 50  # Max samples per LLM call to avoid output token truncation


class SampleSelectorSkill(Skill):
    """Classify GSM samples by library type using LLM.

    Reads:
        context.filtered_datasets — list[GEODataset] (uses accessions)
        context.target_library_types — list[str] (e.g. ["GEX", "ADT"])

    Writes:
        context.sample_metadata — dict[str, list[GEOSample]]
        context.selected_samples — dict[str, list[SampleSelection]]
    """

    def __init__(
        self,
        ncbi_client: NCBIClient,
        llm_client: Any,  # anthropic.Anthropic
        model: str = "claude-haiku-4-5-20251001",
        confidence_threshold: float = 0.7,
    ):
        self._ncbi_client = ncbi_client
        self._llm_client = llm_client
        self._model = model
        self._confidence_threshold = confidence_threshold

    @property
    def name(self) -> str:
        return "sample_selector"

    def execute(self, context: PipelineContext) -> PipelineContext:
        datasets = context.filtered_datasets or context.datasets
        if not datasets:
            logger.warning("No datasets to classify samples for")
            return context

        accessions = [ds.accession for ds in datasets]
        target_types = set(t.upper() for t in (context.target_library_types or ["GEX"]))

        logger.info(
            f"Classifying samples for {len(accessions)} series, "
            f"target types: {target_types}"
        )

        # Step 1: Fetch Family SOFT in batch
        soft_texts = self._ncbi_client.fetch_family_soft_batch(accessions)

        # Step 2: Parse samples per series
        for acc, soft_text in soft_texts.items():
            if not soft_text:
                context.errors.append(f"Failed to fetch Family SOFT for {acc}")
                continue
            try:
                samples = parse_family_soft(soft_text)
                context.sample_metadata[acc] = samples
                logger.info(f"{acc}: parsed {len(samples)} samples")
            except Exception as e:
                context.errors.append(f"Failed to parse Family SOFT for {acc}: {e}")
                logger.warning(f"Failed to parse Family SOFT for {acc}: {e}")

        # Step 3: Classify samples per series via LLM
        for acc, samples in context.sample_metadata.items():
            if not samples:
                continue
            try:
                classifications = self._classify_samples(acc, samples)
                # Filter by target library types
                selected = [
                    c for c in classifications
                    if c.library_type in target_types
                ]
                context.selected_samples[acc] = selected
                logger.info(
                    f"{acc}: {len(selected)}/{len(classifications)} samples "
                    f"match target types {target_types}"
                )
            except Exception as e:
                context.errors.append(
                    f"Failed to classify samples for {acc}: {e}"
                )
                logger.warning(f"Failed to classify samples for {acc}: {e}")

        return context

    def _classify_samples(
        self, accession: str, samples: list[GEOSample]
    ) -> list[SampleSelection]:
        """Build compact JSON prompt and classify via LLM.

        Splits into chunks of BATCH_SIZE to avoid output token truncation.
        """
        if len(samples) <= BATCH_SIZE:
            return self._classify_chunk(accession, samples)

        # Split into chunks and merge results
        all_results: list[SampleSelection] = []
        for i in range(0, len(samples), BATCH_SIZE):
            chunk = samples[i : i + BATCH_SIZE]
            logger.info(
                f"{accession}: classifying chunk {i // BATCH_SIZE + 1} "
                f"({len(chunk)} samples)"
            )
            all_results.extend(self._classify_chunk(accession, chunk))
        return all_results

    def _classify_chunk(
        self, accession: str, samples: list[GEOSample]
    ) -> list[SampleSelection]:
        """Classify a single chunk of samples via LLM."""
        # Compress sample data for LLM
        sample_data = []
        for s in samples:
            entry: dict[str, Any] = {"accession": s.accession, "title": s.title}
            if s.molecule:
                entry["molecule"] = s.molecule
            if s.library_source:
                entry["library_source"] = s.library_source
            if s.characteristics:
                entry["characteristics"] = s.characteristics
            if s.description:
                entry["description"] = s.description
            sample_data.append(entry)

        user_msg = (
            f"Series {accession} has {len(samples)} samples. "
            f"Classify each by library type.\n\n"
            f"{json.dumps(sample_data, indent=None)}"
        )

        # Call LLM with 1 retry
        raw_response = self._call_llm(user_msg)

        # Parse response into SampleSelection objects
        return self._parse_llm_response(raw_response, samples)

    def _call_llm(self, user_msg: str) -> str:
        """Call LLM with system prompt + sample data.

        Retries are handled by the Anthropic SDK (set max_retries on client init).
        """
        try:
            response = self._llm_client.messages.create(
                model=self._model,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.content[0].text
        except Exception as e:
            raise SkillError(f"LLM call failed: {e}") from e

    def _parse_llm_response(
        self, raw_response: str, samples: list[GEOSample]
    ) -> list[SampleSelection]:
        """Parse JSON array from LLM response into SampleSelection objects."""
        # Strip markdown fences if present
        text = raw_response.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

        # Extract JSON array — LLM sometimes outputs text before/after the JSON
        bracket_start = text.find("[")
        bracket_end = text.rfind("]")
        if bracket_start != -1 and bracket_end > bracket_start:
            text = text[bracket_start : bracket_end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise SkillError(f"LLM returned invalid JSON: {e}\nResponse: {text[:500]}")

        if not isinstance(data, list):
            raise SkillError(f"LLM returned non-array JSON: {type(data)}")

        # Build lookup for supplementary files from original samples
        sample_files = {s.accession: s.supplementary_files for s in samples}

        results = []
        for item in data:
            acc = item.get("accession", "")
            lib_type = item.get("library_type", "OTHER").upper()
            confidence = float(item.get("confidence", 0.0))
            reasoning = item.get("reasoning", "")

            # Normalize unknown types to OTHER
            if lib_type not in VALID_LIBRARY_TYPES:
                logger.warning(
                    f"Unknown library_type '{lib_type}' for {acc}, mapping to OTHER"
                )
                lib_type = "OTHER"
                needs_review = True
            else:
                needs_review = confidence < self._confidence_threshold

            # Clamp confidence
            confidence = max(0.0, min(1.0, confidence))

            results.append(SampleSelection(
                accession=acc,
                library_type=lib_type,
                confidence=confidence,
                reasoning=reasoning,
                needs_review=needs_review,
                supplementary_files=sample_files.get(acc, []),
            ))

        return results

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

For each sample, classify it into exactly ONE of these categories:
- GEX: Gene expression (scRNA-seq, mRNA). Signals: title contains _GEX/_RNA/_transcriptome; molecule=polyA RNA/total RNA/cDNA; library_source=transcriptomic; characteristics has library type: mRNA
- ADT: Antibody-derived tag (CITE-seq protein). Signals: title contains _ADT/_protein/_AbSeq; molecule=protein; library_source=other; characteristics has library type: ADT; description mentions antibody
- TCR: T-cell receptor. Signals: title contains _TCR/_VDJ_T; characteristics has library type: TCR
- BCR: B-cell receptor. Signals: title contains _BCR/_VDJ_B; characteristics has library type: BCR
- HTO: Hashtag oligo. Signals: title contains _HTO/_hashtag; molecule=synthetic; characteristics has library type: HTO
- ATAC: Chromatin accessibility. Signals: title contains _ATAC; characteristics has library type: ATAC
- OTHER: Does not match any above category

Signal priority (judge in this order):
1. characteristics "library type" field (most reliable)
2. molecule field (polyA RNA vs protein vs genomic DNA)
3. library_source field (transcriptomic vs other)
4. Title keywords (_GEX, _ADT, etc.)
5. Description supplementary info
6. Series-level context for disambiguation

Confidence guidelines:
- 0.9+: Multiple signals agree (e.g. title has _GEX + molecule=polyA RNA + library_source=transcriptomic)
- 0.7-0.9: Partial signal match (e.g. only title keyword, other fields missing)
- 0.5-0.7: Ambiguous or contradictory signals
- <0.5: Nearly impossible to determine, classify as OTHER

Return a JSON array (no markdown fences) with one object per sample:
[{"accession": "GSM...", "library_type": "GEX", "confidence": 0.95, "reasoning": "brief explanation"}]
"""


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
        target_types = set(t.upper() for t in context.target_library_types)

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
        """Build compact JSON prompt and classify via LLM."""
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

    def _call_llm(self, user_msg: str, retries: int = 1) -> str:
        """Call LLM with system prompt + sample data."""
        for attempt in range(retries + 1):
            try:
                response = self._llm_client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                return response.content[0].text
            except Exception as e:
                if attempt < retries:
                    logger.warning(
                        f"LLM call failed (attempt {attempt + 1}), retrying: {e}"
                    )
                    continue
                raise SkillError(f"LLM call failed after {retries + 1} attempts: {e}")

    def _parse_llm_response(
        self, raw_response: str, samples: list[GEOSample]
    ) -> list[SampleSelection]:
        """Parse JSON array from LLM response into SampleSelection objects."""
        # Strip markdown fences if present
        text = raw_response.strip()
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

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

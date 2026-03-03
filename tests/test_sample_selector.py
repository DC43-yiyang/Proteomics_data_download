"""Tests for SampleSelectorSkill with mocked NCBI + LLM clients."""

import json
from unittest.mock import MagicMock, patch

import pytest

from geo_agent.models.context import PipelineContext
from geo_agent.models.dataset import GEODataset
from geo_agent.models.query import SearchQuery
from geo_agent.models.sample import GEOSample, SampleSelection
from geo_agent.skills.sample_selector import SampleSelectorSkill, VALID_LIBRARY_TYPES
from geo_agent.skills.base import SkillError


# --- Fixtures ---

FAMILY_SOFT_TWO_SAMPLES = """\
^SAMPLE = GSM9474997
!Sample_title = Patient 10-02_GEX timepoint T01 scRNAseq
!Sample_geo_accession = GSM9474997
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = library type: mRNA
!Sample_molecule_ch1 = polyA RNA
!Sample_library_source = transcriptomic
!Sample_description = Gene expression library
!Sample_supplementary_file = ftp://example.com/GSM9474997_matrix.mtx.gz
^SAMPLE = GSM9475081
!Sample_title = Patient 10-02_ADT timepoint T01 scRNAseq
!Sample_geo_accession = GSM9475081
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = library type: ADT
!Sample_molecule_ch1 = protein
!Sample_library_source = other
!Sample_description = antibody-derived oligonucleotide library
!Sample_supplementary_file = ftp://example.com/GSM9475081_matrix.mtx.gz
"""

LLM_RESPONSE_VALID = json.dumps([
    {
        "accession": "GSM9474997",
        "library_type": "GEX",
        "confidence": 0.95,
        "reasoning": "title=_GEX, molecule=polyA RNA, library_source=transcriptomic",
    },
    {
        "accession": "GSM9475081",
        "library_type": "ADT",
        "confidence": 0.95,
        "reasoning": "title=_ADT, molecule=protein, library_source=other",
    },
])


def _make_context(target_types=None):
    ctx = PipelineContext(
        query=SearchQuery(data_type="CITE-seq", organism="Homo sapiens"),
        filtered_datasets=[
            GEODataset(accession="GSE317605", uid="123", title="Test series"),
        ],
    )
    if target_types:
        ctx.target_library_types = target_types
    return ctx


def _make_mock_llm(response_text=LLM_RESPONSE_VALID):
    """Create a mock Anthropic client that returns the given text."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]
    mock_client.messages.create.return_value = mock_response
    return mock_client


def _make_mock_ncbi(soft_texts=None):
    """Create a mock NCBIClient."""
    mock_client = MagicMock()
    if soft_texts is None:
        soft_texts = {"GSE317605": FAMILY_SOFT_TWO_SAMPLES}
    mock_client.fetch_family_soft_batch.return_value = soft_texts
    return mock_client


# --- Tests ---

class TestSampleSelectorSkill:

    def test_basic_classification(self):
        """End-to-end: 2 samples classified as GEX + ADT, filter for both."""
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm()
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        assert "GSE317605" in ctx.sample_metadata
        assert len(ctx.sample_metadata["GSE317605"]) == 2

        assert "GSE317605" in ctx.selected_samples
        selected = ctx.selected_samples["GSE317605"]
        assert len(selected) == 2
        types = {s.library_type for s in selected}
        assert types == {"GEX", "ADT"}

    def test_filter_by_target_type(self):
        """Only ADT samples should be selected when target is ADT."""
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm()
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["ADT"])
        ctx = skill.execute(ctx)

        selected = ctx.selected_samples["GSE317605"]
        assert len(selected) == 1
        assert selected[0].library_type == "ADT"
        assert selected[0].accession == "GSM9475081"

    def test_supplementary_files_carried_over(self):
        """supplementary_files from parsed samples should be in selections."""
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm()
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        for s in ctx.selected_samples["GSE317605"]:
            assert len(s.supplementary_files) >= 1

    def test_low_confidence_flags_needs_review(self):
        """Samples below confidence threshold should have needs_review=True."""
        low_confidence_response = json.dumps([
            {
                "accession": "GSM9474997",
                "library_type": "GEX",
                "confidence": 0.5,
                "reasoning": "ambiguous signals",
            },
            {
                "accession": "GSM9475081",
                "library_type": "ADT",
                "confidence": 0.95,
                "reasoning": "clear ADT signals",
            },
        ])
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm(response_text=low_confidence_response)
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm, confidence_threshold=0.7)

        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        selected = ctx.selected_samples["GSE317605"]
        gex = [s for s in selected if s.library_type == "GEX"][0]
        adt = [s for s in selected if s.library_type == "ADT"][0]
        assert gex.needs_review is True
        assert adt.needs_review is False

    def test_unknown_library_type_mapped_to_other(self):
        """Unknown library types should be normalized to OTHER."""
        unknown_response = json.dumps([
            {
                "accession": "GSM9474997",
                "library_type": "UNKNOWN_TYPE",
                "confidence": 0.8,
                "reasoning": "unknown",
            },
            {
                "accession": "GSM9475081",
                "library_type": "ADT",
                "confidence": 0.95,
                "reasoning": "clear",
            },
        ])
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm(response_text=unknown_response)
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["OTHER", "ADT"])
        ctx = skill.execute(ctx)

        selected = ctx.selected_samples["GSE317605"]
        other = [s for s in selected if s.library_type == "OTHER"]
        assert len(other) == 1
        assert other[0].needs_review is True

    def test_llm_returns_markdown_fences(self):
        """LLM response wrapped in ```json ... ``` fences should still parse."""
        fenced = "```json\n" + LLM_RESPONSE_VALID + "\n```"
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm(response_text=fenced)
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        assert len(ctx.selected_samples["GSE317605"]) == 2

    def test_empty_soft_records_error(self):
        """Empty SOFT text should record an error, not crash."""
        ncbi = _make_mock_ncbi(soft_texts={"GSE317605": ""})
        llm = _make_mock_llm()
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["GEX"])
        ctx = skill.execute(ctx)

        assert any("GSE317605" in e for e in ctx.errors)

    def test_no_datasets_returns_early(self):
        """Should return context unchanged if no datasets."""
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm()
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = PipelineContext(
            query=SearchQuery(data_type="CITE-seq"),
            filtered_datasets=[],
            datasets=[],
        )
        ctx = skill.execute(ctx)

        assert ctx.selected_samples == {}
        assert ctx.sample_metadata == {}

    def test_llm_invalid_json_records_error(self):
        """Invalid JSON from LLM should record error after retry."""
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm(response_text="this is not json at all")
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["GEX"])
        ctx = skill.execute(ctx)

        assert any("GSE317605" in e for e in ctx.errors)

    def test_confidence_clamped(self):
        """Confidence values outside 0-1 should be clamped."""
        out_of_range = json.dumps([
            {
                "accession": "GSM9474997",
                "library_type": "GEX",
                "confidence": 1.5,
                "reasoning": "over-confident",
            },
            {
                "accession": "GSM9475081",
                "library_type": "ADT",
                "confidence": -0.3,
                "reasoning": "negative confidence",
            },
        ])
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm(response_text=out_of_range)
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        selected = ctx.selected_samples["GSE317605"]
        for s in selected:
            assert 0.0 <= s.confidence <= 1.0

    def test_skill_name(self):
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm()
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)
        assert skill.name == "sample_selector"

    def test_fallback_to_datasets_when_no_filtered(self):
        """Should use context.datasets if filtered_datasets is empty."""
        ncbi = _make_mock_ncbi()
        llm = _make_mock_llm()
        skill = SampleSelectorSkill(ncbi_client=ncbi, llm_client=llm)

        ctx = PipelineContext(
            query=SearchQuery(data_type="CITE-seq"),
            datasets=[
                GEODataset(accession="GSE317605", uid="123", title="Test"),
            ],
            target_library_types=["GEX", "ADT"],
        )
        ctx = skill.execute(ctx)

        assert "GSE317605" in ctx.selected_samples

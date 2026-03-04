"""Tests for StandaloneSampleSelectorSkill with mocked NCBI + LLM clients."""

import json
from unittest.mock import MagicMock

import pytest

from geo_agent.models.context import PipelineContext
from geo_agent.models.dataset import GEODataset
from geo_agent.models.query import SearchQuery
from geo_agent.models.sample import GEOSample, SampleSelection
from geo_agent.skills.standalone_sample_selector import StandaloneSampleSelectorSkill, VALID_LIBRARY_TYPES
from geo_agent.skills.base import SkillError
from geo_agent.utils.hierarchy import SeriesNode


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


def _make_standalone_hierarchy():
    """Return a hierarchy with one standalone and one sub node."""
    return {
        "GSE317605": SeriesNode(accession="GSE317605", role="standalone", in_search_results=True),
        "GSE999999": SeriesNode(accession="GSE999999", role="sub", in_search_results=True),
    }


def _make_context(target_types=None, with_hierarchy=True):
    ctx = PipelineContext(
        query=SearchQuery(data_type="CITE-seq", organism="Homo sapiens"),
        filtered_datasets=[
            GEODataset(accession="GSE317605", uid="123", title="Test series"),
        ],
    )
    if target_types:
        ctx.target_library_types = target_types
    if with_hierarchy:
        ctx.series_hierarchy = _make_standalone_hierarchy()
    return ctx


def _make_mock_llm(response_text=LLM_RESPONSE_VALID):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]
    mock_client.messages.create.return_value = mock_response
    return mock_client


def _make_mock_ncbi(soft_texts=None):
    mock_client = MagicMock()
    if soft_texts is None:
        soft_texts = {"GSE317605": FAMILY_SOFT_TWO_SAMPLES}
    mock_client.fetch_family_soft_batch.return_value = soft_texts
    return mock_client


# --- Tests ---

class TestStandaloneSampleSelectorSkill:

    def test_skill_name(self):
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm()
        )
        assert skill.name == "standalone_sample_selector"

    def test_only_standalone_series_are_processed(self):
        """Only standalone nodes from hierarchy should be fetched — not sub nodes."""
        ncbi = _make_mock_ncbi()
        skill = StandaloneSampleSelectorSkill(ncbi_client=ncbi, llm_client=_make_mock_llm())

        ctx = _make_context(target_types=["GEX", "ADT"], with_hierarchy=True)
        skill.execute(ctx)

        fetched = ncbi.fetch_family_soft_batch.call_args[0][0]
        assert "GSE317605" in fetched
        assert "GSE999999" not in fetched  # sub node — must be excluded

    def test_basic_classification(self):
        """End-to-end: 2 samples classified as GEX + ADT."""
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm()
        )
        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        assert "GSE317605" in ctx.sample_metadata
        assert len(ctx.sample_metadata["GSE317605"]) == 2
        assert "GSE317605" in ctx.selected_samples
        types = {s.library_type for s in ctx.selected_samples["GSE317605"]}
        assert types == {"GEX", "ADT"}

    def test_filter_by_target_type(self):
        """Only ADT samples should be selected when target is ADT."""
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm()
        )
        ctx = _make_context(target_types=["ADT"])
        ctx = skill.execute(ctx)

        selected = ctx.selected_samples["GSE317605"]
        assert len(selected) == 1
        assert selected[0].library_type == "ADT"
        assert selected[0].accession == "GSM9475081"

    def test_supplementary_files_carried_over(self):
        """supplementary_files from parsed samples should appear in selections."""
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm()
        )
        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        for s in ctx.selected_samples["GSE317605"]:
            assert len(s.supplementary_files) >= 1

    def test_low_confidence_flags_needs_review(self):
        low_conf = json.dumps([
            {"accession": "GSM9474997", "library_type": "GEX", "confidence": 0.5, "reasoning": "ambiguous"},
            {"accession": "GSM9475081", "library_type": "ADT", "confidence": 0.95, "reasoning": "clear"},
        ])
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(),
            llm_client=_make_mock_llm(response_text=low_conf),
            confidence_threshold=0.7,
        )
        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        selected = ctx.selected_samples["GSE317605"]
        gex = next(s for s in selected if s.library_type == "GEX")
        adt = next(s for s in selected if s.library_type == "ADT")
        assert gex.needs_review is True
        assert adt.needs_review is False

    def test_unknown_library_type_mapped_to_other(self):
        unknown = json.dumps([
            {"accession": "GSM9474997", "library_type": "UNKNOWN_TYPE", "confidence": 0.8, "reasoning": "?"},
            {"accession": "GSM9475081", "library_type": "ADT", "confidence": 0.95, "reasoning": "clear"},
        ])
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm(response_text=unknown)
        )
        ctx = _make_context(target_types=["OTHER", "ADT"])
        ctx = skill.execute(ctx)

        selected = ctx.selected_samples["GSE317605"]
        other = [s for s in selected if s.library_type == "OTHER"]
        assert len(other) == 1
        assert other[0].needs_review is True

    def test_llm_returns_markdown_fences(self):
        fenced = "```json\n" + LLM_RESPONSE_VALID + "\n```"
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm(response_text=fenced)
        )
        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)
        assert len(ctx.selected_samples["GSE317605"]) == 2

    def test_empty_soft_records_error(self):
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(soft_texts={"GSE317605": ""}),
            llm_client=_make_mock_llm(),
        )
        ctx = _make_context(target_types=["GEX"])
        ctx = skill.execute(ctx)
        assert any("GSE317605" in e for e in ctx.errors)

    def test_no_standalone_series_warns_and_returns(self):
        """If hierarchy has no standalone nodes, skill should return unchanged context."""
        hierarchy = {
            "GSE999999": SeriesNode(accession="GSE999999", role="sub", in_search_results=True),
        }
        ncbi = _make_mock_ncbi()
        skill = StandaloneSampleSelectorSkill(ncbi_client=ncbi, llm_client=_make_mock_llm())

        ctx = PipelineContext(query=SearchQuery(data_type="CITE-seq"))
        ctx.series_hierarchy = hierarchy
        ctx = skill.execute(ctx)

        ncbi.fetch_family_soft_batch.assert_not_called()
        assert ctx.selected_samples == {}

    def test_fallback_to_datasets_when_no_hierarchy(self):
        """Without series_hierarchy, falls back to filtered_datasets."""
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm()
        )
        ctx = _make_context(target_types=["GEX", "ADT"], with_hierarchy=False)
        ctx = skill.execute(ctx)
        assert "GSE317605" in ctx.selected_samples

    def test_llm_invalid_json_records_error(self):
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(),
            llm_client=_make_mock_llm(response_text="not json at all"),
        )
        ctx = _make_context(target_types=["GEX"])
        ctx = skill.execute(ctx)
        assert any("GSE317605" in e for e in ctx.errors)

    def test_confidence_clamped(self):
        out_of_range = json.dumps([
            {"accession": "GSM9474997", "library_type": "GEX", "confidence": 1.5, "reasoning": "over"},
            {"accession": "GSM9475081", "library_type": "ADT", "confidence": -0.3, "reasoning": "neg"},
        ])
        skill = StandaloneSampleSelectorSkill(
            ncbi_client=_make_mock_ncbi(), llm_client=_make_mock_llm(response_text=out_of_range)
        )
        ctx = _make_context(target_types=["GEX", "ADT"])
        ctx = skill.execute(ctx)

        for s in ctx.selected_samples["GSE317605"]:
            assert 0.0 <= s.confidence <= 1.0

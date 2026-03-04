"""Tests for SampleSelectorSkill Phase 1 preprocessing."""

import json
from unittest.mock import MagicMock

import pytest

from geo_agent.models.context import PipelineContext
from geo_agent.models.dataset import GEODataset
from geo_agent.models.query import SearchQuery
from geo_agent.skills.sample_selector import (
    SampleSelectorSkill,
    heuristic_select_samples,
    preprocess_family_soft_directory,
    select_samples,
)
from geo_agent.skills.base import SkillError

FAMILY_SOFT_TWO_SAMPLES = """\
^SAMPLE = GSM9474997
!Sample_title = Patient 10-02_GEX timepoint T01 scRNAseq
!Sample_geo_accession = GSM9474997
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = library type: mRNA
!Sample_characteristics_ch1 = tissue: PBMC
!Sample_molecule_ch1 = polyA RNA
!Sample_library_source = transcriptomic
!Sample_supplementary_file = ftp://example.com/GSM9474997_matrix.mtx.gz
^SAMPLE = GSM9475081
!Sample_title = Patient 10-02_ADT timepoint T01 scRNAseq
!Sample_geo_accession = GSM9475081
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = library type: ADT
!Sample_characteristics_ch1 = tissue: PBMC
!Sample_molecule_ch1 = protein
!Sample_library_source = other
!Sample_supplementary_file = NONE
"""


def _make_context():
    return PipelineContext(
        query=SearchQuery(data_type="CITE-seq", organism="Homo sapiens"),
        filtered_datasets=[
            GEODataset(accession="GSE317605", uid="123", title="Test"),
        ],
    )


def _make_mock_ncbi():
    client = MagicMock()
    client.fetch_family_soft_batch.return_value = {"GSE317605": FAMILY_SOFT_TWO_SAMPLES}
    return client


def _make_mock_llm(response_text: str):
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text=response_text)]
    client.messages.create.return_value = response
    return client


def test_skill_name():
    skill = SampleSelectorSkill(ncbi_client=_make_mock_ncbi())
    assert skill.name == "sample_selector"


def test_execute_builds_phase1_context_and_json():
    skill = SampleSelectorSkill(ncbi_client=_make_mock_ncbi())
    ctx = skill.execute(_make_context())

    assert "GSE317605" in ctx.sample_metadata
    assert len(ctx.sample_metadata["GSE317605"]) == 2

    compact = ctx.sample_selector_context["GSE317605"]
    assert compact["series_id"] == "GSE317605"
    assert compact["sample_count"] == 2
    assert compact["samples_with_supp_files"] == 1
    assert compact["samples_without_supp_files"] == 1

    compact_json = ctx.sample_selector_context_json["GSE317605"]
    parsed_json = json.loads(compact_json)
    assert parsed_json["series_id"] == "GSE317605"
    assert len(parsed_json["samples"]) == 2


def test_supplementary_files_are_compacted_to_file_names():
    skill = SampleSelectorSkill(ncbi_client=_make_mock_ncbi())
    ctx = skill.execute(_make_context())

    first = ctx.sample_selector_context["GSE317605"]["samples"][0]
    assert first["supplementary_files"] == ["GSM9474997_matrix.mtx.gz"]


def test_characteristics_are_normalized_to_lowercase_keys():
    skill = SampleSelectorSkill(ncbi_client=_make_mock_ncbi())
    ctx = skill.execute(_make_context())

    first = ctx.sample_selector_context["GSE317605"]["samples"][0]
    assert "characteristics" in first
    assert first["characteristics"]["library type"] == "mRNA"
    assert first["characteristics"]["tissue"] == "PBMC"


def test_preprocess_family_soft_directory(tmp_path):
    soft_path = tmp_path / "GSE317605_family.soft"
    soft_path.write_text(FAMILY_SOFT_TWO_SAMPLES)

    contexts = preprocess_family_soft_directory(
        input_dir=tmp_path,
        output_file=tmp_path / "phase1.json",
    )

    assert "GSE317605" in contexts
    assert contexts["GSE317605"]["sample_count"] == 2

    output = (tmp_path / "phase1.json").read_text()
    assert "\"GSE317605\"" in output


def test_select_samples_happy_path():
    metadata = {
        "series_id": "GSE317605",
        "samples": [
            {"gsm_id": "GSM9474997", "sample_title": "Patient 10-02_GEX timepoint T01 scRNAseq"},
            {"gsm_id": "GSM9475081", "sample_title": "Patient 10-02_ADT timepoint T01 scRNAseq"},
        ],
    }
    llm_output = json.dumps(
        {
            "is_false_positive": False,
            "download_strategy": "GSM_Level_Separated",
            "selected_samples": [
                {
                    "gsm_id": "GSM9475081",
                    "sample_title": "Patient 10-02_ADT timepoint T01 scRNAseq",
                    "modality_inferred": "ADT",
                }
            ],
            "reasoning": "ADT sample is explicitly labeled.",
        }
    )
    llm = _make_mock_llm(llm_output)

    result = select_samples(
        query="Extract all CITE-seq protein/ADT samples",
        metadata=metadata,
        llm_client=llm,
    )

    assert result["is_false_positive"] is False
    assert result["download_strategy"] == "GSM_Level_Separated"
    assert len(result["selected_samples"]) == 1
    assert result["selected_samples"][0]["gsm_id"] == "GSM9475081"
    assert result["selected_samples"][0]["modality_inferred"] == "ADT"

    kwargs = llm.messages.create.call_args.kwargs
    assert kwargs["temperature"] == 0.1

    debug_result = select_samples(
        query="Extract all CITE-seq protein/ADT samples",
        metadata=metadata,
        llm_client=llm,
        include_debug=True,
    )
    assert "raw_selector_output" in debug_result
    assert "result" in debug_result


def test_select_samples_accepts_markdown_wrapped_json():
    metadata = {
        "series_id": "GSE317605",
        "samples": [
            {"gsm_id": "GSM9475081", "sample_title": "Patient 10-02_ADT timepoint T01 scRNAseq"},
        ],
    }
    llm_output = """```json
{"is_false_positive":false,"download_strategy":"GSM_Level_Separated","selected_samples":[{"gsm_id":"GSM9475081","sample_title":"Patient 10-02_ADT timepoint T01 scRNAseq","modality_inferred":"ADT"}],"reasoning":"ok"}
```"""
    llm = _make_mock_llm(llm_output)

    result = select_samples(
        query="Extract ADT samples",
        metadata=metadata,
        llm_client=llm,
    )

    assert result["selected_samples"][0]["gsm_id"] == "GSM9475081"


def test_select_samples_false_positive_forces_empty_selection():
    metadata = {
        "series_id": "GSE280852",
        "samples": [
            {"gsm_id": "GSM8606565", "sample_title": "human liver, ctrl, P1"},
        ],
    }
    llm_output = json.dumps(
        {
            "is_false_positive": True,
            "download_strategy": "GSM_Level_Separated",
            "selected_samples": [
                {
                    "gsm_id": "GSM8606565",
                    "sample_title": "human liver, ctrl, P1",
                    "modality_inferred": "ADT",
                }
            ],
            "reasoning": "No ADT evidence.",
        }
    )
    llm = _make_mock_llm(llm_output)

    result = select_samples(
        query="Extract all CITE-seq protein/ADT samples",
        metadata=metadata,
        llm_client=llm,
    )

    assert result["is_false_positive"] is True
    assert result["download_strategy"] == "None"
    assert result["selected_samples"] == []


def test_select_samples_rejects_unknown_strategy():
    metadata = {
        "series_id": "GSE317605",
        "samples": [
            {"gsm_id": "GSM9475081", "sample_title": "Patient 10-02_ADT timepoint T01 scRNAseq"},
        ],
    }
    llm_output = json.dumps(
        {
            "is_false_positive": False,
            "download_strategy": "BadStrategy",
            "selected_samples": [
                {
                    "gsm_id": "GSM9475081",
                    "sample_title": "Patient 10-02_ADT timepoint T01 scRNAseq",
                    "modality_inferred": "ADT",
                }
            ],
            "reasoning": "bad strategy name",
        }
    )
    llm = _make_mock_llm(llm_output)

    with pytest.raises(SkillError):
        select_samples(
            query="Extract ADT samples",
            metadata=metadata,
            llm_client=llm,
        )


def test_heuristic_select_samples_returns_false_positive_when_no_adt():
    metadata = {
        "series_id": "GSE000001",
        "samples": [
            {"gsm_id": "GSM1", "sample_title": "control gex", "molecule": "polyA RNA"},
            {"gsm_id": "GSM2", "sample_title": "case gex", "molecule": "polyA RNA"},
        ],
    }
    result = heuristic_select_samples("Extract ADT", metadata)
    assert result["is_false_positive"] is True
    assert result["selected_samples"] == []
    assert result["download_strategy"] == "None"


def test_heuristic_select_samples_selects_adt_sample():
    metadata = {
        "series_id": "GSE000002",
        "samples": [
            {
                "gsm_id": "GSM1",
                "sample_title": "Patient ADT",
                "molecule": "protein",
                "supplementary_files": ["GSM1_ADT_matrix.mtx.gz"],
            },
            {"gsm_id": "GSM2", "sample_title": "Patient GEX", "molecule": "polyA RNA"},
        ],
    }
    result = heuristic_select_samples("Extract ADT", metadata)
    assert result["is_false_positive"] is False
    assert len(result["selected_samples"]) == 1
    assert result["selected_samples"][0]["gsm_id"] == "GSM1"

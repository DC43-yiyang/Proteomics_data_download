"""Tests for parse_family_soft() parser."""

from geo_agent.ncbi.parsers import parse_family_soft


# Minimal Family SOFT fixture with 2 samples (GEX + ADT)
FAMILY_SOFT_FIXTURE = """\
^SAMPLE = GSM9474997
!Sample_title = Patient 10-02_GEX timepoint T01 scRNAseq
!Sample_geo_accession = GSM9474997
!Sample_status = Public on Mar 01 2026
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = tissue: PBMC
!Sample_characteristics_ch1 = library type: mRNA
!Sample_characteristics_ch1 = patient: 10-02
!Sample_molecule_ch1 = polyA RNA
!Sample_library_source = transcriptomic
!Sample_description = Gene expression library for CITE-seq
!Sample_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/GSM9474nnn/GSM9474997/suppl/GSM9474997_barcodes.tsv.gz
!Sample_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/GSM9474nnn/GSM9474997/suppl/GSM9474997_features.tsv.gz
!Sample_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/GSM9474nnn/GSM9474997/suppl/GSM9474997_matrix.mtx.gz
^SAMPLE = GSM9475081
!Sample_title = Patient 10-02_ADT timepoint T01 scRNAseq
!Sample_geo_accession = GSM9475081
!Sample_status = Public on Mar 01 2026
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = tissue: PBMC
!Sample_characteristics_ch1 = library type: ADT
!Sample_characteristics_ch1 = patient: 10-02
!Sample_molecule_ch1 = protein
!Sample_library_source = other
!Sample_description = antibody-derived oligonucleotide library for CITE-seq
!Sample_supplementary_file = ftp://ftp.ncbi.nlm.nih.gov/geo/samples/GSM9475nnn/GSM9475081/suppl/GSM9475081_barcodes.tsv.gz
"""


def test_parse_family_soft_returns_two_samples():
    samples = parse_family_soft(FAMILY_SOFT_FIXTURE)
    assert len(samples) == 2


def test_parse_family_soft_gex_sample():
    samples = parse_family_soft(FAMILY_SOFT_FIXTURE)
    gex = samples[0]
    assert gex.accession == "GSM9474997"
    assert "_GEX" in gex.title
    assert gex.organism == "Homo sapiens"
    assert gex.molecule == "polyA RNA"
    assert gex.library_source == "transcriptomic"
    assert gex.characteristics["library type"] == "mRNA"
    assert gex.characteristics["tissue"] == "PBMC"
    assert len(gex.supplementary_files) == 3
    assert "Gene expression" in gex.description


def test_parse_family_soft_adt_sample():
    samples = parse_family_soft(FAMILY_SOFT_FIXTURE)
    adt = samples[1]
    assert adt.accession == "GSM9475081"
    assert "_ADT" in adt.title
    assert adt.organism == "Homo sapiens"
    assert adt.molecule == "protein"
    assert adt.library_source == "other"
    assert adt.characteristics["library type"] == "ADT"
    assert len(adt.supplementary_files) == 1
    assert "antibody" in adt.description


def test_parse_family_soft_empty_input():
    samples = parse_family_soft("")
    assert samples == []


def test_parse_family_soft_no_sample_blocks():
    # Series-level SOFT without ^SAMPLE lines
    soft = """\
^SERIES = GSE317605
!Series_title = Some series
!Series_overall_design = CITE-seq
"""
    samples = parse_family_soft(soft)
    assert samples == []


def test_parse_family_soft_supplementary_file_none():
    """Samples with supplementary_file = NONE should have empty list."""
    soft = """\
^SAMPLE = GSM0000001
!Sample_title = Test sample
!Sample_geo_accession = GSM0000001
!Sample_organism_ch1 = Homo sapiens
!Sample_molecule_ch1 = polyA RNA
!Sample_library_source = transcriptomic
!Sample_supplementary_file = NONE
"""
    samples = parse_family_soft(soft)
    assert len(samples) == 1
    assert samples[0].supplementary_files == []


def test_parse_family_soft_characteristics_without_colon():
    """Characteristics without key: value format."""
    soft = """\
^SAMPLE = GSM0000002
!Sample_title = Test sample 2
!Sample_geo_accession = GSM0000002
!Sample_organism_ch1 = Mus musculus
!Sample_molecule_ch1 = total RNA
!Sample_library_source = transcriptomic
!Sample_characteristics_ch1 = some_value_without_colon
"""
    samples = parse_family_soft(soft)
    assert len(samples) == 1
    assert "some_value_without_colon" in samples[0].characteristics

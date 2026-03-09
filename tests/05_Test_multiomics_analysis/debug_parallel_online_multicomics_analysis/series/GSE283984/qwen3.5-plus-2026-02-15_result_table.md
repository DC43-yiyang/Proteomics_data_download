# Multi-omics Annotation Results (per-series)

- model: `qwen3.5-plus-2026-02-15`
- generated_at_utc: `2026-03-06T03:46:30.727429+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | layers_present | status |
|---|---|---|---:|---|---|
| GSE283984 | healthy | peripheral blood | 3 | RNA, cell_label, protein_surface | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE283984 | GSM8675315 | PBMCs, mRNA-derived cDNA | RNA | BD Rhapsody 3' | BD Rhapsody Multi-modal | scRNA-seq | healthy | peripheral blood |  | 0.95 | library_type=mRNA, library_source=transcriptomic single cell, description=3' mRNA library |
| GSE283984 | GSM8675316 | PBMCs, ADT-derived cDNA | protein_surface | BD Rhapsody 3' | BD Rhapsody Multi-modal | CITE-seq | healthy | peripheral blood |  | 0.95 | library_type=ADT, molecule=protein, antibodies/tags=Anti-CD27 |
| GSE283984 | GSM8675317 | PBMCs, HTO-derived cDNA | cell_label | BD Rhapsody 3' | BD Rhapsody Multi-modal | HTO | healthy | peripheral blood |  | 0.95 | library_type=HTO, antibodies/tags=BD Human SMK, description=Cell Hashing library |
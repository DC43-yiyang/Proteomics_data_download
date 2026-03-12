# Multi-omics Annotation Results (per-series)

- model: `qwen-plus`
- generated_at_utc: `2026-03-10T20:18:04.287554+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE283984 | autoimmunity | PBMC | 3 | 4 | — | RNA, cell_label, protein_surface | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE283984 | GSM8675315 | PBMCs, mRNA-derived cDNA | RNA | 10x Chromium 3' | CITE-seq | scRNA-seq | autoimmunity | PBMC |  | 0.90 | overall_design: 'CD19+IgM+IgDlow/- B cells' in human peripheral blood, therapeutic target for autoimmunity |
| GSE283984 | GSM8675316 | PBMCs, ADT-derived cDNA | protein_surface | 10x Chromium 3' | CITE-seq | CITE-seq | autoimmunity | PBMC |  | 0.90 | library_type: ADT, antibodies listed, overall_design: combined with scRNA for multiomic profiling of BDL subset |
| GSE283984 | GSM8675317 | PBMCs, HTO-derived cDNA | cell_label | 10x Chromium 3' | CITE-seq | HTO | autoimmunity | PBMC |  | 0.90 | library_type: HTO, description: 'Cell Hashing library', overall_design: 'multiplex samples' across 3 donors + 1 control |
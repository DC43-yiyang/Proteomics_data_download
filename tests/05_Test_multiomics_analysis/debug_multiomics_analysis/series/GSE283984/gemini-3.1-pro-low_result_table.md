# Multi-omics Annotation Results (per-series)

- model: `gemini-3.1-pro-low`
- generated_at_utc: `2026-03-10T23:31:58.467452+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE283984 | Healthy | peripheral blood | 3 | 3 | — | RNA, cell_label, protein_surface | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE283984 | GSM8675315 | PBMCs, mRNA-derived cDNA | RNA | BD Rhapsody | CITE-seq | scRNA-seq | Healthy | peripheral blood |  | 0.95 | title, library type: mRNA, description: WTA; 3' mRNA library |
| GSE283984 | GSM8675316 | PBMCs, ADT-derived cDNA | protein_surface | BD Rhapsody | CITE-seq | CITE-seq | Healthy | peripheral blood |  | 0.95 | title, library type: ADT, antibodies/tags: Abseq, description |
| GSE283984 | GSM8675317 | PBMCs, HTO-derived cDNA | cell_label | BD Rhapsody | CITE-seq | HTO | Healthy | peripheral blood |  | 0.95 | title, library type: HTO, antibodies/tags: BD Human SMK Universal marker, description: Cell Hashing library |
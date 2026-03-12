# Multi-omics Annotation Results (per-series)

- model: `qwen-plus`
- generated_at_utc: `2026-03-10T20:18:04.287554+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE306022 | human immunodeficiency virus infection (HIV) | PBMC | 9 | 3 | 1:3 | RNA, TCR_VDJ, cell_label, protein_surface | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE306022 | GSM9191697 | Ci10004 CD8s cultured with various conditions - GEX and FB combined for multi demultiplexing pipeline [GEX] | RNA, protein_surface, cell_label | 10x Chromium 5' | CITE-seq | CITE-seq | human immunodeficiency virus infection (HIV) | PBMC |  | 0.95 | summary: HIV-specific CD8 T cells, characteristics: PBMC, description: feature barcoding library with GEX/ADT/HTO |
| GSE306022 | GSM9191698 | Ci10004 CD8s cultured with various conditions - GEX and FB combined for multi demultiplexing pipeline [FB] | protein_surface, cell_label | 10x Chromium 5' | CITE-seq | CITE-seq | human immunodeficiency virus infection (HIV) | PBMC |  | 0.90 | title: [FB], description: feature barcoding library with ADT/HTO, paired with GSM9191697 |
| GSE306022 | GSM9191699 | Ci10004 CD8s cultured with various conditions - TCR data | TCR_VDJ | 10x Chromium 5' | CITE-seq | TCR V(D)J | human immunodeficiency virus infection (HIV) | PBMC |  | 0.95 | title: TCR data, description: TCR library with cell barcode + V(D)J sequences, same sample ID Ci10004 |
| GSE306022 | GSM9191700 | Ci10074 CD8s cultured with various conditions - GEX and FB combined for multi demultiplexing pipeline [GEX] | RNA, protein_surface, cell_label | 10x Chromium 5' | CITE-seq | CITE-seq | human immunodeficiency virus infection (HIV) | PBMC |  | 0.95 | summary: HIV-specific CD8 T cells, characteristics: PBMC, description: feature barcoding library with GEX/ADT/HTO |
| GSE306022 | GSM9191701 | Ci10074 CD8s cultured with various conditions - GEX and FB combined for multi demultiplexing pipeline [FB] | protein_surface, cell_label | 10x Chromium 5' | CITE-seq | CITE-seq | human immunodeficiency virus infection (HIV) | PBMC |  | 0.90 | title: [FB], description: feature barcoding library with ADT/HTO, paired with GSM9191700 |
| GSE306022 | GSM9191702 | Ci10074 CD8s cultured with various conditions - TCR data | TCR_VDJ | 10x Chromium 5' | CITE-seq | TCR V(D)J | human immunodeficiency virus infection (HIV) | PBMC |  | 0.95 | title: TCR data, description: TCR library, same sample ID Ci10074 |
| GSE306022 | GSM9191703 | Ci10076 CD8s cultured with various conditions - GEX and FB combined for multi demultiplexing pipeline [GEX] | RNA, protein_surface, cell_label | 10x Chromium 5' | CITE-seq | CITE-seq | human immunodeficiency virus infection (HIV) | PBMC |  | 0.95 | summary: HIV-specific CD8 T cells, characteristics: PBMC, description: feature barcoding library with GEX/ADT/HTO |
| GSE306022 | GSM9191704 | Ci10076 CD8s cultured with various conditions - GEX and FB combined for multi demultiplexing pipeline [FB] | protein_surface, cell_label | 10x Chromium 5' | CITE-seq | CITE-seq | human immunodeficiency virus infection (HIV) | PBMC |  | 0.90 | title: [FB], description: feature barcoding library with ADT/HTO, paired with GSM9191703 |
| GSE306022 | GSM9191705 | Ci10076 CD8s cultured with various conditions - TCR data | TCR_VDJ | 10x Chromium 5' | CITE-seq | TCR V(D)J | human immunodeficiency virus infection (HIV) | PBMC |  | 0.95 | title: TCR data, description: TCR library, same sample ID Ci10076 |
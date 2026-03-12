# Multi-omics Annotation Results (per-series)

- model: `qwen-plus`
- generated_at_utc: `2026-03-10T20:18:04.287554+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE299415 | B-cell malignancy | PBMC | 4 | 2 | 1:2 | RNA, TCR_VDJ | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE299415 | GSM9038862 | preInfusion, GEX, 1 | RNA | 10x Chromium 5' | scRNA-seq + TCR V(D)J | scRNA-seq | B-cell malignancy | PBMC | CAR-T cell product | 0.95 | summary: anti-CD19 CAR-T in B-cell malignancies; characteristics: treatment=CAR-T infusion, cell type=T cells |
| GSE299415 | GSM938863 | preInfusion, GEX, 2 | RNA | 10x Chromium 5' | scRNA-seq + TCR V(D)J | scRNA-seq | B-cell malignancy | PBMC | CAR-T cell product | 0.95 | summary: anti-CD19 CAR-T in B-cell malignancies; characteristics: treatment=CAR-T infusion, cell type=T cells |
| GSE299415 | GSM9038864 | preInfusion, VDJ, 1 | TCR_VDJ | 10x Chromium 5' | scRNA-seq + TCR V(D)J | TCR V(D)J | B-cell malignancy | PBMC | CAR-T cell product | 0.95 | summary: clonotype tracking; title: VDJ; description: preInfusion_VDJ1; same donor as GSM9038862 |
| GSE299415 | GSM9038865 | preInfusion, VDJ, 2 | TCR_VDJ | 10x Chromium 5' | scRNA-seq + TCR V(D)J | TCR V(D)J | B-cell malignancy | PBMC | CAR-T cell product | 0.95 | summary: clonotype tracking; title: VDJ; description: preInfusion_VDJ2; same donor as GSM9038863 |
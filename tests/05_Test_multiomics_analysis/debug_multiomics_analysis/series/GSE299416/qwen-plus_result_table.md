# Multi-omics Annotation Results (per-series)

- model: `qwen-plus`
- generated_at_utc: `2026-03-10T20:18:04.287554+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE299416 | B-cell malignancy | PBMC | 9 | 3 | 1:3 | RNA, TCR_VDJ, protein_surface | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE299416 | GSM9038866 | postInfusion_GEX1 | RNA | 10x Chromium 5' | CITE-seq | scRNA-seq | B-cell malignancy | PBMC | tumor | 0.95 | summary: 'patients with B-cell malignancies', overall_design: 'CAR-T cell infusion', characteristics: 'treatment: CAR-T cell infusion' |
| GSE299416 | GSM9038867 | postInfusion_GEX2 | RNA | 10x Chromium 5' | CITE-seq | scRNA-seq | B-cell malignancy | PBMC | tumor | 0.50 | summary: 'patients with B-cell malignancies', overall_design: 'CAR-T cell infusion', characteristics: 'treatment: CAR-T cell infusion' |
| GSE299416 | GSM9038868 | postInfusion_GEX3 | RNA | 10x Chromium 5' | CITE-seq | scRNA-seq | B-cell malignancy | PBMC | tumor | 0.95 | summary: 'patients with B-cell malignancies', overall_design: 'CAR-T cell infusion', characteristics: 'treatment: CAR-T cell infusion' |
| GSE299416 | GSM9038869 | postInfusion_VDJ1 | TCR_VDJ | 10x Chromium 5' | CITE-seq | TCR V(D)J | B-cell malignancy | PBMC | tumor | 0.95 | summary: 'traced anti-CD19 CAR-T clonotypes', overall_design: 'CAR-T cells isolated post-infusion', title: 'VDJ1' |
| GSE299416 | GSM9038870 | postInfusion_VDJ2 | TCR_VDJ | 10x Chromium 5' | CITE-seq | TC V(D)J | B-cell malignancy | PBMC | tumor | 0.95 | summary: 'traced anti-CD19 CAR-T clonotypes', overall_design: 'CAR-T cells isolated post-infusion', title: 'VDJ2' |
| GSE299416 | GSM9038871 | postInfusion_VDJ3 | TCR_VDJ | 10x Chromium 5' | CITE-seq | TCR V(D)J | B-cell malignancy | PBMC | tumor | 0.95 | summary: 'traced anti-CD19 CAR-T clonotypes', overall_design: 'CAR-T cells isolated post-infusion', title: 'VDJ3' |
| GSE299416 | GSM9038872 | postInfusion_ADT1 | protein_surface | 10x Chromium 5' | CITE-seq | CITE-seq | B-cell malignancy | PBMC | tumor | 0.95 | overall_design: 'CITEseq for Dextramers, indicated surface proteins and TotalSeq-C anti-human hashtag antibodies', title: 'ADT1' |
| GSE299416 | GSM9038873 | postInfusion_ADT2 | protein_surface | 10x Chromium 5' | CITE-seq | CITE-seq | B-cell malignancy | PBMC | tumor | 0.95 | overall_design: 'CITEseq for Dextramers, indicated surface proteins and TotalSeq-C anti-human hashtag antibodies', title: 'ADT2' |
| GSE299416 | GSM9038874 | postInfusion_ADT3 | protein_surface | 10x Chromium 5' | CITE-seq | CITE-seq | B-cell malignancy | PBMC | tumor | 0.95 | overall_design: 'CITEseq for Dextramers, indicated surface proteins and TotalSeq-C anti-human hashtag antibodies', title: 'ADT3' |
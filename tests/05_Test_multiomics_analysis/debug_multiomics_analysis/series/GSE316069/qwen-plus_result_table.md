# Multi-omics Annotation Results (per-series)

- model: `qwen-plus`
- generated_at_utc: `2026-03-10T20:18:04.287554+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE316069 | ulcerative colitis (UC) | colon, PBMC | 14 | 6 | 1:2 | RNA, TCR_VDJ, cell_label | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE316069 | GSM9444084 | colon, gdT cells, batch 1 | RNA | FLASH-seq | scRNA-seq | RNA-seq | ulcerative colitis (UC) | colon | tumor | 0.90 | summary: ulcerative colitis, overall_design: intestinal biopsies from UC patients and healthy donors, title: colon |
| GSE316069 | GSM9444085 | colon, gdT cells, batch 2 | RNA | FLASH-seq | scRNA-seq | scRNA-seq | ulcerative colitis (UC) | colon | tumor | 0.90 | summary: ulcerative colitis, overall_design: intestinal biopsies from UC patients and healthy donors, title: colon |
| GSE316069 | GSM9444086 | PBMC, TCRgd Vd1,GEX, batch 1 | RNA | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | scRNA-seq | ulcerative colitis (UC) | PBMC |  | 0.95 | library name: PBMC_Vd1_10X5P_GEX_1, characteristics: tissue=PBMC, library_type=mRNA, description includes HD/UC donors |
| GSE316069 | GSM9444087 | PBMC, TCRgd Vd1, HTO, batch 1 | cell_label | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | HTO | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=HTO, molecule=protein, description: HTO info with HD/UC donors |
| GSE316069 | GSM9444088 | PBMC, TCRgd Vd1, TCR, batch 1 | TCR_VDJ | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | TCR V(D)J | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=TCR, molecule=polyA RNA, source_name=PBMC, description: PBMC_Vd1_10X5P_TCR_1 |
| GSE316069 | GSM9444089 | PBMC, TCRgd Vd1, GEX, batch 2 | RNA | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | scRNA-seq | ulcerative colitis (UC) | PBMC |  | 0.95 | library name: PBMC_Vd1_10X5P_GEX_2, characteristics: tissue=PBMC, library_type=mRNA |
| GSE316069 | GSM9444090 | PBMC, TCRgd Vd1, HTO, batch 2 | cell_label | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | HTO | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=HTO, description: PBMC_Vd1_10X5P_HTO_2, HTO info includes HD/UC donors |
| GSE316069 | GSM9444091 | PBMC, TCRgd Vd1, TCR, batch 2 | TCR_VDJ | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | TCR V(D)J | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=TCR, description: PBMC_Vd1_10X5P_TCR_2 |
| GSE316069 | SM9444092 | PBMC, TCRgd Vd2, GEX, batch 1 | RNA | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | scRNA-seq | ulcerative colitis (UC) | PBMC |  | 0.95 | library name: PBMC_Vd2_10X5P_GEX_1, tissue=PBMC, library_type=mRNA |
| GSE316069 | GSM9444093 | PBMC, TCRgd Vd2, HTO, batch 1 | cell_label | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | HTO | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=HTO, description: PBMC_Vd2_10X5P_HTO_1, HTO info includes HD/UC donors |
| GSE316069 | GSM9444094 | PBMC, TCRgd Vd2, TCR, batch 1 | TCR_VDJ | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | TCR V(D)J | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=TCR, description: PBMC_Vd2_10X5P_TCR_1 |
| GSE316069 | GSM9444095 | PBMC, TCRgd Vd2, GEX, batch 2 | RNA | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | scRNA-seq | ulcerative colitis (UC) | PBMC |  | 0.95 | library name: PBMC_Vd2_10X5P_GEX_2, tissue=PBMC |
| GSE316069 | GSM9444096 | PBMC, TCRgd Vd2, HTO, batch 2 | cell_label | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | HTO | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=HTO, description: PBMC_Vd2_10X5P_HTO_2 |
| GSE316069 | GSM9444097 | PBMC, TCRgd Vd2, TCR, batch 2 | TCR_VDJ | 10x Chromium 5' | multi-modal PBMC γδ T cell profiling | TCR V(D)J | ulcerative colitis (UC) | PBMC |  | 0.95 | library_type=TCR, description: PBMC_Vd2_10X5P_TCR_2 |
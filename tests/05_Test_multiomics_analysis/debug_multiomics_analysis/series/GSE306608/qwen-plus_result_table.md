# Multi-omics Annotation Results (per-series)

- model: `qwen-plus`
- generated_at_utc: `2026-03-10T20:18:04.287554+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE306608 | clear cell renal cell carcinoma (ccRCC) | kidney | 6 | 2 | 1:3 | RNA, cell_label, other, protein_surface | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE306608 | GSM9204556 | CITE-seq, K5 PDX, GEX | other | 10x Chromium 3' | CITE-seq | scRNA-seq | clear cell renal cell carcinoma (ccRCC) | tumor |  | 0.95 | disease state: ccRCC, tissue: Kidney PDX, library type: mRNA |
| GSE306608 | GSM9204557 | CITE-seq, K5 PDX, ADT | protein_surface | 10x Chromium 3' | CITE-seq | CITE-seq | clear cell renal cell carcinoma (ccRCC) | kidney | tumor | 0.95 | library type: ADT, molecule: protein, adt antibodies listed, same bio-sample as GSM9204556 |
| GSE306608 | GSM9204558 | CITE-seq, K5 PDX, HTO | cell_label | 10x Chromium 3' | CITE-seq | HTO | clear cell renal cell carcinoma (ccRCC) | kidney | tumor | 0.95 | library type: HTO, molecule: protein, hto: Hashtag 1, same bio-sample as GSM9204556 |
| GSE306608 | GSM9204559 | CITE-seq, K7 PDX, GEX | RNA | 10x Chromium 3' | CITE-seq | scRNA-seq | clear cell renal cell carcinoma (ccRCC) | kidney | tumor | 0.95 | disease state: ccRCC, tissue: Kidney PDX, library type: mRNA |
| GSE306608 | GSM9204560 | CITE-seq, K7 PDX, ADT | protein_surface | 10x Chromium 3' | CITE-seq | CITE-seq | clear cell renal cell carcinoma (ccRCC) | kidney | tumor | 0.95 | library type: ADT, molecule: protein, adt antibodies listed, same bio-sample as GSM9204559 |
| GSE306608 | GSM9201 | CITE-seq, K7 PDX, HTO | cell_label | 10x Chromium 3' | CITE-seq | HTO | clear cell renal cell carcinoma (ccRCC) | kidney | tumor | 0.95 | library type: HTO: protein, hto: Hashtag 1, same bio-sample as GSM9204559 |
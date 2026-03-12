# Multi-omics Annotation Results (per-series)

- model: `qwen-plus`
- generated_at_utc: `2026-03-10T20:18:04.287554+00:00`
- input: `/Users/yniu2/Project/Proteomics_data_download/tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json`

## Series Summary

| series_id | disease | tissue | samples | bio_samples | split | layers_present | status |
|---|---|---|---:|---:|---|---|---|
| GSE287976 | normal | peripheral blood | 12 | 6 | 1:2 | RNA, protein_surface | ok |

---

## Per-sample Annotations

| series_id | gsm_id | sample_title | measured_layers | platform | experiment | assay | disease | tissue | tissue_subtype | confidence | evidence |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| GSE287976 | GSM8756665 | Donor A pbmcs Gene Expression | RNA | 10x Chromium 3' | CITE-seq | scRNA-seq | normal | peripheral blood | sorted low-density leukocytes basophils | 0.95 | summary: basophil profiling, characteristics: peripheral blood, cell type: Sorted low-density leukocytes plus basophils |
| GSE287976 | GSM8756666 | Donor A pbmcs Surface Protein | protein_surface | 10x Chromium 3' | CITE-seq | CITE-seq | normal | peripheral blood | sorted low-density leukocytes plus basophils | 0.95 | title: Surface Protein, library_type: ADT, characteristics: same dataset number and cell type as GSM8756665 |
| GSE287976 | GSM8756667 | Donor B sorted basophils Gene Expression | RNA | 10x Chromium 3' | CITE-seq | scRNA-seq | normal | peripheral blood | sorted basophils | 0.95 | characteristics: peripheral blood, cell type: Sorted basophils, dataset number: 2 |
| GSE287976 | GSM8756668 | Donor B sorted basophils Surface Protein | protein_surface | 10x Chromium 3' | CITE-seq | CITE-seq | normal | peripheral blood | sorted basophils | 0.95 | same dataset number and cell type as GSM8756667, library_type: ADT |
| GSE287976 | GSM8756669 | Donor C MACS basophils Gene Expression | RNA | 10x Chromium 3' | CITE-seq | scRNA-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.95 | characteristics: peripheral blood, cell type: CCR3 enriched low-density leukocytes, dataset number: 3 |
| GSE287976 | GSM8756670 | Donor C MACS basophils_Surface_Protein | protein_surface | 10x Chromium 3' | CITEq | CITE-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.95 | same dataset number and cell type as GSM8756669, library_type: ADT |
| GSE287976 | GSM8756671 | Donor D1 MACS basophils_Gene_Expression | RNA | 10x Chromium 3' | CITE-seq | scRNA-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.95 | dataset number: 3, cell type: CCR3 enriched low-density leukocytes |
| GSE287976 | GSM8756672 | Donor D1 MACS basophils_Surface_Protein | protein_surface | 10x Chromium 3' | CITE-seq | CITE-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.95 | same dataset number and cell type as GSM8756671, library_type: ADT |
| GSE287976 | GSM8756673 | Donor D2 MACS basophils_Gene_Expression | RNA | 10x Chromium 3' | CITE-seq | scRNA-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.95 | dataset number: 3, cell type: CCR3 enriched low-density leukocytes |
| GSE287976 | GSM8756674 | Donor_D2_MACS_basophils_Surface_Protein | protein_surface | 10x Chromium 3' | CITE-seq | CITE-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.95 | same dataset number and cell type as GSM8756673, library_type: ADT |
| GSE287976 | GSM8756675 | DonorC_MACS_basophils_Gene_Expression_Long_read | RNA | FLT-seq (10x Genomics) | long-read scRNA-seq | scRNA-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.90 | description: FLT-seq from 10X genomics cDNA, same donor and cell type as GSM8756669/GSM8756670, dataset number: 4 |
| GSE287976 | GSM8756676 | DonorD1_MACS_basophils_Gene_Expression_Long_read | RNA | FLT-seq (10x Genomics) | long-read scRNA-seq | scRNA-seq | normal | peripheral blood | CCR3 enriched low-density leukocytes | 0.90 | description: FLT-seq from 10X genomics cDNA, same donor and cell type as GSM8756671/GSM8756672, dataset number: 4 |
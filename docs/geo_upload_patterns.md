# GEO Data Upload Patterns Analysis

## Background

GEO (Gene Expression Omnibus) enforces FASTQ/SRA submission but has minimal requirements for processed data. This leads to highly inconsistent data organization across datasets. Based on our database analysis (26 standalone series, 657 samples), we identified 5 upload pattern variants across 4 conceptual patterns.

> **DB stats as of 2026-03-12**: `data/geo_agent.db`, pipeline_run_id=1, 26 standalone series classified. Pattern classification stored in `series.upload_pattern` column (V3 migration). Implementation: `geo_agent/db/repository.py::classify_upload_patterns()`, test: `tests/07_Test_pattern_classification/run_pattern_classification.py`.

---

## Pattern 1: FASTQ-only

**Description:** Authors upload raw FASTQ files via SRA and provide no processed data at all. No supplementary files at either the Series or Sample level.

**Series-level files:** None
**Sample-level files:** None
**Processed data available:** No

**Example from DB:** Not directly observed in our current search results (our pipeline targets multi-omics processed data), but this is the most common pattern on GEO overall.

**Implications for download:**
- Cannot download any processed results
- Would require re-processing from raw FASTQ

---

## Pattern 2: Series-level Files Only

**Description:** Authors upload all processed data at the Series level. Individual Sample entries contain no supplementary files. This includes both single merged files and cases where per-sample files are dumped at series level (bypassing GEO's sample structure entirely).

**Series-level files:** Yes (one or many)
**Sample-level files:** None
**Processed data available:** Yes, but only accessible as a whole

**Examples from DB:**

| Series | Declared Samples | Series Files | Notes |
|--------|-----------------|--------------|-------|
| GSE266455 | 48 | 72 | Per-sample MTX triplets all dumped at series level |
| GSE267552 | 9 | 7 | |
| GSE283984 | 3 | 2 | |
| GSE291290 | 6 | 4 | |
| GSE294427 | 9 | 8 | |
| GSE309625 | 9 | 2 | |
| GSE313153 | 4 | 5 | |
| GSE316782 | 18 | 4 | |
| GSE320155 | 60 | 3 | 2× TAR archives + 1 feature CSV |

**Notable case — GSE266455:** 72 series-level files named per biological sample (e.g. `GSE266455_SCOPE_Samples_PID1052W0w1NOTHING_barcodes.tsv.gz`). Logically behaves like Pattern 3 (per-sample selective access is possible by filename parsing), but structurally everything is at the series level. Currently treated as Pattern 2 (requires manual intervention).

> **TODO:** GSE266455-style cases could be upgraded to a Pattern 3 download strategy by parsing series-level filenames to map files → biological samples (e.g. regex on sample name tokens in filename). Deferred — not worth a dedicated LLM inference step for now.

**Notable case — GSE320155:**
```
GSE320155_HCC_tumour_and_background_cellranger_aggr.tar.gz   730.4 Mb
GSE320155_Liver_and_PBMC_cellranger_aggr.tar.gz              650.7 Mb
GSE320155_feature_reference.csv.gz                           361 b
```

**Implications for download:**
- Must download Series-level file(s) to access any sample data
- Cannot selectively download individual samples via GSM accessions
- For GSE266455-style cases: **manual intervention required** (see TODO above)

---

## Pattern 3: Per-Sample Files (one GEO Sample = one biological sample)

**Description:** Each GEO Sample entry maps to one biological sample with its own supplementary files. Two sub-variants exist based on whether omic layers are merged or separate.

**Series-level files:** May or may not exist
**Sample-level files:** Yes, for every sample
**GEO Sample = Biological Sample:** Yes

### 3a: Merged multi-omic (pattern3_merged)

All omic layers of one bio-sample bundled under a single GSM. The GSM has multiple entries in `annotation_layer`.

| Series | Samples | With Files | Layers per GSM | Notes |
|--------|---------|-----------|----------------|-------|
| GSE207438 | 4 | 2 | 2 | GEX + ADT/HTO merged |
| GSE268991 | 56 | 28 | 1–2 | RNA + protein_surface merged for covered GSMs |
| GSE299416 | 9 | 3 | 1–2 | multi-layer for covered GSMs |
| GSE303197 | 25 | 5 | 1–2 | multi-layer for covered GSMs |
| GSE303984 | 102 | 34 | 1–2 | multi-layer for covered GSMs |
| GSE306022 | 9 | 6 | 2 | CITE-seq: RNA + protein + cell labels merged |
| GSE313894 | 68 | 68 | 1–3 | H5/CSV mixed, multi-layer |

**Implications:** Download target GSMs as a unit — cannot extract individual layers without post-download processing.

### 3b: Single-omic full coverage (pattern3_singleomic) — HIGHEST PRECISION

Each GSM carries exactly one layer, and every sample has files. Most precise download target — can select exactly the `protein_surface` GSMs.

| Series | Samples | With Files | Layer | Notes |
|--------|---------|-----------|-------|-------|
| GSE280852 | 6 | 6 | RNA | 10x triplets + series RAW.tar |
| GSE296447 | 8 | 8 | RNA + protein_surface | 10x triplets |
| GSE299415 | 4 | 4 | RNA + TCR_VDJ | 10x triplets |
| GSE306608 | 6 | 6 | RNA + protein_surface + cell_label | 10x triplets |
| GSE315668 | 42 | 42 | RNA + protein_surface + BCR_VDJ | 10x + other layers |

**Implications:** Ideal for selective download — pick exactly the `protein_surface` GSMs by accession.

---

## Pattern 4: Layer-Split (one biological sample = multiple GEO Samples)

**Description:** For multi-omics experiments, the author creates separate GEO Sample entries for each omic layer of the same biological sample. Coverage is always < 100% because some layers are FASTQ-only.

**Series-level files:** May or may not exist
**Sample-level files:** Yes, but each GSM contains only one omic layer
**GEO Sample = Biological Sample:** No — one biological sample → N GEO Samples

**Examples from DB (pattern4):**

| Series | Total GSMs | With Files | Missing Rate | Layers |
|--------|-----------|-----------|-------------|--------|
| GSE269123 | 28 | 21 (75%) | 25% | protein_surface, RNA, TCR_VDJ |
| GSE287976 | 12 | 2 (17%) | 83% | RNA, protein_surface |
| GSE305370 | 80 | 60 (75%) | 25% | RNA, protein_surface, chromatin |
| GSE316069 | 14 | 6 (43%) | 57% | RNA, cell_label, TCR_VDJ |
| GSE316096 | 18 | 6 (33%) | 67% | RNA, protein_surface, TCR_VDJ |

**Implications for download:**
- Identify `protein_surface` layer GSMs via `annotation_layer` table
- "Missing" GSMs (no supplementary files) are typically FASTQ-only layers — handled at runtime via `low_quality` flag
- Group GSMs by biological sample identity (encoded in sample title or characteristics) when multi-omic fusion is needed later

---

## ~~Pattern 5: Partial Upload~~ (Retired)

**Pattern 5 is no longer a static classification.** What was previously called "partial upload" is handled at runtime as a degraded state within Pattern 4:

- When a target `protein_surface` GSM in Pattern 4 has no supplementary files → flag `low_quality: true`
- Fall back to series-level integrated file if available
- If no series file either → set `protein_data_available: false`

Former Pattern 5 examples are now correctly classified as either `pattern3_merged` or `pattern4` depending on their `annotation_layer` structure.

---

## Summary Matrix

| Pattern | Series Files | Sample Files | GEO Sample = Bio Sample | Selective Download | Precision |
|---------|-------------|-------------|------------------------|-------------------|-----------|
| 1. FASTQ-only | No | No | Yes | N/A (raw only) | — |
| 2. Series-level only | Yes (1–72+) | No | Yes | No — whole series only | Low |
| 3a. Per-sample merged | Optional | Yes (all) | Yes | Yes — by GSM (bundle) | Medium — all layers bundled |
| 3b. Per-sample single-omic | Optional | Yes (all) | Yes | **Yes — by GSM + layer** | **Highest — full coverage, exact layer** |
| 4. Layer-split | Optional | Yes (per layer) | No — 1 bio → N GSM | Yes — by protein_surface GSM | High — but may have FASTQ-only layers |
| 5. ~~Partial upload~~ | — | — | — | Retired — see low_quality flag below | — |

> **Pattern 5 retired:** Irregular partial upload is no longer a static classification. It is handled at runtime: when a target GSM (e.g. `protein_surface` layer in Pattern 4) has no supplementary files, the series is flagged `low_quality: true` and falls back to the series-level integrated file if available, or `protein_data_available: false` otherwise.

## DB-based Pattern Classification Rules

### Old approach (structural signals only — insufficient)

```python
# Given per series: series_files, actual_samples, samples_with_files

if series_files == 0 and actual_samples == 0:
    pattern = "unknown / super-series / not parsed"
elif samples_with_files == 0 and series_files > 0:
    pattern = "Pattern 2 (series-level only)"
elif samples_with_files == actual_samples:
    pattern = "Pattern 3 (per-sample, all covered)"
elif samples_with_files < actual_samples:
    # Could be Pattern 4, Pattern 5, or both — cannot distinguish
    pattern = "Pattern 4+5 (ambiguous)"
```

**Problem:** The coverage ratio alone cannot distinguish Pattern 3 from Pattern 4, nor Pattern 4 from Pattern 5. A series with 50% sample coverage could be Pattern 4 (layer-split, systematic) or Pattern 5 (random partial upload).

### Revised approach: annotation_layer as primary signal

**Core principle: file location determines download strategy. Annotation is auxiliary.**

Priority order:
1. **Where are the files?** (structural — from `sample_supplementary_file` + `series_supplementary_file`)
2. **What is the per-GSM layer structure?** (from `annotation_layer` — only consulted when sample-level files exist)

The key insight for distinguishing Pattern 3 vs Pattern 4:
- **Pattern 3 (merged) signal:** A single GSM has **multiple layers** (e.g. GSM_A → `RNA + protein_surface`) — all omic layers bundled under one sample entry.
- **Pattern 3 (single-omic) signal:** Every GSM has exactly **one layer**, full coverage — most precise download target.
- **Pattern 4 signal:** Different GSMs each carry a **single distinct layer** (e.g. GSM_A → `RNA`, GSM_B → `protein_surface`) — layers split across separate sample entries, coverage < 100%.

```python
# Step 1: file location — always checked first
if samples_with_files == 0 and series_files == 0:
    pattern = "Pattern 1"  # FASTQ-only, no processed data
elif samples_with_files == 0 and series_files > 0:
    pattern = "Pattern 2"  # all files at series level
    # NOTE: annotation_layer may show multi-layer GSMs (e.g. GSE291290, GSE316782)
    # but file location takes priority — still Pattern 2, download integrated file

# Step 2: sample-level files exist — use annotation_layer to distinguish
else:
    any_gsm_has_multiple_layers = any(c > 1 for c in gsm_layer_counts.values())
    all_gsms_covered = (samples_with_files == actual_samples)

    if any_gsm_has_multiple_layers:
        pattern = "Pattern 3 (merged)"    # multi-omic bundled per GSM
    elif all_gsms_covered:
        pattern = "Pattern 3 (single-omic)"  # MOST PRECISE — full coverage, one layer per GSM
    else:
        pattern = "Pattern 4 (layer-split)"  # systematic layer split, coverage < 100%

# Pattern 5 is retired as a static class — handled at runtime via low_quality flag
```

### Download strategy per pattern

| Pattern | Protein data available | Strategy | Precision |
|---------|----------------------|----------|-----------|
| 1 FASTQ-only | No | Mark skip | — |
| 2 Series-level | Maybe | Download whole series integrated file | Low |
| 3 Merged | Yes (bundled) | Download target GSMs as a unit | Medium |
| 3 Single-omic | Yes (exact) | **Download protein_surface GSMs only** | **Highest** |
| 4 Layer-split | Yes (ADT GSMs) | Download protein_surface layer GSMs only | High |
| Runtime: low_quality | Degraded | Fall back to series file, or mark protein_data_available: false | — |

### Runtime low_quality flag (replaces Pattern 5)

When processing Pattern 4 series at download time: if the target `protein_surface` GSM has no supplementary files (FASTQ-only layer), do not abort — instead:
1. Flag the series as `low_quality: true` in the manifest
2. Fall back to series-level integrated file if available
3. If no series file either → set `protein_data_available: false`

This handles irregular partial uploads without a dedicated static classification.

### Validation results (pipeline_run_id=1, 26 standalone series)

Validated against DB on 2026-03-12 using `annotation_layer` + `sample_supplementary_file` + `series_supplementary_file`:

| Pattern | Count | Series |
|---------|-------|--------|
| Pattern 2 | 9 | GSE266455, GSE267552, GSE283984, GSE291290, GSE294427, GSE309625, GSE313153, GSE316782, GSE320155 |
| Pattern 3 (merged) | 7 | GSE207438, GSE268991, GSE299416, GSE303197, GSE303984, GSE306022, GSE313894 |
| Pattern 3 (single-omic) | 5 | GSE280852, GSE296447, GSE299415, GSE306608, GSE315668 |
| Pattern 4 (layer-split) | 5 | GSE269123, GSE287976, GSE305370, GSE316069, GSE316096 |
| Pattern 1 | 0 | (none in this CITE-seq search — expected) |

> Note: GSE291290, GSE294427, GSE316782 have multi-layer GSM annotations but zero sample-level files → correctly classified as Pattern 2. File location takes priority over annotation structure.

### Known TODOs

> **TODO — GSE266455-style (Pattern 2 variant):** Series-level files named per bio-sample could support selective download via filename parsing (regex mapping filename tokens → sample identity). Currently treated as Pattern 2 (manual intervention). Deferred until enough similar cases justify the effort.

> **TODO — `cell_label` layer ambiguity:** In Pattern 4 series, some GSMs are annotated as `cell_label` layer because the LLM lacks sufficient context from the GSM metadata alone (e.g. GSM6287634 in GSE207438 → `protein_surface + cell_label`). Joining `annotation_layer` with `sample` (via `library_source`, `molecule`, `description` fields) provides the missing context to resolve whether `cell_label` is a true standalone layer or an artifact of merged ADT+HTO data. Deferred — can be resolved via a post-processing refinement step over the DB.

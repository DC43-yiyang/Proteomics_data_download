# Developer note: Family SOFT field analysis — real-world findings

> **Date**: 2026-03-03
> **Context**: After implementing `fetch_family_soft()` and testing against 10 real CITE-seq series

## Test corpus

| GSE | Samples | File size | Library type distribution |
|-----|---------|-----------|--------------------------|
| GSE317605 | 168 | 918K | 84 GEX + 84 ADT |
| GSE268991 | 56 | 230K | GEX (5'GEX) + Surface (ADT) + VDJ (TCR) |
| GSE306608 | 6 | 19K | 2 GEX + 2 ADT + 2 HTO |
| GSE313153 | 4 | 19K | 2 RNA + 2 ADT |
| GSE283984 | 3 | 12K | 1 mRNA + 1 ADT + 1 HTO |
| GSE269123 | 28 | 83K | GEX + ADT + gdTCR + abTCR |
| GSE303197 | 25 | 142K | mRNA + ADT/HTO mixed + TCR |
| GSE280852 | 6 | 16K | All polyA RNA (pure scRNA-seq, no CITE-seq sub-libraries) |
| GSE320155 | 60 | 225K | 20 GEX + 20 ADT + 20 TCR |
| GSE318420 | 210 | 866K | GEX + ADT mixed |

## Key findings

### 1. GEO search itself returns false positives

GSE280852 contains **only scRNA-seq** (all 6 samples are polyA RNA) — there is no CITE-seq sub-library at all. Yet GEO's search API returned it in response to a CITE-seq query.

**Implication**: We cannot assume that all series returned by `esearch` are genuine CITE-seq datasets. The search engine matches keywords loosely (e.g. the study may mention "CITE-seq" in the summary or related literature without actually containing CITE-seq data). This makes the LLM classification step even more important — it can detect "this series has no ADT samples at all" and flag it, rather than silently including it in download lists.

### 2. Some series have no per-sample supplementary files

GSE320155 has `!Sample_supplementary_file_1 = NONE` for all 60 samples. The actual data files are uploaded at the Series level as aggregated CellRanger outputs (e.g. `Liver_and_PBMC_cellranger_aggr.gz`), not per-GSM.

**Implication**: The DownloadSkill cannot rely solely on per-sample FTP links from Family SOFT. It must also handle Series-level bundled files (`_RAW.tar`, `_cellranger_aggr.gz`, etc.). When `selected_samples` points to GSMs with no supplementary files, the download logic needs to fall back to the Series-level supplementary file list.

### 3. Naming conventions are wildly inconsistent — LLM is essential

Across just 10 series, the naming patterns for the same library type vary dramatically:

| Library type | Observed naming variants |
|---|---|
| GEX | `_GEX` (GSE317605), `, GEX` (GSE320155), `_RNA` (GSE313153), `_mRNA` (GSE283984), `5'GEX` (GSE268991) |
| ADT | `_ADT` (GSE317605), `, ADT` (GSE320155), `Surface` (GSE268991), `ADT/HTO mixed` (GSE303197) |
| TCR | `_VDJ` (GSE317605 title), `library type: TCR` (GSE320155 characteristics), `gdTCR` / `abTCR` (GSE269123) |
| HTO | `_HTO` (GSE306608), `ADT/HTO mixed` (GSE303197) |

The `characteristics` field is equally inconsistent: some use `library type: mRNA`, others `library type: ADT`, others don't tag library type at all. The `molecule` field varies between `polyA RNA`, `protein`, `total RNA`, `cDNA`.

**Conclusion**: Rule-based parsing would require an ever-growing list of patterns that still can't cover all cases. LLM-based classification is the correct approach — it can reason about all available signals (title, characteristics, molecule, library_source, description, series-level overall_design) simultaneously and handle novel naming conventions without code changes.

## Impact on design

These findings reinforce three design decisions in `docs/LLM_sample_selector.md`:

1. **LLM classification is not optional** — it's the only reliable way to handle the variability.
2. **SampleSelectorSkill should also detect false-positive series** (TODO — not yet implemented) — if LLM classifies all samples as GEX with no ADT/TCR, the series should be flagged as "likely not a true CITE-seq dataset". Current implementation only classifies individual samples; series-level validation is planned as a post-classification check (addresses Finding 1).
3. **DownloadSkill must support both per-GSM and Series-level file retrieval** — `supplementary_file = NONE` is a common pattern (addresses Finding 2).

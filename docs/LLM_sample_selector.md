# LLM Sample Selector

> **Status**: Implemented
> **Updated**: 2026-03-03
> **Code**: `geo_agent/skills/sample_selector.py`
> **Spec**: `geo_agent/skills/sample_selector.md`

---

## 1. Problem

A single CITE-seq Series contains multiple library types as separate GSM samples. GSE317605 has 168 samples: 84 GEX + 84 ADT. If a researcher only needs ADT data, they need to know *which* GSMs are ADT before downloading.

The pipeline's Series SOFT (`targ=self`) only has Series-level metadata — no sample titles, no molecule fields, no per-sample FTP links. **Family SOFT** (`targ=gsm`) has everything, but its naming conventions are wildly inconsistent across uploaders.

### Why rules don't work — real data from 10 series

| Library type | Observed naming variants (10 series) |
|---|---|
| GEX | `_GEX`, `, GEX`, `_RNA`, `_mRNA`, `5'GEX`, `gene expression` |
| ADT | `_ADT`, `, ADT`, `Surface`, `ADT/HTO mixed` |
| TCR | `_VDJ`, `library type: TCR`, `gdTCR`, `abTCR` |
| HTO | `_HTO`, `ADT/HTO mixed` |

Rule-based parsing cannot scale. LLM handles this naturally.

---

## 2. Solution

```
FilterSkill output (GSE list)
        │
        ▼
  SampleSelectorSkill
    ├─ fetch Family SOFT per GSE (targ=gsm)
    ├─ parse sample-level metadata (GEOSample)
    ├─ compress → JSON prompt → LLM classifies each GSM
    └─ filter by target_library_types
        │
        ▼
  Selection Report (Markdown)
    ├─ per-GSE sample classification table
    ├─ per-GSM download links (FTP)
    └─ needs_review flags for ambiguous samples
```

**Goal**: Run the selector, output a detailed report containing:
- Which database (GSE accession)
- Which samples to use (GSM accessions + library type + confidence)
- Download links (per-sample FTP URLs from supplementary_files)
- Flagged samples needing human review

The skill does **not** download files — it produces an actionable report.

---

## 3. Data flow

### Input signals per sample (from Family SOFT)

| Field | Example (GEX) | Example (ADT) |
|---|---|---|
| `title` | `Patient 10-02_GEX timepoint T01 scRNAseq` | `Patient 10-02_ADT timepoint T01 scRNAseq` |
| `characteristics` | `library type: mRNA` | `library type: ADT` |
| `molecule` | `polyA RNA` | `protein` |
| `library_source` | `transcriptomic` | `other` |
| `description` | `Gene expression library` | `antibody-derived oligonucleotide` |
| `supplementary_files` | 3 FTP URLs (barcodes/features/matrix) | 3 FTP URLs |

### LLM classification

Model: **Claude Haiku** (`claude-haiku-4-5-20251001`) — fast, cheap, sufficient for extraction tasks.

Categories: `GEX` | `ADT` | `TCR` | `BCR` | `HTO` | `ATAC` | `OTHER`

Signal priority:
```
characteristics > molecule > library_source > title > description
```

Confidence: 0.9+ (multiple signals agree) → 0.7–0.9 (partial match) → <0.7 (ambiguous, `needs_review=True`)

### Output: `context.selected_samples`

```python
{
    "GSE317605": [
        SampleSelection(
            accession="GSM9475081",
            library_type="ADT",
            confidence=0.98,
            reasoning="title=_ADT, molecule=protein, library_source=other",
            needs_review=False,
            supplementary_files=[
                "ftp://...GSM9475081_barcodes.tsv.gz",
                "ftp://...GSM9475081_features.tsv.gz",
                "ftp://...GSM9475081_matrix.mtx.gz",
            ],
        ),
        # ... 83 more ADT samples
    ]
}
```

---

## 4. Real-world test corpus (10 CITE-seq series, 566 samples)

| GSE | Samples | Library types | Notes |
|-----|---------|---------------|-------|
| GSE317605 | 168 | 84 GEX + 84 ADT | Clean `_GEX`/`_ADT` naming, characteristics tagged |
| GSE268991 | 56 | GEX + ADT + TCR | Uses `5'GEX` / `Surface` — non-standard naming |
| GSE306608 | 6 | 2 GEX + 2 ADT + 2 HTO | Small, clean |
| GSE313153 | 4 | 2 RNA + 2 ADT | Uses `_RNA` instead of `_GEX` |
| GSE283984 | 3 | 1 mRNA + 1 ADT + 1 HTO | Uses `_mRNA` |
| GSE269123 | 28 | GEX + ADT + gdTCR + abTCR | TCR split into gamma-delta vs alpha-beta |
| GSE303197 | 25 | mRNA + ADT/HTO mixed + TCR | Combined ADT+HTO in single samples |
| GSE280852 | 6 | All polyA RNA (no ADT) | **False positive** — GEO search returned it for CITE-seq but it's pure scRNA-seq |
| GSE320155 | 60 | 20 GEX + 20 ADT + 20 TCR | `supplementary_file = NONE` for all — data is Series-level only |
| GSE318420 | 210 | GEX + ADT mixed | Largest dataset |

### Key findings

1. **GEO returns false positives** — GSE280852 has zero CITE-seq sub-libraries. The LLM can detect this (all samples = GEX, no ADT) and flag it.

2. **Some series have no per-sample files** — GSE320155 has `supplementary_file = NONE` for all 60 GSMs. Data lives at Series level as aggregated CellRanger output. The report should note this.

3. **Naming is chaotic** — The same library type has 5+ naming variants across 10 series. This is exactly why LLM classification is the right approach.

---

## 5. Cost

| Component | Per series | 300 series |
|---|---|---|
| Input tokens | ~3,900 | ~1.2M |
| Output tokens | ~5,000 | ~1.5M |
| **Haiku cost** | ~$0.001 | **~$0.30** |

Negligible. Even Sonnet stays under $10 for 300 series.

---

## 6. Error handling

| Scenario | Handling |
|---|---|
| Family SOFT fetch fails | Skip series, log to `context.errors` |
| Family SOFT is empty | Skip series, log to `context.errors` |
| LLM returns invalid JSON | Retry 1x; still fails → skip series |
| Unknown `library_type` | Map to `OTHER`, set `needs_review=True` |
| Confidence < threshold | Set `needs_review=True`, keep in results |
| `supplementary_file = NONE` | Keep in report, note "Series-level files only" |

---

## 7. Usage

### CLI

```bash
geo-agent search \
    --data-type "CITE-seq" \
    --organism "Homo sapiens" \
    --max-results 10 \
    --library-type GEX \
    --library-type ADT
```

### debug_run.py

```python
FETCH_FAMILY_SOFT = True          # Parse samples without LLM (verification mode)
FAMILY_SOFT_DEBUG_DIR = "debug_family_soft/"  # Save raw .soft files
```

### Programmatic

```python
from geo_agent.skills.sample_selector import SampleSelectorSkill
import anthropic

skill = SampleSelectorSkill(
    ncbi_client=client,
    llm_client=anthropic.Anthropic(api_key="..."),
    confidence_threshold=0.7,
)
context.target_library_types = ["ADT"]
context = skill.execute(context)

# Generate report from context.selected_samples
for acc, selections in context.selected_samples.items():
    for s in selections:
        print(f"{acc} → {s.accession} [{s.library_type}] conf={s.confidence:.2f}")
        for url in s.supplementary_files:
            print(f"    {url}")
```

---

## 8. Files

| File | Role |
|---|---|
| `geo_agent/models/sample.py` | `GEOSample`, `SampleSelection` dataclasses |
| `geo_agent/models/context.py` | `target_library_types`, `sample_metadata`, `selected_samples` on PipelineContext |
| `geo_agent/ncbi/client.py` | `fetch_family_soft()`, `fetch_family_soft_batch()` |
| `geo_agent/ncbi/parsers.py` | `parse_family_soft()` |
| `geo_agent/skills/sample_selector.py` | `SampleSelectorSkill` |
| `geo_agent/skills/sample_selector.md` | Skill spec (classification rules, validation criteria) |
| `geo_agent/config.py` | `anthropic_api_key`, `llm_model` |
| `geo_agent/cli.py` | `--library-type` flag |
| `tests/test_parse_family_soft.py` | Parser tests (7 cases) |
| `tests/test_sample_selector.py` | Skill tests with mocked NCBI + LLM (12 cases) |

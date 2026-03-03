# SampleSelectorSkill

## 1. Overview

Classifies GEO samples (GSMs) within each filtered Series by library type using an LLM. Given a Series with mixed library types (e.g. GEX + ADT + TCR), this skill identifies which samples belong to which category and selects the ones matching the user's target.

**Code location**: `geo_agent/skills/sample_selector.py` → `SampleSelectorSkill`

**Why LLM instead of rules?** GEO sample naming is highly inconsistent across uploaders. The same library type can appear as `_GEX`, `_RNA`, `_transcriptome`, `_3prime`, or have no naming convention at all. Characteristics fields vary too: `library type: mRNA` vs `molecule: cDNA` vs nothing. Rule-based parsing cannot scale; LLM handles this variability naturally.

## 2. Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ncbi_client` | `NCBIClient` | — | For fetching Family SOFT via `fetch_family_soft_batch()` |
| `llm_client` | `anthropic.Anthropic` | — | Anthropic SDK client instance |
| `model` | `str` | `"claude-haiku-4-5-20251001"` | LLM model identifier |
| `confidence_threshold` | `float` | `0.7` | Below this → `needs_review=True` |

`NCBIClient` is configured via `load_config()` in `geo_agent/config.py`.
`anthropic.Anthropic` is initialized with `ANTHROPIC_API_KEY` from `.env`.

## 3. PipelineContext input/output

### Input

| Field | Type | Required | Source |
|-------|------|----------|--------|
| `filtered_datasets` | `list[GEODataset]` | Yes | FilterSkill output |
| `target_library_types` | `list[str]` | Yes | CLI `--library-type` or caller (default `["GEX"]`) |

### Output

| Field | Type | Description |
|-------|------|-------------|
| `sample_metadata` | `dict[str, list[GEOSample]]` | accession → all parsed samples from Family SOFT |
| `selected_samples` | `dict[str, list[SampleSelection]]` | accession → samples matching `target_library_types` |

## 4. LLM classification rules

### 4.1 Categories

| Category | Definition | Typical signals |
|----------|------------|-----------------|
| **GEX** | Gene expression (scRNA-seq) | title: `_GEX`, `_RNA`, `_transcriptome`, `_3prime`; characteristics: `library type: mRNA`; molecule: `polyA RNA`, `total RNA`; library_source: `transcriptomic` |
| **ADT** | Antibody-derived tags (protein) | title: `_ADT`, `_protein`, `_AbSeq`, `_TotalSeq`; characteristics: `library type: ADT`; molecule: `protein`; library_source: `other`; description: `antibody-derived oligonucleotide` |
| **TCR** | T-cell receptor repertoire | title: `_TCR`, `_VDJ_T`; characteristics: `library type: TCR`; molecule: `genomic DNA` or `cDNA`; library_source: `genomic`; description: `TCR` |
| **BCR** | B-cell receptor repertoire | title: `_BCR`, `_VDJ_B`; characteristics: `library type: BCR`; molecule: `genomic DNA`; description: `BCR` |
| **HTO** | Hashtag oligos (multiplexing) | title: `_HTO`, `_hashtag`; characteristics: `library type: HTO`; description: `hashtag`, `cell hashing` |
| **ATAC** | Chromatin accessibility | title: `_ATAC`; characteristics: `library type: ATAC`; molecule: `genomic DNA`; library_source: `genomic` |
| **OTHER** | Anything not matching above | Fallback; always assigned with low confidence |

### 4.2 Signal priority

When signals conflict, the LLM should prioritize in this order:

```
characteristics > molecule > library_source > title > description > overall_design
```

Rationale: `characteristics` is the most explicit structured field (e.g. `library type: ADT`); `title` is free-text and sometimes misleading (e.g. an ADT sample may still say "scRNAseq" in the title).

### 4.3 Confidence standards

| Confidence | When to use |
|------------|-------------|
| **0.9 – 1.0** | Multiple signals agree (e.g. title has `_GEX`, molecule is `polyA RNA`, library_source is `transcriptomic`) |
| **0.7 – 0.9** | One strong signal present (e.g. characteristics says `library type: ADT` but title is ambiguous) |
| **0.5 – 0.7** | Weak or indirect signals only (e.g. only title contains a partial hint like `_RNA`) |
| **< 0.5** | No clear signal; classify as `OTHER` |

Samples with confidence below `confidence_threshold` (default 0.7) are marked `needs_review=True`.

## 5. Validation criteria

### 5.1 Correctness checklist

For any classified series, verify:

- [ ] Every GSM in the Family SOFT appears in the output (no samples dropped)
- [ ] Each GSM is assigned exactly one `library_type`
- [ ] Paired samples from the same patient/timepoint have different library types (e.g. Patient 10-02 should have one GEX + one ADT, not two GEX)
- [ ] `confidence` values are consistent (clear signals → high, ambiguous → low)
- [ ] `supplementary_files` are carried over from the parsed sample metadata

### 5.2 Verification example: GSE317605

This series contains 168 samples: 84 GEX + 84 ADT.

| Sample | Expected type | Key signals | Expected confidence |
|--------|---------------|-------------|---------------------|
| GSM9474997 `Patient 10-02_GEX timepoint T01 scRNAseq` | GEX | title: `_GEX`; characteristics: `library type: mRNA`; molecule: `polyA RNA`; library_source: `transcriptomic` | ≥ 0.9 |
| GSM9475081 `Patient 10-02_ADT timepoint T01 scRNAseq` | ADT | title: `_ADT`; characteristics: `library type: ADT`; molecule: `protein`; library_source: `other`; description: `antibody-derived oligonucleotide` | ≥ 0.9 |

Expected result summary:
- 84 samples classified as GEX, all confidence ≥ 0.9
- 84 samples classified as ADT, all confidence ≥ 0.9
- 0 samples classified as OTHER
- 0 samples with `needs_review=True`

## 6. AI Agent usage guide

When debugging or invoking this skill manually (e.g. from Claude Code or a script), follow these steps:

### Step 1: Ensure prerequisites

```python
from geo_agent.config import load_config
from geo_agent.ncbi.client import NCBIClient

config = load_config()
client = NCBIClient(api_key=config.api_key, email=config.email)
```

### Step 2: Create LLM client

```python
import anthropic

llm_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
```

### Step 3: Instantiate skill

```python
from geo_agent.skills.sample_selector import SampleSelectorSkill

skill = SampleSelectorSkill(
    ncbi_client=client,
    llm_client=llm_client,
    model=config.llm_model,          # default: claude-haiku-4-5-20251001
    confidence_threshold=0.7,
)
```

### Step 4: Prepare context

```python
from geo_agent.models.context import PipelineContext
from geo_agent.models.query import SearchQuery

context = PipelineContext(
    query=SearchQuery(data_type="CITE-seq", organism="Homo sapiens"),
    filtered_datasets=[...],          # from FilterSkill
    target_library_types=["ADT"],     # which types to select
)
```

### Step 5: Execute

```python
context = skill.execute(context)
```

### Step 6: Inspect results

```python
for accession, selections in context.selected_samples.items():
    print(f"\n{accession}: {len(selections)} samples selected")
    for s in selections[:3]:
        print(f"  {s.accession} → {s.library_type} (confidence={s.confidence:.2f})")
        if s.needs_review:
            print(f"    ⚠ NEEDS REVIEW: {s.reasoning}")
```

### Step 7: Check for issues

```python
# Low-confidence samples across all series
for acc, selections in context.selected_samples.items():
    flagged = [s for s in selections if s.needs_review]
    if flagged:
        print(f"{acc}: {len(flagged)} samples need review")
```

## 7. Error handling

| Scenario | Handling |
|----------|----------|
| Family SOFT fetch fails (HTTP error) | Log warning, skip series, add to `context.errors` |
| Family SOFT is empty or unparseable | Skip series, flag in `context.errors` |
| LLM returns invalid JSON | Retry once with stricter prompt; if still fails, skip series and log |
| LLM returns unknown `library_type` | Map to `"OTHER"`, set `needs_review=True` |

## 8. Pipeline position

- **Depends on**: FilterSkill (reads `filtered_datasets`)
- **Followed by**: DownloadSkill (future; reads `selected_samples` to get per-GSM FTP URLs)

```
[GEOSearchSkill] → [ReportSkill] → [FilterSkill] → [SampleSelectorSkill] → [DownloadSkill]
```

## Requirements

- Network access (GEO acc.cgi for Family SOFT + Anthropic API for LLM)
- `ANTHROPIC_API_KEY` in `.env`
- Optional: `LLM_MODEL` in `.env` to override default model

## Performance notes

- Family SOFT fetch: one request per series to GEO acc.cgi (0.25s spacing); response is 5K–20K lines depending on sample count
- LLM call: ~1–2s per series (Haiku); ~3K input tokens + ~5K output tokens for 168 samples
- Total for 317 series: ~80s SOFT fetch + ~10min LLM calls (sequential) or ~2min (concurrent)

# LLM Sample Selector — Design Plan

> **Status**: Proposed (not yet implemented)
> **Created**: 2026-03-02
> **Target**: Phase 3.5 — between FilterSkill and DownloadSkill
> **Related**: `docs/Architecture.md`, `docs/developer_notes_geo_superseries_subseries.md`

---

## 1. Problem statement

### 1.1 What works today

The current pipeline operates at the **Series (GSE) level**:

```
SearchQuery → esearch (UIDs) → esummary (GEODataset) → Series SOFT (overall_design)
    → ReportSkill → FilterSkill → ranked list of GSE accessions
```

After FilterSkill, we know **which Series are relevant** (e.g. "GSE317605 is a CITE-seq study on biliary cancer"). This is sufficient for search and reporting.

### 1.2 What breaks when we try to download

A single CITE-seq Series typically contains **multiple library types** as separate GSM samples:

| Library type | What it is | Example title in GSE317605 |
|---|---|---|
| **GEX** | Gene expression (scRNA-seq) | `Patient 10-02_GEX timepoint T01 scRNAseq` |
| **ADT** | Antibody-derived tag (protein) | `Patient 10-02_ADT timepoint T01 scRNAseq` |
| TCR | T-cell receptor repertoire | (not in this series, but common in others) |
| HTO | Hashtag oligo (sample multiplexing) | (not in this series, but common in others) |

GSE317605 has **168 samples**: 84 GEX + 84 ADT. If a researcher only needs protein (ADT) data, downloading all 168 wastes bandwidth and storage. If they only need GEX, same problem.

**The pipeline currently cannot distinguish GEX from ADT from TCR.** It only knows "this series has 168 samples."

### 1.3 The information gap: Series SOFT vs Family SOFT

The root cause is that our pipeline fetches **Series SOFT** (`targ=self`), which only contains Series-level metadata. Actual sample-level details live in **Family SOFT** (the full file including all `^SAMPLE` records).

| Information | Series SOFT (`targ=self`) | Family SOFT |
|---|---|---|
| Series title / summary / overall_design | Yes | Yes |
| Sample ID list (GSM numbers) | Yes (IDs only) | Yes |
| Sample title (e.g. `_GEX` vs `_ADT`) | **No** | Yes |
| Sample characteristics (library type) | **No** | Yes |
| Sample molecule (polyA RNA vs protein) | **No** | Yes |
| Per-sample FTP download links | **No** | Yes |
| Sample data_processing | **No** | Yes |
| Series supplementary files | Yes (only `_RAW.tar` bundle) | Yes |

**Concrete example** — Series SOFT for GSE317605 (210 lines) only tells us there are 168 GSM IDs. Family SOFT (8,289 lines) tells us each GSM's title, `library type: mRNA` vs `library type: ADT`, `molecule: polyA RNA` vs `molecule: protein`, and per-sample FTP paths to `barcodes.tsv.gz` / `features.tsv.gz` / `matrix.mtx.gz`.

**Conclusion**: To select which samples to download, we **must** fetch Family SOFT.

### 1.4 Why rule-based classification fails

Even with Family SOFT, parsing sample types with deterministic rules is fragile:

**Naming inconsistency across uploaders**:

| Series | GEX sample naming | ADT sample naming |
|---|---|---|
| GSE317605 | `Patient 10-02_GEX timepoint T01` | `Patient 10-02_ADT timepoint T01` |
| (hypothetical) Series B | `sample1_RNA` | `sample1_protein` |
| (hypothetical) Series C | `donor3_transcriptome` | `donor3_AbSeq` |
| (hypothetical) Series D | `S1_3prime_GeneExpression` | `S1_CITE_antibody` |

**Characteristics field inconsistency**:
- GSE317605: `library type: mRNA` / `library type: ADT`
- Others might use: `molecule: cDNA` / `molecule: antibody capture`
- Some don't tag library type at all

**Molecule field inconsistency**:
- GSE317605: `polyA RNA` (GEX) vs `protein` (ADT)
- Others: `total RNA`, `cDNA`, `genomic DNA`, or missing entirely

You can write `if "GEX" in title or "RNA" in molecule: ...` but each new series introduces edge cases. More rules risk false positives on other series.

---

## 2. Proposed solution: LLM-based sample classification

### 2.1 Why LLM fits this task

| Property | Why it helps |
|---|---|
| Semi-structured text + high variability | LLM's core strength vs rigid regex/rules |
| Clear task definition | "Classify each sample as GEX / ADT / TCR / HTO / other" |
| Modest reasoning requirement | Information extraction + classification, not complex reasoning |
| Structured output | LLM returns JSON, directly feeds download pipeline |
| Confidence scoring | LLM can flag low-confidence cases for human review |

### 2.2 Practical considerations

| Dimension | Assessment |
|---|---|
| **Input size** | Family SOFT is ~8K lines / ~200KB per series, but we only need to send each sample's title + characteristics + molecule (~5 fields per sample). For 168 samples, compressed input is ~3K tokens |
| **Cost** | ~300 series × ~3K input tokens each × Haiku pricing → under $1 total |
| **Speed** | Can be called concurrently per series; far faster than manual review |
| **Accuracy** | Higher than rules; LLM can reason about novel naming conventions. Low-confidence results get flagged |

### 2.3 Model choice

**Recommended: Anthropic Claude Haiku** (via `anthropic` Python SDK)

- Sufficient for classification / extraction tasks
- Cheapest option in the Claude family
- Fast response time (~1–2s per request)
- `anthropic` SDK already needed for potential future agent features

Alternative: OpenAI `gpt-4o-mini` — similar cost/capability tier. Decision is an implementation-time choice; the Skill should be model-agnostic via config.

---

## 3. Architecture

### 3.1 New pipeline position

```
[GEOSearchSkill] → [ReportSkill] → [FilterSkill]
                                        │
                                        ▼
                                  filtered_datasets (GSE list)
                                        │
                                        ▼
                              [SampleSelectorSkill]  ← NEW
                                  │           │
                                  │           ├─ fetch Family SOFT per GSE
                                  │           ├─ parse sample-level metadata
                                  │           ├─ compress → LLM prompt
                                  │           └─ LLM classifies each GSM
                                  │
                                  ▼
                          context.selected_samples
                          (dict[str, list[SampleSelection]])
                                  │
                                  ▼
                            [DownloadSkill]  (future)
```

### 3.2 New data models

**File**: `geo_agent/models/sample.py` (new)

```python
@dataclass
class GEOSample:
    """A single GEO Sample (GSM) with metadata from Family SOFT."""
    accession: str           # e.g. "GSM9474997"
    title: str               # e.g. "Patient 10-02_GEX timepoint T01 scRNAseq"
    organism: str            # e.g. "Homo sapiens"
    molecule: str            # e.g. "polyA RNA", "protein"
    characteristics: dict[str, str]  # e.g. {"library type": "mRNA", "tissue": "BTC"}
    library_source: str      # e.g. "transcriptomic", "other"
    supplementary_files: list[str]   # FTP URLs to barcodes/features/matrix files
    description: str         # e.g. "Library name: 10-02_GEX"


@dataclass
class SampleSelection:
    """LLM classification result for one sample."""
    accession: str           # GSM ID
    library_type: str        # "GEX" | "ADT" | "TCR" | "HTO" | "other"
    confidence: float        # 0.0 ~ 1.0
    reasoning: str           # brief explanation from LLM
    needs_review: bool       # True if confidence < threshold
    supplementary_files: list[str]   # carried over for download
```

**PipelineContext additions** (`geo_agent/models/context.py`):

```python
# SampleSelectorSkill outputs
sample_metadata: dict[str, list[GEOSample]] = field(default_factory=dict)
    # accession -> list of parsed samples
selected_samples: dict[str, list[SampleSelection]] = field(default_factory=dict)
    # accession -> list of classified samples
target_library_types: list[str] = field(default_factory=lambda: ["GEX"])
    # which library types to select for download
```

### 3.3 New NCBIClient method

**File**: `geo_agent/ncbi/client.py` — add `fetch_family_soft()`

```python
def fetch_family_soft(self, accession: str) -> str:
    """Fetch Family SOFT for a GSE (includes all sample records).

    Uses GEO acc.cgi with targ=gsm to get sample-level metadata.
    Response is typically 5K–20K lines depending on sample count.
    """
    url = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
    params = {"acc": accession, "targ": "gsm", "form": "text", "view": "brief"}
    self._rate_limit(interval=self._min_interval_geo)
    resp = self.session.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.text
```

Key difference from existing `fetch_geo_soft()`: `targ=gsm` instead of `targ=self`. This returns all `^SAMPLE` blocks instead of just the `^SERIES` block.

### 3.4 Family SOFT parser

**File**: `geo_agent/ncbi/parsers.py` — add `parse_family_soft()`

```python
def parse_family_soft(soft_text: str) -> list[GEOSample]:
    """Parse Family SOFT text into a list of GEOSample objects.

    Splits on '^SAMPLE = ' boundaries, then extracts per-sample fields:
    title, characteristics, molecule, supplementary files, etc.
    """
```

Family SOFT structure (one sample block):

```
^SAMPLE = GSM9474997
!Sample_title = Patient 10-02_GEX timepoint T01 scRNAseq
!Sample_geo_accession = GSM9474997
!Sample_characteristics_ch1 = tissue: Biliary tract cancer (BTC)
!Sample_characteristics_ch1 = cell type: peripheral blood mononuclear cells (PBMCs)
!Sample_characteristics_ch1 = library type: mRNA
!Sample_characteristics_ch1 = time: T01
!Sample_molecule_ch1 = polyA RNA
!Sample_library_source = transcriptomic
!Sample_description = Library name: 10-02_GEX
!Sample_supplementary_file_1 = ftp://...barcodes.tsv.gz
!Sample_supplementary_file_2 = ftp://...features.tsv.gz
!Sample_supplementary_file_3 = ftp://...matrix.mtx.gz
```

vs an ADT sample from the same series:

```
^SAMPLE = GSM9475081
!Sample_title = Patient 10-02_ADT timepoint T01 scRNAseq
!Sample_characteristics_ch1 = library type: ADT
!Sample_molecule_ch1 = protein
!Sample_library_source = other
!Sample_description = Library name: 10-02_ADT
!Sample_description = antibody-derived oligonucleotide
!Sample_supplementary_file_1 = ftp://...ADT_barcodes.tsv.gz
```

Parser only extracts the fields needed for LLM classification + download, keeping memory and token usage low.

### 3.5 LLM prompt design

**Input to LLM** (per series): a compressed JSON array of sample summaries, not the raw SOFT text.

```json
{
  "series": "GSE317605",
  "series_title": "A Phase II Trial of ... [CITE-Seq]",
  "overall_design": "... CITE-seq using 99 AbSeq antibodies ...",
  "samples": [
    {
      "gsm": "GSM9474997",
      "title": "Patient 10-02_GEX timepoint T01 scRNAseq",
      "characteristics": {"library type": "mRNA", "tissue": "BTC", "cell type": "PBMCs"},
      "molecule": "polyA RNA",
      "library_source": "transcriptomic",
      "description": "Library name: 10-02_GEX; polyA RNA"
    },
    {
      "gsm": "GSM9475081",
      "title": "Patient 10-02_ADT timepoint T01 scRNAseq",
      "characteristics": {"library type": "ADT", "tissue": "BTC", "cell type": "PBMCs"},
      "molecule": "protein",
      "library_source": "other",
      "description": "Library name: 10-02_ADT; antibody-derived oligonucleotide"
    }
  ]
}
```

**System prompt** (draft):

```
You are a bioinformatics assistant that classifies GEO samples by library type.

Given a GEO Series and its sample metadata, classify each sample into exactly
one category:
  - GEX: gene expression (scRNA-seq, mRNA, cDNA, transcriptomic)
  - ADT: antibody-derived tags (CITE-seq protein, AbSeq, TotalSeq, surface protein)
  - TCR: T-cell receptor sequencing (TCR-seq, VDJ T cell)
  - BCR: B-cell receptor sequencing (BCR-seq, VDJ B cell)
  - HTO: hashtag oligos (sample multiplexing, cell hashing)
  - ATAC: chromatin accessibility (scATAC-seq)
  - OTHER: anything that doesn't fit above

Use ALL available signals: sample title, characteristics, molecule field,
library_source, and description. Consider the series-level context (title,
overall_design) for disambiguation.

Return a JSON array with one object per sample:
[
  {
    "gsm": "GSM...",
    "library_type": "GEX",
    "confidence": 0.95,
    "reasoning": "title contains _GEX, molecule is polyA RNA, library_source is transcriptomic"
  }
]

Rules:
- confidence should be 0.0-1.0. Use 0.9+ for clear cases, 0.5-0.8 for ambiguous.
- If a sample doesn't clearly match any category, classify as OTHER with low confidence.
- Be concise in reasoning (one sentence).
```

### 3.6 SampleSelectorSkill

**File**: `geo_agent/skills/sample_selector.py` (new)

```python
class SampleSelectorSkill(Skill):
    """Classify samples within each filtered series by library type using LLM.

    Reads:
        context.filtered_datasets — list[GEODataset] from FilterSkill
        context.target_library_types — which types to select (default: ["GEX"])

    Writes:
        context.sample_metadata — dict[str, list[GEOSample]]
        context.selected_samples — dict[str, list[SampleSelection]]
    """

    def __init__(
        self,
        client: NCBIClient,
        llm_client,            # anthropic.Anthropic or similar
        model: str = "claude-3-5-haiku-20241022",
        confidence_threshold: float = 0.7,
        max_concurrent: int = 5,
    ):
        ...
```

**Execution flow**:

```
for each GSE in filtered_datasets:
    1. fetch_family_soft(accession) → raw SOFT text
    2. parse_family_soft(soft_text) → list[GEOSample]
    3. compress samples to JSON prompt input
    4. call LLM with system prompt + sample data
    5. parse LLM JSON response → list[SampleSelection]
    6. filter by target_library_types
    7. flag low-confidence results (needs_review=True)
    8. store in context
```

### 3.7 Config

**File**: `geo_agent/config.py` — add:

```python
anthropic_api_key: str   # from ANTHROPIC_API_KEY in .env
llm_model: str           # default "claude-3-5-haiku-20241022"
```

**File**: `.env` — add:

```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 4. Token budget and cost estimate

### 4.1 Per-series token estimate

| Component | Tokens (approx.) |
|---|---|
| System prompt | ~300 |
| Series context (title + overall_design) | ~200 |
| Sample data (168 samples × ~20 tokens each) | ~3,400 |
| **Total input** | **~3,900** |
| Output (168 classifications × ~30 tokens) | ~5,000 |
| **Total per series** | **~8,900** |

### 4.2 Batch cost estimate (Haiku pricing)

| Scenario | Series count | Total tokens | Estimated cost |
|---|---|---|---|
| Current CITE-seq Homo sapiens | ~317 | ~2.8M | ~$0.30 |
| With larger searches (1000 series) | ~1,000 | ~8.9M | ~$0.90 |

Negligible cost. Even switching to Sonnet for better accuracy stays under $10 for the full corpus.

---

## 5. Error handling

| Scenario | Handling |
|---|---|
| Family SOFT fetch fails (HTTP error) | Log warning, skip series, add to `context.errors` |
| Family SOFT is empty or unparseable | Skip series, flag in errors |
| LLM returns invalid JSON | Retry once with stricter prompt; if still fails, skip series |
| LLM returns unknown library_type | Map to "OTHER", flag for review |
| LLM confidence below threshold | Set `needs_review=True`; include in output but flag |
| LLM rate limit / timeout | Exponential backoff, up to 3 retries |
| Series has 0 samples after filtering | Log info, skip |

---

## 6. Output example

After SampleSelectorSkill, `context.selected_samples` for GSE317605 with `target_library_types=["ADT"]`:

```python
{
    "GSE317605": [
        SampleSelection(
            accession="GSM9475081",
            library_type="ADT",
            confidence=0.98,
            reasoning="title contains _ADT, molecule is protein, library_source is other",
            needs_review=False,
            supplementary_files=[
                "ftp://...GSM9475081_10-02_ADT_barcodes.tsv.gz",
                "ftp://...GSM9475081_10-02_ADT_features.tsv.gz",
                "ftp://...GSM9475081_10-02_ADT_matrix.mtx.gz",
            ],
        ),
        # ... 83 more ADT samples
    ]
}
```

This directly feeds DownloadSkill: iterate `selected_samples`, download each `supplementary_files` list.

---

## 7. Implementation steps

### Step 1: Create data models

**New** `geo_agent/models/sample.py` — `GEOSample` and `SampleSelection` dataclasses (see §3.2).

**Modify** `geo_agent/models/__init__.py` — export the new types.

### Step 2: Extend PipelineContext

**Modify** `geo_agent/models/context.py` — add three fields:

- `target_library_types: list[str]` (default `["GEX"]`)
- `sample_metadata: dict[str, list[GEOSample]]`
- `selected_samples: dict[str, list[SampleSelection]]`

### Step 3: Add Family SOFT fetch methods

**Modify** `geo_agent/ncbi/client.py` — add `fetch_family_soft()` and `fetch_family_soft_batch()`.

- Same pattern as existing `fetch_geo_soft()`, but with `targ=gsm` (fetches all `^SAMPLE` blocks).
- Timeout raised to 60s (response body is 10–50x larger than Series SOFT).

### Step 4: Add Family SOFT parser

**Modify** `geo_agent/ncbi/parsers.py` — add `parse_family_soft(soft_text: str) -> list[GEOSample]`.

- Split text on `^SAMPLE = ` boundaries.
- Per sample block, extract:
  - `!Sample_title`
  - `!Sample_characteristics_ch1` (multiple, parse `key: value` pairs)
  - `!Sample_molecule_ch1`
  - `!Sample_library_source`
  - `!Sample_supplementary_file_*` (collect all numbered entries)
  - `!Sample_description`

### Step 5: Add `anthropic` dependency

**Modify** `pyproject.toml` — add `"anthropic>=0.39.0"` to `[project.dependencies]`.

Then run: `uv lock && uv sync`

### Step 6: Add Anthropic configuration

**Modify** `geo_agent/config.py` — add `anthropic_api_key: str` and `llm_model: str` to `Config`; `load_config()` reads `ANTHROPIC_API_KEY` and `LLM_MODEL` from `.env`.

**Modify** `.env.example` — add `ANTHROPIC_API_KEY=` and `LLM_MODEL=` templates.

### Step 7: Implement SampleSelectorSkill (core)

**New** `geo_agent/skills/sample_selector.py`

- **Constructor**: `ncbi_client`, `llm_client` (`anthropic.Anthropic`), `model`, `confidence_threshold`.
- **`execute(context)`**: fetch Family SOFT → parse → compress to JSON → LLM classification → parse response → filter by `target_library_types`.
- **`_call_llm()`**: call `llm_client.messages.create()`; 1 retry on failure.
- **`_parse_llm_response()`**: parse JSON array from response; strip markdown code fences if present; map unknown `library_type` to `"OTHER"`; set `needs_review=True` when confidence < threshold.

### Step 8: CLI integration

**Modify** `geo_agent/cli.py`

- Add `--library-type` argument (`action="append"`, repeatable, e.g. `--library-type GEX --library-type ADT`).
- When `--library-type` is specified: register `FilterSkill` + `SampleSelectorSkill`, create `anthropic.Anthropic` client, set `context.target_library_types`.
- Print sample selection summary after pipeline run.
- `import anthropic` inside the conditional branch (lazy import — only needed when `--library-type` is used).

### Step 9: Skill spec document

**New** `geo_agent/skills/sample_selector.md` — constructor params, context input/output, execution flow, pipeline position.

### Step 10: Update Architecture.md

**Modify** `docs/Architecture.md` — update data flow diagram, context key table, NCBI method table, data models section, implementation status table.

### Step 11: Tests

**New** `tests/test_parse_family_soft.py` — unit tests for `parse_family_soft()` using fixture data from `Example/GSE317605/GSE317605_family.soft`.

**New** `tests/test_sample_selector.py` — Skill tests with mock NCBI client + mock LLM client.

---

### File summary

| Action | File |
|---|---|
| New | `geo_agent/models/sample.py` |
| Modify | `geo_agent/models/__init__.py` |
| Modify | `geo_agent/models/context.py` |
| Modify | `geo_agent/ncbi/client.py` |
| Modify | `geo_agent/ncbi/parsers.py` |
| Modify | `pyproject.toml` |
| Modify | `geo_agent/config.py` |
| Modify | `.env.example` |
| New | `geo_agent/skills/sample_selector.py` |
| Modify | `geo_agent/cli.py` |
| New | `geo_agent/skills/sample_selector.md` |
| Modify | `docs/Architecture.md` |
| New | `tests/test_parse_family_soft.py` |
| New | `tests/test_sample_selector.py` |

---

## 8. Open questions

1. **Model choice**: Haiku vs Sonnet vs OpenAI gpt-4o-mini? Start with Haiku; upgrade if accuracy is insufficient on edge cases.
2. **Batch API**: Anthropic offers a batch API for async processing at 50% discount. Worth using if processing 300+ series at once.
3. **Caching**: Should we cache Family SOFT and LLM results locally? Family SOFT rarely changes; caching avoids re-fetching. LLM results are deterministic for same input.
4. **Concurrency model**: `asyncio` + `httpx` for parallel Family SOFT + LLM calls, or keep `requests` + `ThreadPoolExecutor`? ThreadPoolExecutor is simpler and consistent with current codebase.
5. **Human review workflow**: How to surface `needs_review=True` samples? Terminal prompt? Markdown report section? Start with a report section.

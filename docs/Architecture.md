# GEO Data Search Agent - Architecture

> **Version**: v1.2
> **Created**: 2026-03-02
> **Last updated**: 2026-03-05
> **Environment**: Python 3.13 (uv) | isolated venv `.venv/`

---

## 1. Project overview

NCBI GEO hosts a large number of public datasets (e.g. 317 CITE-seq Homo sapiens–related records). Researchers need to filter by **data type, organism, disease, tissue**, and other dimensions. Manual search and review is not feasible.

This tool uses an **Agent + Skill pipeline** with two independent branches:

**Branch A — GEO search & report**
1. **Search** — Call NCBI E-utilities + GEO acc.cgi to get raw results and detailed metadata
2. **Report generation** — Structure as a readable report (Markdown + structured data)
3. **AI filter/validation** — Smart filtering based on report content

**Branch B — Multi-omics sample annotation (current focus)**
1. **Hierarchy filter** — `HierarchySkill` classifies each GSE as `standalone` / `super` / `sub`; only `standalone` series (in search results) proceed further
2. **Fetch** — `FetchFamilySoftSkill` calls `NCBIClient.fetch_family_soft_batch()` for the standalone GSE IDs
3. **Parse** — `FamilySoftStructurerSkill` converts raw Family SOFT text to structured JSON
4. **Annotate** — `MultiomicsSeriesAnalyzerSkill` uses a local LLM to annotate all GSMs in a series with a single call (see §3.2 for strategy rationale)
5. **Persist** — `PersistSkill` writes results into a local SQLite database (`geo_agent.db`)

> SuperSeries and SubSeries are currently excluded from annotation; their sample structure is too complex to handle reliably without dedicated resolution logic. This constraint will be revisited in a later phase.
>
> Download of raw data files (fastq, h5) is not implemented.

---

## 2. Project structure

```
Proteomics_data_download/
├── pyproject.toml                  # Dependencies & CLI entry
├── .env                            # Real NCBI_API_KEY (git-ignored)
├── run_multiomics_analysis.py      # Batch runner for multi-omics annotation
│
├── docs/
│   ├── Architecture.md             # This document
│   ├── LLM_sample_selector.md      # LLM selector design notes
│   └── search_report_example.md    # Search report example
│
├── geo_agent/
│   ├── __init__.py
│   ├── cli.py                      # CLI entry (argparse)
│   ├── agent.py                    # Agent orchestrator
│   ├── config.py                   # Config (API Key, LLM model, rate limits)
│   │
│   ├── llm/                        # LLM backend adapters
│   │   ├── __init__.py
│   │   └── ollama_client.py        # OllamaClient: local Ollama via /v1/chat/completions
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── query.py                # SearchQuery dataclass
│   │   ├── dataset.py              # GEODataset, SupplementaryFile
│   │   ├── sample.py               # GEOSample, SampleSelection
│   │   └── context.py              # PipelineContext
│   │
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── base.py                 # Skill abstract interface
│   │   ├── search.py / .md         # GEOSearchSkill
│   │   ├── report.py / .md         # ReportSkill
│   │   ├── filter.py / .md         # FilterSkill
│   │   ├── hierarchy.py / .md      # HierarchySkill
│   │   ├── sample_selector.py / .md          # SampleSelectorSkill (query-driven, Anthropic)
│   │   ├── standalone_sample_selector.py     # StandaloneSampleSelectorSkill
│   │   ├── family_soft_structurer.py         # FamilySoftStructurerSkill (pure field extraction)
│   │   ├── multiomics_analyze_series.py / .md  # MultiomicsSeriesAnalyzerSkill (one LLM call per series)
│   │   ├── multiomics_analyze_sample.py / .md  # MultiomicsSampleAnalyzerSkill (one LLM call per sample)
│   │   └── multiomics_runner.py              # run_series_mode() / run_sample_mode() runner logic
│   │
│   ├── ncbi/
│   │   ├── __init__.py
│   │   ├── client.py               # NCBIClient: HTTP, rate limit, retry
│   │   └── parsers.py              # E-utilities JSON + SOFT parsers
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logging.py
│       └── hierarchy.py            # SeriesNode dataclass + build/format helpers
│
└── tests/
    ├── Test_family_soft_parse/
    │   ├── run_family_soft_parser_debug.py   # Runs FamilySoftStructurerSkill on 22 series
    │   └── family_soft_22_structured.json    # Output: structured metadata (no rule-based labels)
    └── Test_multiomics_analysis/
        ├── run_multiomics_analysis_series.py # Runner: per-series mode (calls run_series_mode)
        ├── run_multiomics_analysis.py        # Runner: per-sample mode (calls run_sample_mode)
        └── debug_multiomics_analysis/        # Output directory
            ├── series/                       # Per-sample JSON files: {series_id}/{gsm_id}.json
            ├── {series_id}_{model}_series_results.json
            └── {series_id}_{model}_series_results_table.md
```

---

## 3. Core architecture

### 3.1 Data flow — Branch B (multi-omics annotation)

```
GEOSearchSkill  →  HierarchySkill
                         │
                         │  series_hierarchy: {role: standalone/super/sub}
                         ▼
               ┌─ standalone AND in_search_results ─┐   ← only these proceed
               │  (super / sub series are skipped)   │
               └───────────────────────────────────-─┘
                         │
                         ▼
              [FetchFamilySoftSkill]         NCBIClient.fetch_family_soft_batch()
                         │   - fetches raw Family SOFT text for each standalone GSE
                         ▼
              [FamilySoftStructurerSkill]    pure field extraction, no inference
                         │   - characteristics, library_type, molecule, description
                         │   - supplementary_files, relation_sra, relation_biosample
                         ▼
              [MultiomicsSeriesAnalyzerSkill]  local LLM (Ollama qwen3:30b-a3b)
                         │   - all samples in one series submitted as a single compacted JSON
                         │   - reads raw fields, reasons from domain knowledge
                         │   - no hardcoded keyword mappings
                         ▼
              per-sample annotation:
                measured_layers  (RNA / protein_surface / TCR_VDJ / ...)
                platform         (10x Chromium 5', Smart-seq2, ...)
                experiment       (CITE-seq, 10x Multiome, ...)
                assay            (scRNA-seq, CITE-seq, TCR V(D)J, ...)
                disease          (normalised: colorectal cancer (CRC))
                tissue           (normalised: colon / PBMC)
                tissue_subtype   (tumor / adjacent normal / "")
                confidence + evidence
                         │
                         ▼
              [PersistSkill]                 SQLite: geo_agent.db
                         │
                         ├── series          (series-level metadata)
                         ├── sample          (per-GSM annotation)
                         ├── sample_layer    (measured_layers, one row per layer)
                         └── sample_raw      (raw SOFT fields for traceability)
```

#### 3.1.1 Standalone-only policy

`HierarchySkill` assigns each series one of three roles based on `!Series_relation` fields:

| Role | Meaning | Processed by Branch B? |
|---|---|---|
| `standalone` | No SuperSeries / SubSeries relations | **Yes** |
| `super` | Has SubSeries children | No (future phase) |
| `sub` | Belongs to a SuperSeries | No (future phase) |

Only series with `role == "standalone" and in_search_results == True` are passed to `FetchFamilySoftSkill`. SuperSeries and SubSeries are excluded because their sample-level structure requires dedicated resolution logic (e.g. deduplication across SubSeries, mapping samples to the correct SubSeries SOFT block).

### 3.2 Annotation strategy: per-series vs per-sample

Two annotation granularities were implemented and evaluated:

| Strategy | LLM calls | Input tokens (GSE266455, 48 samples) | Runtime | Accuracy |
|---|---|---|---|---|
| **Per-series** | 1 per series | ~3,400 tokens (all samples compacted) | ~6 min | **High** |
| Per-sample | 1 per GSM | ~90 tokens (single sample) | similar* | Degrades for paired-library experiments |

\* Per-sample serial execution yields no meaningful wall-clock improvement over per-series in a local Ollama environment, because the total output token count is equivalent and the LLM processes requests sequentially by default.

**Why per-sample accuracy degrades for multi-modal experiments**

For paired-library datasets such as CITE-seq (where GEX and ADT libraries are separate GSM entries), the experiment type is only inferable by observing all samples together. A GEX sample annotated in isolation lacks the signal from its paired ADT counterpart, causing systematic misclassification:

- `experiment` → `"scRNA-seq"` instead of `"CITE-seq"`
- `tissue` → `"blood"` instead of `"PBMC"` (series-level summary not visible to the model)

**Recommendation**: the per-series strategy is adopted as the primary annotation mode. Submitting all samples as a single compacted JSON payload preserves cross-sample context and correctly handles paired-library, multi-modal, and multi-condition series.

### 3.3 Three-layer annotation design

Each GSM is annotated at three independent levels to support flexible downstream filtering:

| Field | Level | Example (GEX sample in CITE-seq) | Example (ADT sample) |
|---|---|---|---|
| `measured_layers` | Molecular | `["RNA"]` | `["protein_surface"]` |
| `experiment` | Experiment | `CITE-seq` | `CITE-seq` |
| `assay` | Sample detection | `scRNA-seq` | `CITE-seq` |

This allows:
- "Give me all protein surface samples" → `"protein_surface" in measured_layers`
- "Give me all samples from CITE-seq experiments" → `experiment == "CITE-seq"`
- "Give me only the RNA component of CITE-seq" → `experiment == "CITE-seq" AND assay == "scRNA-seq"`

### 3.4 Why LLM for annotation (not rules)

Sample naming in GEO is wildly inconsistent across uploaders. Examples:

| Molecular layer | Naming variants seen |
|---|---|
| RNA | `5'GEX`, `GEX`, `_RNA`, `Gene Expression`, `mRNA`, `scRNA` |
| Protein surface | `ADT`, `Surface`, `Surface protein`, `AbSeq`, `CITE` |
| TCR | `VDJ - ab TCR`, `VDJ - gd TCR`, `abTCR`, `gdTCR`, `TCR` |
| Cell hashing | `HTO`, `hashtag`, `ADT/HTO mixed` |

Writing rules for every variant is not scalable — especially for future data types (spatial transcriptomics, CUT&TAG, Perturb-seq). The LLM applies domain knowledge to reason from raw field values directly.

`FamilySoftStructurerSkill` only extracts raw fields (no inference labels). All classification is done by the LLM.

### 3.5 Skill interface

Each Skill is a stateless processor:

```python
class Skill(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def execute(self, context: PipelineContext) -> PipelineContext: ...
```

#### Context key convention

| Skill | Reads | Writes | Status |
|-------|-------|--------|--------|
| GEOSearchSkill | `query` | `datasets`, `total_found` | Implemented |
| HierarchySkill | `datasets` | `series_hierarchy` | Implemented |
| ReportSkill | `query`, `datasets`, `total_found` | `report`, `report_data` | Implemented |
| FilterSkill | `datasets`, `query` | `filtered_datasets` | Implemented |
| FetchFamilySoftSkill | `series_hierarchy` | `family_soft_raw` | Planned (Phase 3.8) |
| FamilySoftStructurerSkill | `target_series_ids` | `family_soft_structured`, `family_soft_structured_json` | Implemented |
| MultiomicsSeriesAnalyzerSkill | `family_soft_structured`, `target_series_ids` | `multiomics_annotations` | Implemented |
| MultiomicsSampleAnalyzerSkill | `family_soft_structured`, `target_series_ids` | `multiomics_annotations` | Implemented (not recommended, see §3.2) |
| PersistSkill | `multiomics_annotations`, `family_soft_structured` | — (writes to SQLite) | Planned (Phase 3.8) |
| StandaloneSampleSelectorSkill | `series_hierarchy`, `target_library_types` | `sample_metadata`, `selected_samples` | Implemented |
| ValidationSkill | `filtered_datasets` | `validated_datasets` | Not yet implemented |

### 3.5 NCBI Client

**Implemented API methods**:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `esearch(db, term, retmax)` | E-utilities | Search, get UID list |
| `esummary(db, ids)` | E-utilities | Get dataset summaries (auto-batched, 200/batch) |
| `efetch(db, ids, rettype, retmode)` | E-utilities | Get full records (XML) |
| `fetch_geo_soft(accession)` | GEO acc.cgi | SOFT metadata for one GSE |
| `fetch_geo_soft_batch(accessions)` | GEO acc.cgi | Batch SOFT metadata |
| `fetch_family_soft(accession)` | GEO acc.cgi | Family SOFT (all sample blocks); 60s timeout |
| `fetch_family_soft_batch(accessions)` | GEO acc.cgi | Batch Family SOFT |

**Rate limits**:

| | No API Key | With API Key | GEO acc.cgi |
|---|---|---|---|
| Max req/s | 3 | 10 | 4 |
| Min interval | 0.34s | 0.1s | 0.25s |

---

## 4. Data models

### 4.1 GEODataset

**File**: `geo_agent/models/dataset.py`

| Field | Type | Description |
|-------|------|-------------|
| `accession` | `str` | e.g. `"GSE164378"` |
| `title` | `str` | Dataset title |
| `summary` | `str` | Series summary text |
| `organism` | `str` | e.g. `"Homo sapiens"` |
| `platform` | `str` | e.g. `"GPL24676"` |
| `sample_count` | `int` | Number of samples |
| `overall_design` | `str` | Experiment design (from SOFT) |
| `ftp_link` | `str` | FTP base URL |
| `supplementary_files` | `list[SupplementaryFile]` | Name + URL |
| `relevance_score` | `float` | Filled by FilterSkill |

### 4.2 SearchQuery

**File**: `geo_agent/models/query.py`

| Field | Type | Description |
|-------|------|-------------|
| `data_type` | `str` | e.g. `"CITE-seq"` |
| `organism` | `Optional[str]` | e.g. `"Homo sapiens"` |
| `disease` | `Optional[str]` | e.g. `"breast cancer"` |
| `tissue` | `Optional[str]` | e.g. `"PBMC"` |
| `max_results` | `int` | Default 100 |

### 4.3 PipelineContext

**File**: `geo_agent/models/context.py`

| Field | Type | Set by | Description |
|-------|------|--------|-------------|
| `query` | `SearchQuery` | Caller | Input search parameters |
| `datasets` | `list[GEODataset]` | GEOSearchSkill | Search results |
| `total_found` | `int` | GEOSearchSkill | Total GEO matches |
| `series_hierarchy` | `dict[str, SeriesNode]` | HierarchySkill | SuperSeries/SubSeries tree |
| `report` | `str` | ReportSkill | Markdown report |
| `filtered_datasets` | `list[GEODataset]` | FilterSkill | Scored subset |
| `target_series_ids` | `list[str]` | CLI / caller | Explicit GSE list for local parsing |
| `family_soft_structured` | `dict[str, dict]` | FamilySoftStructurerSkill | Raw-field structured JSON per GSE |
| `family_soft_structured_json` | `dict[str, str]` | FamilySoftStructurerSkill | Minified JSON string per GSE |
| `multiomics_annotations` | `dict[str, dict]` | MultiomicsAnalyzerSkill | LLM annotation results per GSE |
| `sample_metadata` | `dict[str, list[GEOSample]]` | SampleSelectorSkill | Parsed samples per GSE |
| `selected_samples` | `dict[str, list[SampleSelection]]` | SampleSelectorSkill | Classified samples |
| `errors` | `list[str]` | Agent | Accumulated SkillError messages |

### 4.4 MultiomicsAnnotation (per-sample output)

Output of `MultiomicsAnalyzerSkill`, stored in `context.multiomics_annotations`:

| Field | Type | Description |
|-------|------|-------------|
| `gsm_id` | `str` | e.g. `"GSM8304227"` |
| `sample_title` | `str` | Original GEO title |
| `measured_layers` | `list[str]` | Molecular layers: `RNA`, `protein_surface`, `chromatin`, `TCR_VDJ`, `BCR_VDJ`, `cell_label`, `spatial`, `histone_mod`, `CRISPR`, `other` |
| `platform` | `str` | Sequencing chemistry: `10x Chromium 5'`, `Smart-seq2`, … |
| `experiment` | `str` | Experiment-level protocol: `CITE-seq`, `10x Multiome`, … |
| `assay` | `str` | Sample-level detection: `scRNA-seq`, `CITE-seq`, `TCR V(D)J`, … |
| `disease` | `str` | Normalised disease name |
| `tissue` | `str` | Normalised tissue/cell type |
| `tissue_subtype` | `str` | e.g. `tumor`, `adjacent normal`, `""` |
| `confidence` | `float` | 0.0–1.0 |
| `evidence` | `str` | Key fields used for inference |

---

## 5. OllamaClient

**File**: `geo_agent/llm/ollama_client.py`

Thin wrapper around Ollama's OpenAI-compatible `/v1/chat/completions` endpoint.

```python
client = OllamaClient(base_url="http://localhost:11434")
resp = client.messages.create(
    model="qwen3:30b-a3b",
    system="You are a bioinformatics curator.",
    messages=[{"role": "user", "content": "..."}],
    temperature=0.1,
    max_tokens=16384,
)
text = resp.choices[0].message.content
```

- Automatically strips `<think>...</think>` blocks (qwen3 thinking output)
- Retry logic is handled at the skill level (`max_retries` in `annotate_series`)
- `client.health_check()` and `client.list_models()` for pre-flight checks
- Presents `.messages.create()` interface — compatible with Anthropic SDK calling convention, allowing skills to work with either backend

---

## 6. Batch runners

Two runner scripts live under `tests/Test_multiomics_analysis/`. Both are thin entry points; all logic resides in `geo_agent/skills/multiomics_runner.py`.

**Per-series runner** (recommended):

```bash
# Single series — output files are prefixed with the series ID
TARGET_SERIES=GSE266455 DISABLE_THINKING=1 uv run python tests/Test_multiomics_analysis/run_multiomics_analysis_series.py

# Multiple series
TARGET_SERIES=GSE266455,GSE268991 uv run python tests/Test_multiomics_analysis/run_multiomics_analysis_series.py

# All series in the structured JSON
uv run python tests/Test_multiomics_analysis/run_multiomics_analysis_series.py
```

Output (under `debug_multiomics_analysis/`):
- `{series_id}_{model}_series_results.json` — full annotation with `disease_normalized`, `tissue_normalized`, `reasoning`
- `{series_id}_{model}_series_results_table.md` — series summary + flat per-sample table

**Per-sample runner** (experimental, not recommended for production — see §3.2):

```bash
# Test first sample only
TARGET_SERIES=GSE266455 TARGET_SAMPLE_INDEX=0 DISABLE_THINKING=1 uv run python tests/Test_multiomics_analysis/run_multiomics_analysis.py

# Test first three samples
TARGET_SERIES=GSE266455 TARGET_SAMPLE_INDEX=0,1,2 uv run python tests/Test_multiomics_analysis/run_multiomics_analysis.py
```

`TARGET_SAMPLE_INDEX` accepts comma-separated 0-based indices within each series. Output per-sample JSON is written to `debug_multiomics_analysis/series/{series_id}/{gsm_id}.json`.

---

## 7. Known issues

### 7.1 GEO search returns false positives

GEO's `esearch` matches keywords loosely. Example: GSE280852 was returned for a CITE-seq query but contains only scRNA-seq (6 samples, no ADT). `MultiomicsAnalyzerSkill` correctly annotates such series as RNA-only — these become easy to filter out post-annotation.

### 7.2 Per-sample supplementary files can be empty

Some series set `!Sample_supplementary_file_1 = NONE` for every sample. Data is uploaded as Series-level aggregated files only. `relation_sra` and `relation_biosample` in the structured JSON provide alternative links.

### 7.3 Output token limit for large series

Series with 50+ samples can approach the model's output token limit at `max_tokens=16384`. A retry with slightly higher temperature is attempted automatically (up to `max_retries=2`). If failures persist, consider splitting large series into batches or increasing `max_tokens`.

### 7.4 Qwen JSON instability and rollback controls (added 2026-03-05)

To reduce parse failures such as `no JSON object in LLM output`, the multi-omics runner now supports explicit output-stability controls:

- `STRICT_JSON_MODE=1` (default): send `response_format={"type":"json_object"}` to Ollama OpenAI endpoint.
- `LLM_TEMPERATURE=0.0` and `RETRY_TEMP_STEP=0.0` (default): avoid retry-time temperature drift.
- `DISABLE_THINKING=1` (optional): send `think=false` for models/endpoints that support it.
- `DEBUG_RAW_LLM_DIR=<dir>` (optional): save raw failed responses for debugging.

Quick rollback to legacy behavior:

```bash
STRICT_JSON_MODE=0 \
LLM_TEMPERATURE=0.1 \
RETRY_TEMP_STEP=0.05 \
DISABLE_THINKING=0 \
uv run python run_multiomics_analysis.py
```

---

## 8. SQLite database — `geo_agent.db`

**File**: project root (`geo_agent.db`), git-ignored. Path configurable via `.env`.

Managed by `PersistSkill`. Schema is created on first run (`CREATE TABLE IF NOT EXISTS`).

```sql
-- Series-level metadata
CREATE TABLE series (
    series_id          TEXT PRIMARY KEY,
    title              TEXT,
    organism           TEXT,
    disease_normalized TEXT,
    tissue_normalized  TEXT,
    sample_count       INTEGER,
    model              TEXT,       -- LLM model name used for annotation
    annotated_at       TEXT        -- ISO8601 UTC
);

-- Per-sample annotation results
CREATE TABLE sample (
    gsm_id         TEXT PRIMARY KEY,
    series_id      TEXT NOT NULL REFERENCES series(series_id),
    sample_title   TEXT,
    platform       TEXT,           -- sequencing chemistry
    experiment     TEXT,           -- experiment-level protocol
    assay          TEXT,           -- sample-level detection method
    disease        TEXT,
    tissue         TEXT,
    tissue_subtype TEXT,
    confidence     REAL,
    evidence       TEXT
);

-- measured_layers: one row per layer per sample (atomic)
-- Allows: SELECT * FROM sample JOIN sample_layer USING (gsm_id) WHERE layer = 'protein_surface'
CREATE TABLE sample_layer (
    gsm_id TEXT NOT NULL REFERENCES sample(gsm_id),
    layer  TEXT NOT NULL,          -- RNA / protein_surface / TCR_VDJ / BCR_VDJ / ...
    PRIMARY KEY (gsm_id, layer)
);

-- Raw SOFT fields: traceability back to original GEO metadata
CREATE TABLE sample_raw (
    gsm_id                   TEXT PRIMARY KEY REFERENCES sample(gsm_id),
    library_type             TEXT,
    molecule                 TEXT,
    description              TEXT,
    characteristics_json     TEXT,   -- JSON blob of raw characteristics_ch1 fields
    supplementary_files_json TEXT,
    relation_sra             TEXT,
    relation_biosample       TEXT
);
```

### Example queries

```sql
-- All protein surface samples from PBMC
SELECT s.* FROM sample s
JOIN sample_layer sl USING (gsm_id)
WHERE sl.layer = 'protein_surface' AND s.tissue = 'PBMC';

-- Layer distribution for a specific series
SELECT sl.layer, COUNT(*) AS n
FROM sample_layer sl
JOIN sample s USING (gsm_id)
WHERE s.series_id = 'GSE266455'
GROUP BY sl.layer;

-- High-confidence CITE-seq experiments across all series
SELECT series_id, COUNT(*) AS n
FROM sample
WHERE experiment = 'CITE-seq' AND confidence >= 0.85
GROUP BY series_id ORDER BY n DESC;
```

---

## 9. Implementation status

| Phase | Content | Status |
|-------|---------|--------|
| Phase 1 | Base (data models + NCBIClient) | **Done** |
| Phase 2 | Search Skill + Agent + CLI (MVP) | **Done** |
| Phase 2.5 | Report Skill | **Done** |
| Phase 3 | FilterSkill (relevance scoring) | **Done** |
| Phase 3.5 | StandaloneSampleSelectorSkill (Anthropic, standalone series) | **Done** |
| Phase 3.6 | HierarchySkill (SuperSeries/SubSeries tree) | **Done** |
| Phase 3.7 | FamilySoftStructurerSkill (pure field extraction) + MultiomicsAnalyzerSkill (LLM annotation via Ollama) | **Done** |
| Phase 3.8 | FetchFamilySoftSkill (A→B bridge, standalone-only) + PersistSkill (SQLite: `geo_agent.db`) | **Planned** |
| Phase 4 | Download Skill (raw data files: fastq / h5) | Not implemented |
| Phase 5 | Logging, PipelineResult, unified JSON output | Not implemented |

---

## 9. Technology choices

| Decision | Choice | Reason |
|---|---|---|
| LLM backend for annotation | Local Ollama (qwen3:30b-a3b) | No API cost; MoE architecture (~3.7B active params) is fast despite 30B total |
| MoE vs Dense | qwen3:30b-a3b (MoE) faster than qwen3.5:9b (Dense) | Active parameter count determines speed, not total parameter count |
| Annotation strategy | LLM reasoning on raw fields | Rule-based keyword matching cannot scale to all omics types and naming variants |
| Annotation granularity | Per-series (all samples in one call) | Per-sample mode loses cross-sample context; paired-library experiments (CITE-seq, 10x Multiome) misclassified when GEX and ADT samples are annotated in isolation (see §3.2) |
| No `inferred_library_type` in LLM input | Removed from structurer | Hardcoded rules leak bias; LLM reasons better from raw evidence |
| HTTP client | `requests` | Synchronous is sufficient; NCBI rate limit 3–10 req/s |
| Package manager | `uv` | Fast, isolated venv independent of system Python |

---

## 10. CLI usage

```bash
# Basic search
uv run geo-agent search --data-type "CITE-seq" --organism "Homo sapiens"

# Save report to file
uv run geo-agent search --data-type "CITE-seq" --organism "Homo sapiens" --report results.md

# Run Family SOFT parser (generates structured JSON)
cd tests/Test_family_soft_parse
uv run python run_family_soft_parser_debug.py

# Run multi-omics annotation
TARGET_SERIES=GSE268991 uv run python run_multiomics_analysis.py
```

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-02 | v0.1 | Initial architecture |
| 2026-03-02 | v0.2 | Phase 1/2/2.5 done; ReportSkill; retry/FTP separation |
| 2026-03-02 | v0.3 | PipelineContext dataclass; FilterSkill |
| 2026-03-02 | v0.4 | Overall design: GEO acc.cgi SOFT; GEOSearchSkill 3-step |
| 2026-03-02 | v0.5 | Self-contained doc: data models, end-to-end example |
| 2026-03-03 | v0.6 | SampleSelectorSkill: LLM-based GSM classification; Anthropic SDK |
| 2026-03-03 | v0.7 | Known issues from real-world testing |
| 2026-03-03 | v0.8 | HierarchySkill: SuperSeries/SubSeries family tree |
| 2026-03-04 | v0.9 | FamilySoftStructurerSkill: rule-based local SOFT parser (no LLM) |
| 2026-03-05 | v1.0 | MultiomicsAnalyzerSkill: LLM-based three-layer annotation (measured_layers / experiment / assay) via local Ollama; OllamaClient adapter; removed hardcoded modality inference from FamilySoftStructurerSkill; three-layer annotation design (§3.2); MoE speed note (§9) |
| 2026-03-05 | v1.1 | Standalone-only policy for Branch B (§3.1.1); FetchFamilySoftSkill + PersistSkill planned as Phase 3.8; SQLite schema design (§8); updated data flow diagram to show full A→B pipeline |
| 2026-03-05 | v1.2 | Refactored `multiomics_analyzer` into `multiomics_analyze_series` + `multiomics_analyze_sample` + `multiomics_runner`; added per-series vs per-sample strategy evaluation (§3.2); adopted per-series as primary annotation mode; added `TARGET_SAMPLE_INDEX` and `output_prefix` to test runners; updated project structure, skill table, batch runner docs |

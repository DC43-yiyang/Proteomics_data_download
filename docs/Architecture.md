# GEO Data Search Agent - Architecture

> **Version**: v0.6
> **Created**: 2026-03-02
> **Last updated**: 2026-03-03
> **Environment**: Python 3.12.12 (uv) | isolated venv `.venv/`

---

## 1. Project overview

NCBI GEO hosts a large number of public datasets (e.g. 276+ CITE-seq Homo sapiens–related records). Researchers need to filter by **data type, organism, disease, tissue**, and other dimensions. Manual search and review is not feasible.

This tool uses an **Agent + Skill pipeline** with three automated stages:

1. **Search** — Call NCBI E-utilities + GEO acc.cgi to get raw results and detailed metadata (Overall design)
2. **Report generation** — Structure as a readable report (Markdown + structured data)
3. **AI filter/validation** — Smart filtering based on report content to surface the best matches

> Current focus is search and report generation; download is not implemented yet (interfaces are stubbed).

---

## 2. Project structure

```
Proteomics_data_download/
├── pyproject.toml                  # Dependencies & CLI entry
├── .env                            # Real NCBI_API_KEY (git-ignored)
├── .env.example                    # API Key template
├── .gitignore
│
├── docs/
│   ├── ARCHITECTURE.md             # This document
│   └── search_report_example.md    # Search report example
│
├── geo_agent/
│   ├── __init__.py
│   ├── cli.py                      # CLI entry (argparse)
│   ├── agent.py                    # Agent orchestrator
│   ├── config.py                   # Config (API Key, rate limits)
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── query.py                # SearchQuery dataclass
│   │   ├── dataset.py              # GEODataset, SupplementaryFile
│   │   ├── sample.py               # GEOSample, SampleSelection (sample-level models)
│   │   └── result.py               # PipelineResult (not yet implemented)
│   │
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── base.py                 # Skill abstract interface
│   │   ├── README.md               # Skill development guide
│   │   ├── search.py              # GEOSearchSkill: esearch + esummary + SOFT (Overall design)
│   │   ├── search.md              # GEOSearchSkill spec
│   │   ├── report.py              # ReportSkill: Markdown report
│   │   ├── report.md              # ReportSkill spec
│   │   ├── filter.py              # FilterSkill: keyword scoring + filtering
│   │   ├── filter.md              # FilterSkill spec
│   │   ├── sample_selector.py     # SampleSelectorSkill: LLM-based sample classification
│   │   ├── sample_selector.md     # SampleSelectorSkill spec / 操作指南
│   │   └── validate.py            # ValidationSkill (not yet implemented)
│   │
│   ├── ncbi/
│   │   ├── __init__.py
│   │   ├── client.py               # NCBIClient: HTTP, rate limit, retry
│   │   └── parsers.py              # E-utilities JSON + SOFT parsers
│   │
│   └── utils/
│       ├── __init__.py
│       └── logging.py             # Logging config
│
└── tests/
    ├── __init__.py
    ├── test_parse_family_soft.py   # Family SOFT parser tests
    ├── test_sample_selector.py     # SampleSelectorSkill tests (mocked LLM)
    └── fixtures/                   # Offline test response data
```

---

## 3. Core architecture

### 3.1 Data flow

```
User CLI input
    │
    ▼
SearchQuery ──▶ [GEOSearchSkill] ──▶ list[GEODataset]
                  │                       │
                  ├─ esearch (UIDs)       │  Each dataset has:
                  ├─ esummary (metadata)  │  title, summary, organism,
                  └─ acc.cgi SOFT         │  overall_design, sample_count...
                    (Overall design)      │
                                          ▼
                                   [ReportSkill] ──▶ Markdown report + structured data
                                                          │
                                                          ▼
                                                   [FilterSkill] ──▶ scored & sorted (implemented)
                                                                         │
                                                                         ▼
                                                               [SampleSelectorSkill] ──▶ per-GSM classification
                                                                  │                       (when --library-type)
                                                                  ├─ acc.cgi Family SOFT (targ=gsm)
                                                                  └─ LLM classification (Claude Haiku)
                                                                                              │
                                                                                              ▼
                                                                                       [ValidateSkill] ──▶ validation (not yet implemented)
```

### 3.2 Skill interface

Each Skill is a stateless processor with a single `execute(context) -> context` contract:

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
| ReportSkill | `query`, `datasets`, `total_found` | `report`, `report_data` | Implemented |
| FilterSkill | `datasets`, `query` | `filtered_datasets` | Implemented |
| SampleSelectorSkill | `filtered_datasets`, `target_library_types` | `sample_metadata`, `selected_samples` | Implemented |
| ValidationSkill | `filtered_datasets` | `validated_datasets` | Not yet implemented |

### 3.3 Agent orchestrator

- Maintains an ordered list of Skills; supports chained `agent.register(skill)`
- Executes in order, passing a shared context
- `SkillError` → log and continue with next Skill
- Other exceptions → abort pipeline

### 3.4 NCBI Client

**Implemented API methods**:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `esearch(db, term, retmax)` | E-utilities | Search, get UID list |
| `esummary(db, ids)` | E-utilities | Get dataset summaries (auto-batched, 200 per batch) |
| `efetch(db, ids, rettype, retmode)` | E-utilities | Get full records (XML) |
| `fetch_geo_soft(accession)` | GEO acc.cgi | Get SOFT metadata for one GSE (incl. Overall design) |
| `fetch_geo_soft_batch(accessions)` | GEO acc.cgi | Batch SOFT metadata; returns `dict[str, str]` |
| `fetch_family_soft(accession)` | GEO acc.cgi | Get Family SOFT (`targ=gsm`) with all sample blocks; 60s timeout |
| `fetch_family_soft_batch(accessions)` | GEO acc.cgi | Batch Family SOFT; returns `dict[str, str]` |

**Rate limits (implemented)**:

| | No API Key | With API Key (current) | GEO acc.cgi |
|---|---|---|---|
| Max req/s | 3 | **10** | **4** |
| Min interval | 0.34s | **0.1s** | **0.25s** |

> **Note**: GEO acc.cgi is a web endpoint (not E-utilities), does not accept API Key; uses fixed 0.25s interval.
> Full SOFT fetch for 317 records takes ~80 seconds.

**Retry (implemented)**: Exponential backoff on HTTP 429/5xx, up to 3 attempts.

---

## 4. Data models

All types live under `geo_agent/models/`. Skills read/write these; changing report or filter logic requires knowing the exact fields.

### 4.1 GEODataset and SupplementaryFile

**File**: `geo_agent/models/dataset.py`

| Field | Type | Description |
|-------|------|-------------|
| `accession` | `str` | e.g. `"GSE164378"` |
| `uid` | `str` | NCBI internal UID |
| `title` | `str` | Dataset title |
| `summary` | `str` | Series summary text |
| `organism` | `str` | e.g. `"Homo sapiens"` |
| `platform` | `str` | e.g. `"GPL24676"` |
| `series_type` | `str` | e.g. `"Expression profiling by high throughput sequencing"` |
| `sample_count` | `int` | Number of samples |
| `overall_design` | `str` | Experiment design (from SOFT; often contains protocol info) |
| `ftp_link` | `str` | FTP base URL for future download |
| `supplementary_files` | `list[SupplementaryFile]` | Name + URL (+ optional size) |
| `relevance_score` | `float` | Filled by FilterSkill (0.0 ~ 1.0) |
| `is_valid` | `bool` | Filled by ValidationSkill (not yet implemented) |
| `validation_notes` | `str` | Filled by ValidationSkill |

**Computed**: `geo_url` property → `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}`

**SupplementaryFile**: `name: str`, `url: str`, `size_bytes: Optional[int]`

### 4.2 SearchQuery

**File**: `geo_agent/models/query.py`

| Field | Type | Description |
|-------|------|-------------|
| `data_type` | `str` | e.g. `"CITE-seq"`, `"scRNA-seq"`, `"WGS"`, `"WES"` |
| `organism` | `Optional[str]` | e.g. `"Homo sapiens"` |
| `disease` | `Optional[str]` | e.g. `"breast cancer"` |
| `tissue` | `Optional[str]` | e.g. `"PBMC"`, `"T cells"` |
| `file_types` | `list[str]` | Default `[".h5", ".mtx.gz", ".csv.gz"]` (for future download) |
| `max_results` | `int` | Default 100 |

**`to_geo_query() -> str`**: Builds NCBI GEO search string. Logic:

- `data_type` is first term (matched in [All Fields] by GEO).
- If `organism`: append `"<organism>"[Organism]`.
- If `disease` or `tissue`: append as extra terms (All Fields).
- Always append `gse[EntryType]`.
- All parts joined with ` AND `.

Example: `SearchQuery(data_type="CITE-seq", organism="Homo sapiens")` →  
`CITE-seq AND "Homo sapiens"[Organism] AND gse[EntryType]`

### 4.3 GEOSample and SampleSelection

**File**: `geo_agent/models/sample.py`

**GEOSample** — per-GSM metadata parsed from Family SOFT:

| Field | Type | Description |
|-------|------|-------------|
| `accession` | `str` | e.g. `"GSM9474997"` |
| `title` | `str` | Sample title |
| `organism` | `str` | e.g. `"Homo sapiens"` |
| `molecule` | `str` | e.g. `"polyA RNA"`, `"protein"`, `"genomic DNA"` |
| `characteristics` | `dict[str, str]` | Parsed from `!Sample_characteristics_ch1` (key: value pairs) |
| `library_source` | `str` | e.g. `"transcriptomic"`, `"other"` |
| `supplementary_files` | `list[str]` | URLs from `!Sample_supplementary_file` |
| `description` | `str` | Sample description text |

**SampleSelection** — LLM classification result:

| Field | Type | Description |
|-------|------|-------------|
| `accession` | `str` | GSM accession |
| `library_type` | `str` | `GEX\|ADT\|TCR\|BCR\|HTO\|ATAC\|OTHER` |
| `confidence` | `float` | 0.0–1.0 |
| `reasoning` | `str` | LLM explanation |
| `needs_review` | `bool` | `True` if confidence < threshold |
| `supplementary_files` | `list[str]` | Carried from GEOSample |

### 4.4 PipelineContext

**File**: `geo_agent/models/context.py`

| Field | Type | Set by | Description |
|-------|------|--------|-------------|
| `query` | `SearchQuery` | Caller (required) | Input search parameters |
| `datasets` | `list[GEODataset]` | GEOSearchSkill | Search results with metadata |
| `total_found` | `int` | GEOSearchSkill | Total matching records in GEO |
| `report` | `str` | ReportSkill | Markdown report text |
| `report_data` | `list[dict]` | ReportSkill | Per-dataset dicts for AI/filter |
| `filtered_datasets` | `list[GEODataset]` | FilterSkill | Scored and sorted subset |
| `target_library_types` | `list[str]` | CLI `--library-type` | Target library types (default `["GEX"]`) |
| `sample_metadata` | `dict[str, list[GEOSample]]` | SampleSelectorSkill | Parsed samples per GSE |
| `selected_samples` | `dict[str, list[SampleSelection]]` | SampleSelectorSkill | Classified + filtered samples per GSE |
| `validated_datasets` | `list[GEODataset]` | ValidationSkill | Not yet implemented |
| `download_dir` | `str` | Config | Default `"./geo_downloads"` |
| `downloaded_files` | `list[str]` | Download skill | Not yet implemented |
| `errors` | `list[str]` | Agent | Accumulated SkillError messages |

---

## 5. Overall design: why and how

### 5.1 Why a third step (SOFT)?

E-utilities **esummary** does not return the **Overall design** field. For many scRNA-seq/CITE-seq entries, Title and Summary describe study background; the actual protocol (e.g. "CITE-seq, 151 antibodies") is only in **Overall design**. So GEOSearchSkill adds a third step: request SOFT from GEO acc.cgi per record and parse out `!Series_overall_design`.

### 5.2 SOFT format example

GEO acc.cgi returns SOFT: line-oriented key-value lines with `!` prefix and ` = ` separator. Example snippet:

```
!Series_geo_accession = GSE164378
!Series_title = Single-cell RNA and protein profiling of ...
!Series_summary = We applied joint single cell RNA and epitope analysis...
!Series_overall_design = Tumour samples were processed for CITE-seq using 151 antibodies. Libraries were...
!Series_type = Expression profiling by high throughput sequencing
!Series_contributor = Smith,,John
!Series_sample_id = GSM5012345
!Series_sample_id = GSM5012346
```

### 5.3 Parsing logic

**File**: `geo_agent/ncbi/parsers.py` → `parse_soft_text(soft_text: str) -> dict[str, str]`

- Iterate lines; keep only lines starting with `!` and containing ` = `.
- Split on first ` = `; key and value stripped.
- Single-value fields (e.g. `!Series_overall_design`) → one entry in the dict (e.g. `overall_design`).
- Multi-value fields (e.g. `!Series_contributor`, `!Series_sample_id`) → collected then joined with `"; "`.
- GEOSearchSkill uses `parsed.get("overall_design", "")` to set `GEODataset.overall_design`; other fields are available for future use.

---

## 6. End-to-end example

One full data flow from CLI to filtered output.

### 6.1 CLI command

```bash
.venv/bin/geo-agent search --data-type "CITE-seq" --organism "Homo sapiens" --disease "breast cancer" --max-results 10 --report results.md
```

### 6.2 Query building

CLI builds `SearchQuery(data_type="CITE-seq", organism="Homo sapiens", disease="breast cancer", max_results=10)`.  
`to_geo_query()` returns:

```
CITE-seq AND "Homo sapiens"[Organism] AND breast cancer AND gse[EntryType]
```

### 6.3 GEOSearchSkill (three steps)

1. **esearch** — `NCBIClient.esearch(db="gds", term=geo_query, retmax=10)` → JSON → `parse_esearch_response()` → list of UIDs + `total_found`.
2. **esummary** — `NCBIClient.esummary(db="gds", ids=uids)` → JSON → `parse_esummary_to_datasets()` → `list[GEODataset]` with accession, title, summary, organism, sample_count, ftp_link, etc. (no Overall design yet).
3. **SOFT** — `NCBIClient.fetch_geo_soft_batch(accessions)` → one acc.cgi request per accession (0.25s spacing) → `parse_soft_text()` per response → set `ds.overall_design` on each dataset.

Context after search: `context.datasets`, `context.total_found` populated.

### 6.4 ReportSkill

Reads `context.query`, `context.datasets`, `context.total_found`. Builds:

- `context.report_data`: list of dicts (accession, title, organism, summary, overall_design, geo_url, …) for each dataset.
- `context.report`: Markdown (overview table + per-dataset details). If `--report results.md` was given, also writes that file.

### 6.5 FilterSkill (when registered)

Reads `context.datasets` and `context.query`. For each dataset:

- Applies `min_samples`, `required_keywords`, `exclude_keywords` (constructor params).
- Computes **relevance score** from: data_type in title (0.30) / Overall design (0.25) / summary (0.15); organism exact (0.20); disease in title (0.20) / design or summary (0.10); tissue in title (0.15) / design or summary (0.08); sample count ≥50 (0.10) or ≥20 (0.05); has supplementary files (0.05). Sorted by score descending; threshold by `min_score`.
- Writes `context.filtered_datasets`.

> **Note**: The current CLI only registers GEOSearchSkill and ReportSkill; it does not register FilterSkill. To use filtering, instantiate and register FilterSkill (e.g. in a custom script or future CLI flag) before `agent.run()`.

### 6.6 Summary flow

```
CLI args → SearchQuery → to_geo_query()
    → esearch (UIDs) → esummary (GEODataset list) → acc.cgi SOFT (overall_design)
    → ReportSkill (report + report_data)
    → FilterSkill (filtered_datasets, if registered)
```

---

## 7. Adopted improvements

These improvements came from review and are reflected in the code:

| Suggestion | Status | Notes |
|------------|--------|-------|
| FTP vs API separation | Adopted | E-utilities for metadata only; `GEODataset.ftp_link` holds FTP URL for future download |
| Retry + backoff | Implemented | `NCBIClient._request_with_retry()` for 429/5xx |
| UID batch requests | Implemented | `esummary()` auto-batches (200 per batch) |
| Defer download phase | Adopted | Focus on search + report; download not implemented |
| Metadata sync / download async | Not yet | Download phase will use `ThreadPoolExecutor` |
| Resume download | Not yet | Download: file size check + HTTP Range |
| Typed context | **Implemented** | `PipelineContext` dataclass instead of raw dict; IDE completion + spell-check |
| Downstream AnnData | Not yet | After download, emit `metadata.json` for analysis |

---

## 8. CLI usage

```bash
# Basic search
.venv/bin/geo-agent search --data-type "CITE-seq" --organism "Homo sapiens"

# Multi-dimensional search
.venv/bin/geo-agent search --data-type "CITE-seq" --disease "breast cancer" --tissue "PBMC"

# Save report to file
.venv/bin/geo-agent search --data-type "CITE-seq" --organism "Homo sapiens" --report results.md

# Limit results
.venv/bin/geo-agent search --data-type "scRNA-seq" --max-results 50
```

### Search dimensions

| Dimension | CLI option | GEO field | Examples |
|-----------|------------|-----------|----------|
| Data type | `--data-type` | `[Description]` | CITE-seq, scRNA-seq, WGS, WES |
| Organism | `--organism` | `[Organism]` | Homo sapiens, Mus musculus |
| Disease | `--disease` | `[Description]` | breast cancer, lung cancer |
| Tissue/cell | `--tissue` | `[Description]` | PBMC, T cells, breast tissue |

---

## 9. Implementation status

| Phase | Content | Status |
|-------|---------|--------|
| Phase 1 | Base (data models + NCBIClient) | **Done** |
| Phase 2 | Search Skill + Agent + CLI (MVP) | **Done** |
| Phase 2.5 | Report Skill (Markdown + structured data) | **Done** |
| Phase 3 | FilterSkill (relevance scoring) + Skill docs | **Done** |
| Phase 3.5 | SampleSelectorSkill (LLM sample classification) | **Done** |
| Phase 4 | Download Skill (deferred) | Not implemented |
| Phase 5 | Logging, PipelineResult, JSON output | Not implemented |

---

## 10. Technology choices

- **Custom framework vs LangChain**: Pipeline is mostly deterministic (search → report → filter); LLM is only used for sample classification (SampleSelectorSkill)
- **requests vs httpx/aiohttp**: NCBI rate limit 3–10 req/s; async adds little for metadata phase
- **uv + Python 3.12**: Isolated environment, independent of system Python
- **Current focus on search**: Ensure search → report is correct first; download can follow later

---

## 11. Extensibility

- **New Skill**: Implement `Skill` and call `agent.register()`
- **Web UI**: Agent is CLI-agnostic; call `agent.run(context)` from FastAPI/Flask
- **AI filtering**: `report_data` from ReportSkill (list of dicts) feeds LLM or other downstream filtering
- **Downstream analysis**: Future download can emit `metadata.json` for Scanpy/Muon

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-02 | v0.1 | Initial architecture |
| 2026-03-02 | v0.2 | Phase 1/2/2.5 done; ReportSkill; review feedback (retry, FTP separation); flow search→report→AI filter; uv + API Key |
| 2026-03-02 | v0.3 | PipelineContext dataclass; FilterSkill (keyword scoring); Skill docs under `docs/skills/` |
| 2026-03-02 | v0.4 | Overall design: GEO acc.cgi SOFT; `fetch_geo_soft()` / `fetch_geo_soft_batch()`; `parse_soft_text()`; GEOSearchSkill 3-step (esearch→esummary→SOFT); FilterSkill scoring with design_lower (title 0.30 > design 0.25 > summary 0.15); GEO acc.cgi rate limit 0.25s |
| 2026-03-02 | v0.5 | Self-contained doc: Data models (GEODataset, SearchQuery, PipelineContext); Overall design motivation + SOFT example + parse logic; End-to-end example (CLI → query → esearch → esummary → SOFT → report → filter); FilterSkill scoring weights in Architecture |
| 2026-03-03 | v0.6 | SampleSelectorSkill: LLM-based GSM sample classification; Family SOFT fetch/parse (`fetch_family_soft`, `parse_family_soft`); GEOSample/SampleSelection data models; Anthropic SDK integration; `--library-type` CLI flag; Unit tests |

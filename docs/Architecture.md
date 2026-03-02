# GEO Data Search Agent - Architecture

> **Version**: v0.4
> **Created**: 2026-03-02
> **Last updated**: 2026-03-02
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

**Rate limits (implemented)**:

| | No API Key | With API Key (current) | GEO acc.cgi |
|---|---|---|---|
| Max req/s | 3 | **10** | **4** |
| Min interval | 0.34s | **0.1s** | **0.25s** |

> **Note**: GEO acc.cgi is a web endpoint (not E-utilities), does not accept API Key; uses fixed 0.25s interval.
> Full SOFT fetch for 317 records takes ~80 seconds.

**Retry (implemented)**: Exponential backoff on HTTP 429/5xx, up to 3 attempts.

---

## 4. Adopted improvements

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

## 5. CLI usage

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

## 6. Implementation status

| Phase | Content | Status |
|-------|---------|--------|
| Phase 1 | Base (data models + NCBIClient) | **Done** |
| Phase 2 | Search Skill + Agent + CLI (MVP) | **Done** |
| Phase 2.5 | Report Skill (Markdown + structured data) | **Done** |
| Phase 3 | FilterSkill (relevance scoring) + Skill docs | **Done** |
| Phase 4 | Download Skill (deferred) | Not implemented |
| Phase 5 | Logging, PipelineResult, JSON output | Not implemented |

---

## 7. Technology choices

- **Custom framework vs LangChain**: Pipeline is deterministic (search → report → filter → validate), no LLM; a small Agent class is enough
- **requests vs httpx/aiohttp**: NCBI rate limit 3–10 req/s; async adds little for metadata phase
- **uv + Python 3.12**: Isolated environment, independent of system Python
- **Current focus on search**: Ensure search → report is correct first; download can follow later

---

## 8. Extensibility

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

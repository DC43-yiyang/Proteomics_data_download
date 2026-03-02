# GEOSearchSkill

## Overview

Searches the GEO database via NCBI E-utilities (esearch + esummary) and GEO acc.cgi (SOFT format), returning a list of datasets with full metadata including Overall design.

## Code location

`geo_agent/skills/search.py` → `GEOSearchSkill`

## Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `client` | `NCBIClient` | — | From `geo_agent/ncbi/client.py`; handles rate limiting and retries |
| `fetch_details` | `bool` | `True` | Whether to fetch Overall design etc. via GEO acc.cgi |

`NCBIClient` is configured via `load_config()` in `geo_agent/config.py` (reads `NCBI_API_KEY` and `NCBI_EMAIL` from `.env`).

## Execution flow (three steps)

1. **esearch** — Query GDS database, get matching UID list
2. **esummary** — Batch fetch metadata (title, summary, organism, sample_count, etc.)
3. **acc.cgi SOFT** (optional) — Request GEO SOFT format per record to extract `overall_design`

> **Why step 3?** E-utilities esummary does not return Overall design. Many scRNA-seq entries only describe study background in Title/Summary; key protocol info (e.g. "CITE-seq, 151 antibodies") is in Overall design.

## PipelineContext input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | `SearchQuery` | Yes | Defined in `geo_agent/models/query.py`; includes data_type, organism, disease, tissue, max_results |

## PipelineContext output

| Field | Type | Description |
|-------|------|-------------|
| `datasets` | `list[GEODataset]` | Defined in `geo_agent/models/dataset.py`; includes accession, title, summary, organism, **overall_design**, etc. |
| `total_found` | `int` | Total number of GEO records matching the query (may exceed len(datasets)) |

## Performance notes

- SOFT step issues one request per record to GEO acc.cgi (0.25s spacing); 300+ records take ~80 seconds
- Set `fetch_details=False` to skip this step (overall_design will be empty)

## CLI usage

```bash
.venv/bin/geo-agent search --data-type "CITE-seq" --organism "Homo sapiens" --max-results 20
```

## Pipeline position

- Depends on: none
- Followed by: ReportSkill, FilterSkill

## Requirements

- Network access (NCBI E-utilities + GEO acc.cgi)
- Optional: set `NCBI_API_KEY` in `.env` to raise E-utilities rate to 10 req/s (acc.cgi unchanged)

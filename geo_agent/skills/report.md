# ReportSkill

## Overview

Turns search results into a human-readable Markdown report and structured data (`report_data`) for manual review or downstream AI Agent filtering.

## Code location

`geo_agent/skills/report.py` → `ReportSkill`

## Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_file` | `str \| None` | `None` | Optional; path to save the Markdown report |

## PipelineContext input

| Field | Type | Required | Source |
|-------|------|----------|--------|
| `query` | `SearchQuery` | Yes | CLI-constructed |
| `datasets` | `list[GEODataset]` | Yes | GEOSearchSkill output |
| `total_found` | `int` | Yes | GEOSearchSkill output |

## PipelineContext output

| Field | Type | Description |
|-------|------|-------------|
| `report` | `str` | Full report in Markdown (overview table + per-dataset details) |
| `report_data` | `list[dict]` | Structured dict per dataset; fields listed below |

### report_data record fields

| Field | Type | Description |
|-------|------|-------------|
| `accession` | `str` | GSE accession |
| `title` | `str` | Dataset title |
| `organism` | `str` | Organism |
| `platform` | `str` | GPL platform id |
| `series_type` | `str` | Series type |
| `sample_count` | `int` | Sample count |
| `summary` | `str` | Summary |
| `overall_design` | `str` | Experiment design (from GEO acc.cgi SOFT; often contains key protocol info) |
| `geo_url` | `str` | GEO page URL |
| `ftp_link` | `str` | FTP download URL |
| `supplementary_files` | `list[dict]` | Supplementary files; each has `name` and `url` |

## CLI usage

```bash
# Search and save report to file
.venv/bin/geo-agent search --data-type "CITE-seq" --organism "Homo sapiens" --report results.md
```

## Pipeline position

- Depends on: GEOSearchSkill
- Followed by: FilterSkill

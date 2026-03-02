# FilterSkill

## Overview

Filters and scores search results. Designed to be invoked directly by an AI Agent (e.g. Claude Code): filter criteria are specified via constructor parameters, and datasets are relevance-scored and filtered.

## Code location

`geo_agent/skills/filter.py` → `FilterSkill`

## Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_samples` | `int` | `0` | Minimum sample count; datasets below this are excluded |
| `required_keywords` | `list[str]` | `[]` | Keywords that must appear in title, summary, or Overall design (any match passes) |
| `exclude_keywords` | `list[str]` | `[]` | Datasets containing these keywords in title, summary, or Overall design are excluded |
| `min_score` | `float` | `0.0` | Minimum relevance score threshold |

## PipelineContext input

| Field | Type | Required | Source |
|-------|------|----------|--------|
| `datasets` | `list[GEODataset]` | Yes | GEOSearchSkill output |
| `query` | `SearchQuery` | Yes | CLI-constructed (used for keyword scoring) |

## PipelineContext output

| Field | Type | Description |
|-------|------|-------------|
| `filtered_datasets` | `list[GEODataset]` | Filtered datasets, sorted by `relevance_score` descending |

Each `GEODataset`'s `relevance_score` field (0.0 ~ 1.0) is filled in this stage.

## Scoring dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Data type match | 0.30 / 0.25 / 0.15 | data_type in title / Overall design / summary |
| Organism exact match | 0.20 | organism matches query exactly |
| Disease match | 0.20 / 0.10 | disease in title / Overall design or summary |
| Tissue match | 0.15 / 0.08 | tissue in title / Overall design or summary |
| Sample count | 0.10 / 0.05 | ≥50 / ≥20 samples |
| Has supplementary files | 0.05 | supplementary_files non-empty |

> **Design note**: Overall design weight (0.25) is second only to title (0.30) and higher than summary (0.15). Many scRNA-seq/CITE-seq experiments put key protocol info only in Overall design, while title and summary often describe study background.

## Pipeline position

- Depends on: GEOSearchSkill
- Followed by: ValidateSkill (not yet implemented)

## AI Agent usage

After reviewing `report_data` from ReportSkill, the AI Agent should set FilterSkill constructor parameters (e.g. which keywords to require/exclude, minimum samples) based on the analysis, then call `FilterSkill.execute(context)` to obtain filtered results.

# ReportSkill

## What it does

Generates a Markdown report and structured `report_data` from search results for human review.

## Context I/O

| Direction | Field | Type |
|---|---|---|
| Input | `query` | `SearchQuery` |
| Input | `datasets` | `list[GEODataset]` |
| Input | `total_found` | `int` |
| Output | `report` | `str` (Markdown) |
| Output | `report_data` | `list[dict]` |

## Domain knowledge

- The report is for **human review before downstream processing**. It helps researchers quickly decide which series are worth investigating.
- `overall_design` is the most important field — it tells the researcher exactly what the experiment did. Truncated to 500 chars in the report.
- `supplementary_files` here are Series-level files (e.g. `_RAW.tar`), not per-sample files. Per-sample files come from Family SOFT (SampleSelectorSkill).

## Code entry

```python
from geo_agent.skills.report import ReportSkill

skill = ReportSkill(output_file="report.md")
context = skill.execute(context)
```

## Pipeline position

GEOSearchSkill → **ReportSkill** → FilterSkill

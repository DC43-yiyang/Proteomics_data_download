# FilterSkill

## What it does

Filters and scores datasets by relevance. Removes irrelevant series before expensive downstream steps (Family SOFT fetch, LLM classification).

## Context I/O

| Direction | Field | Type |
|---|---|---|
| Input | `datasets` | `list[GEODataset]` |
| Input | `query` | `SearchQuery` |
| Output | `filtered_datasets` | `list[GEODataset]` sorted by `relevance_score` desc |

## Domain knowledge

- `min_score=0.0` passes everything — useful for debug, bad for production. For CITE-seq searches, `min_score=0.3` is a reasonable starting point.
- `exclude_keywords` is more useful than `required_keywords` in practice. GEO metadata is inconsistent — requiring specific keywords drops valid series. But excluding "organoid" or "mouse" when you only want human PBMC works well.
- This skill does NOT look at sample-level data. A series can score 0.8 here and still be useless (e.g. GSE280852 — high series-level relevance but zero CITE-seq sub-libraries). That's SampleSelectorSkill's job.

## Code entry

```python
from geo_agent.skills.filter import FilterSkill

skill = FilterSkill(min_samples=0, min_score=0.3, exclude_keywords=["organoid"])
context = skill.execute(context)
```

## Pipeline position

GEOSearchSkill → ReportSkill → **FilterSkill** → SampleSelectorSkill

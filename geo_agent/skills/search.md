# GEOSearchSkill

## What it does

Searches GEO via NCBI E-utilities (esearch → esummary → acc.cgi SOFT), returns datasets with metadata including Overall design.

## Context I/O

| Direction | Field | Type |
|---|---|---|
| Input | `query` | `SearchQuery` |
| Output | `datasets` | `list[GEODataset]` |
| Output | `total_found` | `int` |

## Domain knowledge

- `esearch` on GDS returns UIDs, not accessions. UIDs must go through `esummary` to get GSE accessions.
- GEO search is keyword-based and **returns false positives**. Searching "CITE-seq" returns series that merely mention it in the abstract (e.g. GSE280852 — only scRNA-seq, zero CITE-seq sub-libraries).
- `Overall design` is the most valuable field for downstream filtering — submitters describe experimental protocols there. It only exists in Series SOFT (`targ=self`), not in esummary.
- Series SOFT (`targ=self`) is small (~200 lines). Family SOFT (`targ=gsm`) is 10–50x larger and is NOT fetched here.

## Code entry

```python
from geo_agent.skills.search import GEOSearchSkill

skill = GEOSearchSkill(client=ncbi_client, fetch_details=True)
context = skill.execute(context)
```

## Pipeline position

First skill → ReportSkill, FilterSkill

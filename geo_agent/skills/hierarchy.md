# HierarchySkill

## What it does

Builds a SuperSeries / SubSeries family tree from `!Series_relation` fields already parsed into `GEODataset.relations`. Resolves titles for external references (series referenced in relations but not present in search results) via Series SOFT fetch.

## Context I/O

| Direction | Field | Type |
|---|---|---|
| Input | `datasets` | `list[GEODataset]` (with `relations` populated by GEOSearchSkill) |
| Output | `series_hierarchy` | `dict[str, SeriesNode]` — accession → node with role/parent/children |

## SeriesNode fields

| Field | Type | Description |
|---|---|---|
| `accession` | `str` | e.g. `"GSE164378"` |
| `title` | `str` | Series title (fetched for external refs if ncbi_client provided) |
| `role` | `str` | `"super"` / `"sub"` / `"standalone"` |
| `parent` | `str \| None` | Parent accession (set for sub nodes) |
| `children` | `list[str]` | Child accessions (set for super nodes) |
| `bioproject` | `str` | BioProject URL if present in relations |
| `in_search_results` | `bool` | `False` for placeholder nodes created for external references |

## Domain knowledge

- GEO CITE-seq searches frequently return SuperSeries **and** their SubSeries as separate hits. Without hierarchy resolution, the same underlying data appears multiple times in `datasets`.
- A SuperSeries referenced by a SubSeries may not be in the search results at all (e.g. it is a broader study). The skill creates placeholder nodes (`in_search_results=False`) for these and optionally fetches their titles.
- `relations` is populated by GEOSearchSkill from `!Series_relation` lines in Series SOFT. If `GEOSearchSkill` is run without `fetch_details=True`, relations will be empty and this skill produces no families.
- Three relation types are parsed: `SuperSeries of: GSExxxxx`, `SubSeries of: GSExxxxx`, `BioProject: https://...`.

## Code entry

```python
from geo_agent.skills.hierarchy import HierarchySkill

skill = HierarchySkill(
    ncbi_client=ncbi_client,                              # optional; needed to fill external titles
    families_file="tests/Test_hierarchy/hierarchy_families.json",    # optional; JSON output
    standalone_file="tests/Test_hierarchy/hierarchy_standalone.json", # optional; JSON output
)
context = skill.execute(context)
```

After execution, use the helper in `geo_agent/utils/hierarchy.py` to format output:

```python
from geo_agent.utils.hierarchy import format_series_hierarchy

print(format_series_hierarchy(context.series_hierarchy))
```

## JSON output format

### `hierarchy_standalone.json`

```json
{
  "generated_at": "2026-03-05T10:00:00+00:00",
  "count": 25,
  "series": [
    {"accession": "GSE266455", "title": "CITE-seq of T cells..."},
    ...
  ]
}
```

### `hierarchy_families.json`

```json
{
  "generated_at": "2026-03-05T10:00:00+00:00",
  "family_count": 3,
  "families": [
    {
      "super": {"accession": "GSE123", "title": "...", "in_search_results": true},
      "children": [
        {"accession": "GSE124", "title": "...", "in_search_results": true},
        {"accession": "GSE125", "title": "...", "in_search_results": false}
      ]
    }
  ]
}
```

`hierarchy_standalone.json` is consumed by `FetchFamilySoftSkill` test as its input — no re-querying needed.

## Pipeline position

GEOSearchSkill → **HierarchySkill** → FetchFamilySoftSkill → FamilySoftStructurerSkill → MultiomicsAnalyzerSkill

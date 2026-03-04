# SampleSelectorSkill

## What it does

Implements **Phase 1 (metadata preprocessing)** for LLM-driven sample selection.

Given GEO Family SOFT content, it extracts compact per-sample metadata and stores two outputs for downstream prompting:

1. Structured dict context (`context.sample_selector_context`)
2. Minified JSON string (`context.sample_selector_context_json`)

This phase intentionally does **not** run LLM classification.

## Context I/O

| Direction | Field | Type |
|---|---|---|
| Input | `filtered_datasets` or `datasets` | `list[GEODataset]` |
| Output | `sample_metadata` | `dict[str, list[GEOSample]]` |
| Output | `sample_selector_context` | `dict[str, dict]` |
| Output | `sample_selector_context_json` | `dict[str, str]` |

## Phase 1 extraction scope

For each `GSM`, keep only lightweight fields:

- `gsm_id`
- `sample_title`
- `characteristics` (prioritized keys first)
- `supplementary_files` (filename only, URL removed)
- optional `molecule`, `library_source`

Also add per-series summary fields:

- `sample_count`
- `samples_with_supp_files`
- `samples_without_supp_files`
- `characteristic_keys`

## Code entry

```python
from geo_agent.skills.sample_selector import SampleSelectorSkill

skill = SampleSelectorSkill(ncbi_client=ncbi_client)
context = skill.execute(context)

series_json = context.sample_selector_context_json["GSE317605"]
```

For local offline preprocessing (without NCBI API calls):

```python
from geo_agent.skills.sample_selector import preprocess_family_soft_directory

contexts = preprocess_family_soft_directory(
    input_dir="debug_family_soft",
    output_file="debug_phase1_context.json",
)
```

## Phase 2 API

```python
from geo_agent.skills.sample_selector import select_samples

result = select_samples(
    query="Extract all CITE-seq protein/ADT samples",
    metadata=contexts["GSE317605"],   # output from Phase 1
    llm_client=anthropic_client,
    model="claude-haiku-4-5-20251001",
    temperature=0.1,
)
```

Return schema:

- `is_false_positive`: `bool`
- `download_strategy`: `GSM_Level_Separated | GSE_Level_Bundled | Integrated_Object | None`
- `selected_samples`: list of `{gsm_id, sample_title, modality_inferred}`
- `reasoning`: concise string

## Why this design

- Keeps prompt payload small for large series (dozens of GSMs)
- Preserves core diagnostic metadata needed for later LLM reasoning
- Avoids brittle hard-matching rules in Phase 1

## Debug batch run (22 series)

Use:

```bash
.venv/bin/python run_selector_debug.py
```

Outputs:

- `selector_results_table.md` (human review table)
- `selector_results_debug.json` (full debug payload)

Current debug payload includes:

- Series-level decision (`is_false_positive`, `download_strategy`)
- Selected GSM IDs and titles
- Selected supplementary links (if present)
- Evidence keywords and extra counters for manual review

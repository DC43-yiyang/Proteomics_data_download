# GEO Agent - Proteomics Data Download Pipeline

## Project Overview

Python-based agentic pipeline for searching, fetching, parsing, and LLM-annotating GEO/NCBI multi-omics datasets. Skill-based architecture with sequential pipeline execution over a shared `PipelineContext`.

## Architecture

```
CLI (cli.py) --> Agent (agent.py) --> [Skill1, Skill2, ...] --> PipelineContext (shared state)
```

- **Entry point**: `geo_agent/cli.py` (`geo-agent` CLI command)
- **Orchestrator**: `geo_agent/agent.py` — thin sequential skill runner, zero business logic
- **Skills**: `geo_agent/skills/` — each reads/writes typed fields on `PipelineContext`
- **LLM layer**: `geo_agent/llm/` — factory pattern, two clients (Ollama local + OpenAI-compatible cloud)
- **Models**: `geo_agent/models/` — dataclasses for query, dataset, sample, context

## Key Patterns

- **Skill base class**: `Skill(ABC)` with `name: str` property and `execute(context) -> PipelineContext`
- **Error handling**: `SkillError` = recoverable (logged, pipeline continues); other exceptions = abort
- **LLM client contract**: All clients expose `.messages.create(model, messages, system, temperature, max_tokens)` and `.health_check()` — returns `response.choices[0].message.content`
- **LLM factory**: `create_llm_client()` dispatches on provider name → `OllamaClient` or `OpenAICompatibleClient`
- **No openai SDK dependency** — both clients use raw `requests` against `/v1/chat/completions`
- **Think tag stripping**: Both clients strip `<think>...</think>` tags by default (for reasoning models)

## Skills (execution order in pipeline)

| Skill | Module | Purpose |
|-------|--------|---------|
| GEOSearchSkill | `search.py` | Search NCBI GEO via Entrez |
| ReportSkill | `report.py` | Generate Markdown report |
| HierarchySkill | `hierarchy.py` | Classify SuperSeries/SubSeries/standalone |
| FilterSkill | `filter.py` | Filter by library type |
| FetchFamilySoftSkill | `fetch_family_soft.py` | Download Family SOFT files |
| FamilySoftStructurerSkill | `family_soft_structurer.py` | Parse SOFT → structured JSON |
| MultiomicsRunnerSkill | `multiomics_runner.py` | Orchestrate LLM annotation |
| MultiomicsAnalyzeSeriesSkill | `multiomics_analyze_series.py` | LLM annotation per series |
| MultiomicsAnalyzeSampleSkill | `multiomics_analyze_sample.py` | LLM annotation per sample |

## LLM Providers

| Provider | Default Model | Base URL |
|----------|--------------|----------|
| ollama (default) | `qwen3:30b-a3b` | `http://localhost:11434` |
| deepseek | `deepseek-chat` | `https://api.deepseek.com` |
| qwen | `qwen-plus` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| kimi | `moonshot-v1-8k` | `https://api.moonshot.cn/v1` |
| minimax | `abab6.5-chat` | `https://api.minimax.chat/v1` |
| openai | `gpt-4o-mini` | `https://api.openai.com` |

## Setup & Running

```bash
# Install
uv sync

# Configure
cp .env.example .env  # then edit with API keys

# Verify LLM
uv run python tests/verify_llm_setup.py
uv run python tests/test_llm_provider.py

# Run CLI
uv run geo-agent search --data-type "CITE-seq" --organism "Homo sapiens"
```

## Test Pipeline (sequential, each step depends on prior)

```bash
uv run python tests/01_Test_geo_search/run_geo_search.py        # Search GEO (needs NCBI_API_KEY)
uv run python tests/02_Test_hierarchy/run_hierarchy.py           # Classify hierarchy (local)
uv run python tests/03_Test_fetch_family_soft/run_fetch_family_soft.py  # Fetch Family SOFT (needs NCBI)
uv run python tests/04_Test_family_soft_parse/run_family_soft_parser_debug.py  # Parse SOFT (local)
uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py  # LLM annotation
```

## Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `NCBI_API_KEY` | — | NCBI Entrez API key (10 req/s vs 3) |
| `NCBI_EMAIL` | — | Required by NCBI |
| `LLM_PROVIDER` | `ollama` | Provider selector |
| `LLM_API_KEY` | — | Required for cloud providers |
| `LLM_BASE_URL` | — | Override provider URL |
| `LLM_ANNOTATION_MODEL` | provider-specific | Model name |
| `LLM_TEMPERATURE` | `0.0` | |
| `LLM_TIMEOUT` | `600` | Seconds |
| `PARALLEL_MODE` | `0` | 1 = parallel series processing |
| `NUM_WORKERS` | `4` | Thread pool size |
| `TARGET_SERIES` | all | Comma-separated GSE IDs |
| `STRICT_JSON_MODE` | `1` | Enforce JSON output |
| `DISABLE_THINKING` | `0` | Strip reasoning tokens |

## Tech Stack

- Python 3.10+ (dev: 3.13)
- Package manager: `uv`
- Dependencies: `requests`, `python-dotenv`, `anthropic`
- No `openai` SDK — LLM clients use raw HTTP

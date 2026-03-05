# Multiomics Stability And Rollback

This runner supports stability controls for local Qwen/Ollama JSON extraction.

## New defaults

- `STRICT_JSON_MODE=1`
- `LLM_TEMPERATURE=0.0`
- `RETRY_TEMP_STEP=0.0`
- `MAX_RETRIES=2`
- `DISABLE_THINKING=0` (off by default; opt-in)

## Environment variables

- `STRICT_JSON_MODE`:
  - `1` -> send `response_format={"type":"json_object"}`
  - `0` -> legacy free-form output mode
- `LLM_TEMPERATURE`: base sampling temperature
- `RETRY_TEMP_STEP`: added temperature for each retry
- `MAX_RETRIES`: parse/validate retry count
- `DISABLE_THINKING`:
  - `1` -> send `think=false` (if endpoint supports it)
  - `0` -> do not send `think` field
- `LLM_SEED`: optional seed for reproducibility
- `DEBUG_RAW_LLM_DIR`: directory to persist raw outputs when parse/validate fails

## Recommended stable run

```bash
STRICT_JSON_MODE=1 \
LLM_TEMPERATURE=0.0 \
RETRY_TEMP_STEP=0.0 \
MAX_RETRIES=2 \
DEBUG_RAW_LLM_DIR=debug_llm_raw \
uv run python run_multiomics_analysis.py
```

## One-command rollback to old behavior

```bash
STRICT_JSON_MODE=0 \
LLM_TEMPERATURE=0.1 \
RETRY_TEMP_STEP=0.05 \
DISABLE_THINKING=0 \
uv run python run_multiomics_analysis.py
```

This rollback reproduces the previous sampling pattern (non-JSON-mode, retry temperature increase).

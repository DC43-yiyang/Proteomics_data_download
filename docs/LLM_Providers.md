# OpenAI-Compatible LLM Integration

This document describes how to use Chinese commercial LLM APIs (DeepSeek, Qwen, Kimi, MiniMax) for multi-omics annotation.

## Supported Providers

| Provider | Base URL | Default Model | Notes |
|----------|----------|---------------|-------|
| **ollama** | `http://localhost:11434` | `qwen3:30b-a3b` | Local, no API key required |
| **deepseek** | `https://api.deepseek.com` | `deepseek-chat` | Cost-effective, supports reasoning |
| **qwen** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | Alibaba Cloud |
| **kimi** | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | Moonshot AI |
| **minimax** | `https://api.minimax.chat/v1` | `abab6.5-chat` | MiniMax |
| **openai** | `https://api.openai.com` | `gpt-4o-mini` | OpenAI (for reference) |

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# LLM Provider: ollama | deepseek | qwen | kimi | minimax | openai
LLM_PROVIDER=deepseek

# API Key (required for non-ollama providers)
LLM_API_KEY=sk-your-api-key-here

# Base URL (optional, uses provider default if not specified)
LLM_BASE_URL=

# Model name for annotation (provider-specific)
LLM_ANNOTATION_MODEL=deepseek-chat
```

### Provider-Specific Examples

#### DeepSeek (Recommended for Cost)

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-deepseek-key
LLM_ANNOTATION_MODEL=deepseek-chat
```

**Models**:
- `deepseek-chat` - Standard chat model (¥1/M tokens input, ¥2/M tokens output)
- `deepseek-reasoner` - Reasoning model with chain-of-thought

**Get API Key**: https://platform.deepseek.com/

#### Qwen (Alibaba Cloud)

```bash
LLM_PROVIDER=qwen
LLM_API_KEY=sk-your-qwen-key
LLM_ANNOTATION_MODEL=qwen-plus
```

**Models**:
- `qwen-turbo` - Fast, cost-effective
- `qwen-plus` - Balanced performance
- `qwen-max` - Most capable

**Get API Key**: https://dashscope.console.aliyun.com/

#### Kimi (Moonshot)

```bash
LLM_PROVIDER=kimi
LLM_API_KEY=sk-your-kimi-key
LLM_ANNOTATION_MODEL=moonshot-v1-32k
```

**Models**:
- `moonshot-v1-8k` - 8K context
- `moonshot-v1-32k` - 32K context
- `moonshot-v1-128k` - 128K context

**Get API Key**: https://platform.moonshot.cn/

#### MiniMax

```bash
LLM_PROVIDER=minimax
LLM_API_KEY=your-minimax-key
LLM_ANNOTATION_MODEL=abab6.5-chat
```

**Models**:
- `abab6.5-chat` - Standard chat
- `abab6.5s-chat` - Faster variant

**Get API Key**: https://www.minimaxi.com/

## Usage

### Basic Usage

Once configured, run annotation as usual:

```bash
# Per-series annotation (recommended)
TARGET_SERIES=GSE266455 uv run python tests/Test_multiomics_analysis/run_multiomics_analysis_series.py

# Per-sample annotation
TARGET_SERIES=GSE266455 uv run python tests/Test_multiomics_analysis/run_multiomics_analysis.py
```

### Override Provider at Runtime

You can override the provider without editing `.env`:

```bash
# Use DeepSeek for this run
LLM_PROVIDER=deepseek \
LLM_API_KEY=sk-xxx \
LLM_ANNOTATION_MODEL=deepseek-chat \
TARGET_SERIES=GSE266455 \
uv run python tests/Test_multiomics_analysis/run_multiomics_analysis_series.py
```

### Test Connection

```python
from geo_agent.llm import create_llm_client

# Test DeepSeek connection
client = create_llm_client(
    provider="deepseek",
    api_key="sk-your-key",
)

if client.health_check():
    print("✓ Connected")
    print(f"Available models: {client.list_models()}")
else:
    print("✗ Connection failed")
```

## Cost Comparison

Estimated cost for annotating 1000 samples (assuming ~3.5K input tokens, ~500 output tokens per series):

| Provider | Model | Input Cost | Output Cost | Total (1000 samples) |
|----------|-------|------------|-------------|---------------------|
| **DeepSeek** | deepseek-chat | ¥1/M | ¥2/M | ~¥4.5 (~$0.62) |
| **Qwen** | qwen-plus | ¥4/M | ¥12/M | ~¥20 (~$2.75) |
| **Kimi** | moonshot-v1-32k | ¥12/M | ¥12/M | ~¥54 (~$7.40) |
| **Ollama** | qwen3:30b-a3b | Free | Free | Free (local compute) |

*Prices are approximate and subject to change. Check provider websites for current pricing.*

## Migration from Ollama

If you're currently using local Ollama and want to switch to a commercial API:

1. **Keep Ollama as fallback** - Set `LLM_PROVIDER=ollama` in `.env` (default)
2. **Test with DeepSeek** - Override at runtime to test:
   ```bash
   LLM_PROVIDER=deepseek LLM_API_KEY=sk-xxx TARGET_SERIES=GSE266455 uv run python tests/...
   ```
3. **Compare results** - Verify annotation quality matches Ollama
4. **Switch permanently** - Update `.env` once satisfied

## Troubleshooting

### Connection Failed

```
ERROR: LLM client not reachable (provider: deepseek, base_url: https://api.deepseek.com)
```

**Solutions**:
- Check API key is correct
- Verify network connectivity (try `curl https://api.deepseek.com/v1/models`)
- Check if provider requires VPN/proxy in your region

### Invalid API Key

```
RuntimeError: OpenAI-compatible API request failed: 401 Client Error: Unauthorized
```

**Solutions**:
- Verify `LLM_API_KEY` is set correctly
- Check API key hasn't expired
- Ensure sufficient credits/balance

### Model Not Found

```
RuntimeError: OpenAI-compatible API request failed: 404 Client Error: Not Found
```

**Solutions**:
- Check model name is correct for the provider
- Use `client.list_models()` to see available models
- Refer to provider documentation for model names

### JSON Parse Failures

If you see frequent JSON parse errors with a new provider:

```bash
# Enable strict JSON mode (default)
STRICT_JSON_MODE=1 uv run python tests/...

# Disable thinking tags if provider doesn't support them
DISABLE_THINKING=1 uv run python tests/...

# Save failed responses for debugging
DEBUG_RAW_LLM_DIR=./debug_llm uv run python tests/...
```

## Advanced Configuration

### Custom Timeout

```bash
LLM_TIMEOUT=1200  # 20 minutes for large series
```

### Retry Strategy

```bash
MAX_RETRIES=3              # Retry up to 3 times
LLM_TEMPERATURE=0.0        # Start with temperature 0
RETRY_TEMP_STEP=0.05       # Increase by 0.05 on each retry
```

### Parallel Processing

```bash
NUM_WORKERS=4  # Process 4 samples in parallel (per-sample mode only)
```

## API Client Implementation

The implementation uses a unified interface compatible with both Ollama and OpenAI-style APIs:

```python
# Both clients expose the same interface
client.messages.create(
    model="model-name",
    system="System prompt",
    messages=[{"role": "user", "content": "..."}],
    temperature=0.1,
    max_tokens=4096,
)
```

This allows seamless switching between providers without code changes.

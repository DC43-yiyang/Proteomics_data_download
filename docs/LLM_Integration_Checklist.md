# LLM Integration Checklist

## 项目中所有使用 LLM 的地方

### ✅ 已更新为支持多 Provider

#### 1. Multi-omics Annotation (Branch B)
**位置**: `geo_agent/skills/multiomics_analyze_series.py` + `multiomics_analyze_sample.py`

**用途**:
- 对 GEO 样本进行三层注释（measured_layers, experiment, assay）
- 推断 disease, tissue, platform 等信息

**调用方式**:
```python
from geo_agent.llm import create_llm_client

client = create_llm_client(
    provider=config.llm_provider,
    api_key=config.llm_api_key,
    base_url=config.llm_base_url,
)
```

**配置变量**:
- `LLM_PROVIDER` - provider 名称
- `LLM_API_KEY` - API key
- `LLM_BASE_URL` - base URL（可选）
- `LLM_ANNOTATION_MODEL` - 模型名称

**测试脚本**:
- `tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py` (推荐)
- `tests/05_Test_multiomics_analysis/run_multiomics_analysis.py` (per-sample)

**状态**: ✅ 已完全支持所有 provider

---

### ⚠️ 未更新（使用旧的 Anthropic API）

#### 2. Sample Selector (Branch A - 已废弃?)
**位置**: `geo_agent/skills/sample_selector.py`

**用途**:
- 基于查询条件对样本进行分类
- 使用 Anthropic Claude 进行智能筛选

**配置变量**:
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `LLM_MODEL` (默认: claude-haiku-4-5-20251001)

**状态**: ⚠️ 仍使用旧的 Anthropic API（但可能已不再使用）

**检查**: 让我确认这个 skill 是否还在使用中...

---

## 配置文件检查

### `.env` 文件结构

```bash
# ============================================================================
# NCBI API (用于 GEO 数据获取)
# ============================================================================
NCBI_API_KEY=
NCBI_EMAIL=

# ============================================================================
# Anthropic API (Legacy - 仅用于旧的 sample classification)
# ============================================================================
ANTHROPIC_BASE_URL=https://www.fucheers.top/v1
ANTHROPIC_API_KEY=sk-xxx
LLM_MODEL=claude-haiku-4-5-20251001

# ============================================================================
# Multi-omics Annotation LLM (新系统 - 支持多 Provider)
# ============================================================================
LLM_PROVIDER=openai
LLM_API_KEY=sk-ikwZw0PLEv4mO5vssWUbyBfS4SJ4QRZNJ7rqhaJ9S8GFBLfQ
LLM_BASE_URL=https://api.vectorengine.ai/v1
LLM_ANNOTATION_MODEL=qwen3.5-plus-2026-02-15
```

### 配置优先级

1. **环境变量** (命令行设置) - 最高优先级
2. **`.env` 文件** - 中等优先级
3. **代码默认值** - 最低优先级

---

## 完整流程图

```
用户查询
   │
   ├─ Branch A: GEO Search & Report (不使用 LLM)
   │    ├─ GEOSearchSkill (NCBI API)
   │    ├─ HierarchySkill (解析 SOFT)
   │    ├─ ReportSkill (生成报告)
   │    └─ FilterSkill (规则过滤)
   │
   └─ Branch B: Multi-omics Annotation (使用 LLM)
        ├─ HierarchySkill (过滤 standalone series)
        ├─ FetchFamilySoftSkill (NCBI API)
        ├─ FamilySoftStructurerSkill (解析 SOFT)
        ├─ MultiomicsSeriesAnalyzerSkill ⭐ 使用 LLM
        │    └─ create_llm_client() → 支持多 provider
        └─ PersistSkill (写入 SQLite)
```

---

## 测试验证

### 1. 测试 LLM 连接
```bash
uv run python tests/test_llm_provider.py
```

### 2. 测试多组学注释（单个系列）
```bash
TARGET_SERIES=GSE266455 \
uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py
```

### 3. 测试多组学注释（所有系列）
```bash
uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py
```

### 4. 验证输出文件
```bash
ls -lh tests/05_Test_multiomics_analysis/debug_multiomics_analysis/
```

输出文件命名格式：
- `{series_id}_{model_slug}_series_results.json`
- `{series_id}_{model_slug}_series_results_table.md`

其中 `model_slug` = `model_name.replace(":", "_").replace("/", "_")`

例如：
- `qwen3:30b-a3b` → `qwen3_30b-a3b`
- `qwen3.5-plus-2026-02-15` → `qwen3.5-plus-2026-02-15`

**不同模型的输出文件不会互相覆盖！**

---

## 潜在问题和注意事项

### 1. ⚠️ SampleSelectorSkill 未更新
- 位置: `geo_agent/skills/sample_selector.py`
- 状态: 仍使用 Anthropic API
- 影响: 如果这个 skill 还在使用，需要更新

### 2. ✅ 路径问题已修复
- 测试脚本中的路径从 `Test_family_soft_parse` 更新为 `04_Test_family_soft_parse`

### 3. ✅ URL 重复问题已修复
- OpenAI 兼容客户端现在正确处理 base_url 中的 `/v1` 后缀

### 4. ⚠️ API 速率限制
- VectorEngine API 可能有速率限制
- 建议在批量处理时添加适当的延迟

### 5. ✅ 输出文件命名
- 每个模型都有独立的输出文件
- 不会覆盖之前的结果

---

## 下一步建议

1. **确认 SampleSelectorSkill 是否还在使用**
   - 如果是，需要更新为支持多 provider
   - 如果不是，可以标记为 deprecated

2. **更新 Architecture.md**
   - 添加新的 LLM provider 支持说明
   - 更新 OllamaClient 为 "支持多 provider"

3. **添加成本追踪**
   - 记录每次 API 调用的 token 使用量
   - 计算总成本

4. **添加重试和错误处理**
   - 对于 503/429 等临时错误，增加指数退避重试
   - 保存失败的请求以便后续重试

5. **性能优化**
   - 考虑批量处理时的并行化
   - 添加本地缓存避免重复调用

# GEO Multi-omics Annotation System - 完整使用指南

## 概述

本系统支持**双模式 LLM 后端**，可以灵活切换：

| 模式 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **本地 Ollama** | 免费、数据隐私、无网络依赖 | 需要 GPU、模型下载大 | 有本地 GPU 资源、大批量处理 |
| **商业 API** | 无需本地资源、模型更新快 | 按 token 计费、需要网络 | 无 GPU、小批量测试、使用最新模型 |

---

## 1. 系统架构

### LLM 使用位置

系统中**只有一个地方**使用 LLM：

**Multi-omics Annotation (Branch B)**
- **位置**: `geo_agent/skills/multiomics_analyze_series.py` + `multiomics_analyze_sample.py`
- **功能**: 对 GEO 样本进行智能注释
  - 识别分子层（RNA, protein_surface, TCR_VDJ 等）
  - 推断实验类型（CITE-seq, 10x Multiome 等）
  - 标准化 disease, tissue 信息
- **调用方式**: 通过 `create_llm_client()` 工厂函数自动选择后端

### 数据流程

```
GEO 搜索
   ↓
层级过滤（standalone series）
   ↓
获取 Family SOFT 文件
   ↓
解析为结构化 JSON
   ↓
⭐ LLM 注释 ⭐  ← 唯一使用 LLM 的地方
   ↓
写入 SQLite 数据库
```

---

## 2. 配置方式

### 方式 1: 本地 Ollama（推荐用于大批量）

**前提条件**:
- 已安装 Ollama: https://ollama.ai/
- 已下载模型: `ollama pull qwen3:30b-a3b`
- Ollama 服务运行中: `ollama serve`

**配置 `.env`**:
```bash
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_ANNOTATION_MODEL=qwen3:30b-a3b
# 不需要 API key
```

**优点**:
- ✅ 完全免费
- ✅ 数据不出本地
- ✅ 适合大批量处理（26 个系列约 2 小时）

**缺点**:
- ❌ 需要 GPU（推荐 16GB+ VRAM）
- ❌ 首次需要下载模型（~20GB）

---

### 方式 2: 商业 API（推荐用于测试）

**支持的 Provider**:

| Provider | Base URL | 推荐模型 | 成本估算 |
|----------|----------|----------|----------|
| **VectorEngine** | `https://api.vectorengine.ai/v1` | `qwen3.5-plus-2026-02-15` | 按实际使用 |
| **DeepSeek** | `https://api.deepseek.com` | `deepseek-chat` | ¥1/M input, ¥2/M output |
| **Qwen** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | ¥4/M input, ¥12/M output |
| **Kimi** | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` | ¥12/M input, ¥12/M output |
| **MiniMax** | `https://api.minimax.chat/v1` | `abab6.5-chat` | 按实际使用 |

**配置 `.env` (以 VectorEngine 为例)**:
```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=https://api.vectorengine.ai/v1
LLM_ANNOTATION_MODEL=qwen3.5-plus-2026-02-15
```

**优点**:
- ✅ 无需本地 GPU
- ✅ 模型更新快
- ✅ 适合快速测试

**缺点**:
- ❌ 按 token 计费
- ❌ 需要稳定网络

---

## 3. 快速开始

### 步骤 1: 验证配置

```bash
uv run python tests/verify_llm_setup.py
```

**预期输出**:
```
✓ Provider: openai (或 ollama)
✓ Model: qwen3.5-plus-2026-02-15
✓ API 连接正常
✓ LLM 响应成功
✓ 所有检查通过！
```

---

### 步骤 2: 测试单个系列

```bash
TARGET_SERIES=GSE266455 \
uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py
```

**预期输出**:
```
21:02:55 INFO   GSE266455 done | layers: ['RNA', 'protein_surface'] | disease: healthy | tissue: PBMC
processed : 1  ok: 1  errors: 0
```

**输出文件**:
- `tests/05_Test_multiomics_analysis/debug_multiomics_analysis/GSE266455_{model}_series_results.json`
- `tests/05_Test_multiomics_analysis/debug_multiomics_analysis/GSE266455_{model}_series_results_table.md`

其中 `{model}` 是模型名称的 slug（如 `qwen3.5-plus-2026-02-15`）

---

### 步骤 3: 批量处理所有系列

```bash
uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py
```

**处理时间估算**:
- 本地 Ollama: ~2 小时（26 个系列）
- 商业 API: ~1.5 小时（取决于 API 速度）

---

## 4. 切换模式

### 临时切换（不修改 `.env`）

```bash
# 临时使用商业 API
LLM_PROVIDER=openai \
LLM_API_KEY=sk-xxx \
LLM_BASE_URL=https://api.vectorengine.ai/v1 \
LLM_ANNOTATION_MODEL=qwen3.5-plus-2026-02-15 \
TARGET_SERIES=GSE266455 \
uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py

# 临时使用本地 Ollama
LLM_PROVIDER=ollama \
LLM_ANNOTATION_MODEL=qwen3:30b-a3b \
TARGET_SERIES=GSE266455 \
uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py
```

### 永久切换（修改 `.env`）

编辑 `.env` 文件，修改 `LLM_PROVIDER` 和相关配置即可。

---

## 5. 输出文件说明

### 文件命名规则

```
{series_id}_{model_slug}_series_results.json
{series_id}_{model_slug}_series_results_table.md
```

**model_slug 转换规则**:
- `qwen3:30b-a3b` → `qwen3_30b-a3b`
- `qwen3.5-plus-2026-02-15` → `qwen3.5-plus-2026-02-15`

**不同模型的输出文件不会互相覆盖！**

### 示例

```bash
ls tests/05_Test_multiomics_analysis/debug_multiomics_analysis/

# 本地 Ollama 的结果
GSE266455_qwen3_30b-a3b_series_results.json
GSE266455_qwen3_30b-a3b_series_results_table.md

# 商业 API 的结果
GSE266455_qwen3.5-plus-2026-02-15_series_results.json
GSE266455_qwen3.5-plus-2026-02-15_series_results_table.md
```

---

## 6. 高级配置

### 环境变量完整列表

```bash
# ============================================================================
# LLM Provider 配置
# ============================================================================
LLM_PROVIDER=ollama              # ollama | deepseek | qwen | kimi | minimax | openai
LLM_API_KEY=                     # API key (ollama 不需要)
LLM_BASE_URL=                    # Base URL (可选，使用 provider 默认值)
LLM_ANNOTATION_MODEL=qwen3:30b-a3b  # 模型名称

# ============================================================================
# 运行时参数
# ============================================================================
TARGET_SERIES=                   # 指定系列 ID，逗号分隔（默认：全部）
NUM_WORKERS=1                    # 并行数（per-series 模式建议 1）
MAX_RETRIES=2                    # 失败重试次数
LLM_TEMPERATURE=0.0              # 温度（0.0 = 确定性输出）
RETRY_TEMP_STEP=0.0              # 重试时温度增量
STRICT_JSON_MODE=1               # 严格 JSON 模式（1=开启）
DISABLE_THINKING=0               # 禁用思考标签（1=禁用）
MAX_TOKENS=16384                 # 最大输出 token 数
LLM_TIMEOUT=600                  # 请求超时（秒）
DEBUG_RAW_LLM_DIR=               # 保存失败响应的目录（调试用）
```

### 性能优化建议

**本地 Ollama**:
```bash
# 使用量化模型加速
LLM_ANNOTATION_MODEL=qwen3.5:35b-a3b-q8_0

# 减少最大 token 数
MAX_TOKENS=8192
```

**商业 API**:
```bash
# 禁用思考标签减少 token 消耗
DISABLE_THINKING=1

# 使用更快的模型
LLM_ANNOTATION_MODEL=qwen-turbo  # (Qwen provider)
```

---

## 7. 故障排查

### 问题 1: Ollama 连接失败

```
ERROR: LLM client not reachable (provider: ollama, base_url: http://localhost:11434)
```

**解决方案**:
1. 检查 Ollama 是否运行: `ollama list`
2. 启动 Ollama: `ollama serve`
3. 验证模型已下载: `ollama pull qwen3:30b-a3b`

---

### 问题 2: 商业 API 认证失败

```
RuntimeError: OpenAI-compatible API request failed: 401 Client Error: Unauthorized
```

**解决方案**:
1. 检查 `LLM_API_KEY` 是否正确
2. 验证 API key 是否过期
3. 确认账户余额充足

---

### 问题 3: 503 Service Unavailable

```
RuntimeError: OpenAI-compatible API request failed: 503 Server Error
```

**解决方案**:
1. 等待几秒后重试（可能是临时限流）
2. 检查网络连接
3. 尝试其他 provider

---

### 问题 4: JSON 解析失败

```
ValueError: no JSON object in LLM output
```

**解决方案**:
```bash
# 启用严格 JSON 模式
STRICT_JSON_MODE=1

# 禁用思考标签
DISABLE_THINKING=1

# 保存失败响应以便调试
DEBUG_RAW_LLM_DIR=./debug_llm
```

---

## 8. 成本估算

### 单个系列（48 个样本）

| Provider | 输入 tokens | 输出 tokens | 成本 |
|----------|-------------|-------------|------|
| Ollama (本地) | ~3,400 | ~500 | ¥0 |
| VectorEngine | ~3,400 | ~500 | ~¥0.01 |
| DeepSeek | ~3,400 | ~500 | ~¥0.004 |
| Qwen | ~3,400 | ~500 | ~¥0.02 |

### 批量处理（26 个系列）

| Provider | 总成本估算 |
|----------|-----------|
| Ollama (本地) | ¥0（免费） |
| VectorEngine | ~¥0.26 |
| DeepSeek | ~¥0.10 |
| Qwen | ~¥0.52 |

*成本仅供参考，实际费用以 provider 官网为准*

---

## 9. 最佳实践

### 开发/测试阶段

1. **使用商业 API 快速验证**
   ```bash
   LLM_PROVIDER=deepseek  # 成本最低
   TARGET_SERIES=GSE266455  # 单个系列测试
   ```

2. **验证输出质量**
   - 检查 `_series_results_table.md` 文件
   - 确认 `measured_layers`, `experiment`, `assay` 正确

3. **调整 prompt 或参数**
   - 修改 `multiomics_analyze_series.md` 中的 prompt
   - 调整 `LLM_TEMPERATURE` 等参数

### 生产/批量处理阶段

1. **切换到本地 Ollama**
   ```bash
   LLM_PROVIDER=ollama
   # 处理全部系列
   ```

2. **监控进度**
   - 观察日志输出
   - 检查 `debug_multiomics_analysis/` 目录

3. **验证结果**
   ```bash
   # 统计成功/失败数量
   grep "ok:" tests/05_Test_multiomics_analysis/debug_multiomics_analysis/*.log
   ```

---

## 10. 相关文档

- **LLM Provider 详细配置**: `docs/LLM_Providers.md`
- **系统架构说明**: `docs/Architecture.md`
- **集成检查清单**: `docs/LLM_Integration_Checklist.md`

---

## 11. 常见问题

**Q: 可以同时使用多个 provider 吗？**

A: 可以。通过环境变量临时切换，不同模型的输出文件不会互相覆盖。

**Q: 哪个模型质量最好？**

A: 根据测试，`qwen3.5-plus-2026-02-15` (VectorEngine) 和 `qwen3:30b-a3b` (Ollama) 质量相当，都能正确识别 CITE-seq 等复杂实验类型。

**Q: 如何减少 API 成本？**

A:
1. 使用 DeepSeek（成本最低）
2. 启用 `DISABLE_THINKING=1`
3. 减少 `MAX_TOKENS`
4. 批量处理时使用本地 Ollama

**Q: 输出文件可以合并吗？**

A: 可以。所有结果都是标准 JSON 格式，可以用脚本合并。系统后续会添加 `PersistSkill` 自动写入 SQLite 数据库。

---

## 12. 更新日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-05 | v1.0 | 初始版本，支持 Ollama + 商业 API 双模式 |

# 并行处理使用指南

## 概述

系统支持两种处理模式：

| 模式 | 特点 | 适用场景 | 输出结构 |
|------|------|----------|----------|
| **串行模式** | 一个接一个处理 | 稳定、调试、小批量 | 合并的 JSON 文件 |
| **并行模式** | 多个同时处理 | 大批量、加速处理 | 每个 series 独立文件 |

---

## 1. 串行模式（默认）

### 配置

```bash
# .env 文件
PARALLEL_MODE=0
NUM_WORKERS=1
```

### 运行

```bash
# 处理所有 series（22 个）
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py

# 处理指定 series
TARGET_SERIES=GSE266455,GSE268991 \
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py
```

### 输出结构

```
debug_parallel_online_multicomics_analysis/
├── qwen3.5-plus-2026-02-15_series_results.json       # 所有结果合并
└── qwen3.5-plus-2026-02-15_series_results_table.md   # 汇总表格
```

### 特点

- ✅ 稳定可靠
- ✅ 便于调试
- ✅ 单个合并文件
- ❌ 处理速度慢（22 个 series 约 1.5-2 小时）

---

## 2. 并行模式

### 配置

```bash
# .env 文件
PARALLEL_MODE=1
NUM_WORKERS=4  # 同时处理 4 个 series
```

### 运行

```bash
# 并行处理所有 series
PARALLEL_MODE=1 NUM_WORKERS=4 \
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py

# 并行处理指定 series
PARALLEL_MODE=1 NUM_WORKERS=4 TARGET_SERIES=GSE266455,GSE268991,GSE269123 \
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py
```

### 输出结构

```
debug_parallel_online_multicomics_analysis/
├── series/
│   ├── GSE266455/
│   │   ├── qwen3.5-plus-2026-02-15_result.json
│   │   └── qwen3.5-plus-2026-02-15_result_table.md
│   ├── GSE268991/
│   │   ├── qwen3.5-plus-2026-02-15_result.json
│   │   └── qwen3.5-plus-2026-02-15_result_table.md
│   └── ... (每个 series 一个目录)
├── qwen3.5-plus-2026-02-15_series_results.json       # 也保存合并文件
└── qwen3.5-plus-2026-02-15_series_results_table.md
```

### 特点

- ✅ 处理速度快（4 workers 约 30-40 分钟）
- ✅ 每个 series 独立保存
- ✅ 失败不影响其他 series
- ⚠️ 需要注意 API 速率限制

---

## 3. NUM_WORKERS 设置建议

### 本地 Ollama

```bash
# 根据 GPU 内存调整
NUM_WORKERS=1  # 单卡，避免 OOM
NUM_WORKERS=2  # 双卡或大内存卡
```

### 商业 API

| Provider | 推荐 Workers | 原因 |
|----------|--------------|------|
| **VectorEngine** | 4-8 | 速率限制较宽松 |
| **DeepSeek** | 2-4 | 有速率限制 |
| **Qwen** | 2-4 | 有速率限制 |
| **Kimi** | 2-4 | 有速率限制 |

**注意**：设置过高可能触发 429 (Too Many Requests) 错误。

---

## 4. 完整示例

### 示例 1: 串行处理所有 series（稳定）

```bash
# 使用 .env 配置
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py
```

### 示例 2: 并行处理所有 series（快速）

```bash
PARALLEL_MODE=1 NUM_WORKERS=4 \
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py
```

### 示例 3: 并行处理指定 series

```bash
PARALLEL_MODE=1 NUM_WORKERS=4 \
TARGET_SERIES=GSE266455,GSE268991,GSE269123 \
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py
```

### 示例 4: 测试单个 series（调试）

```bash
TARGET_SERIES=GSE266455 \
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py
```

---

## 5. 监控进度

### 查看日志

```bash
# 实时查看进度
tail -f tests/05_Test_multiomics_analysis/debug_parallel_online_multicomics_analysis/run.log
```

### 检查已完成的 series

```bash
# 串行模式
ls -lh tests/05_Test_multiomics_analysis/debug_parallel_online_multicomics_analysis/*.json

# 并行模式
ls -d tests/05_Test_multiomics_analysis/debug_parallel_online_multicomics_analysis/series/*/
```

---

## 6. 故障排查

### 问题 1: 429 Too Many Requests

```
RuntimeError: OpenAI-compatible API request failed: 429 Client Error: Too Many Requests
```

**解决方案**：
```bash
# 减少并行数
NUM_WORKERS=2  # 从 4 降到 2

# 或切换到串行模式
PARALLEL_MODE=0 NUM_WORKERS=1
```

---

### 问题 2: 部分 series 失败

**并行模式优势**：失败的 series 不影响其他 series

**检查失败的 series**：
```bash
# 查看合并文件中的 error 字段
grep -A 5 '"error"' debug_parallel_online_multicomics_analysis/*_series_results.json
```

**重新处理失败的 series**：
```bash
TARGET_SERIES=GSE123456,GSE789012 \
uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py
```

---

### 问题 3: 内存不足（Ollama）

```
RuntimeError: CUDA out of memory
```

**解决方案**：
```bash
# 使用串行模式
PARALLEL_MODE=0 NUM_WORKERS=1

# 或使用量化模型
LLM_ANNOTATION_MODEL=qwen3.5:35b-a3b-q8_0
```

---

## 7. 性能对比

### 处理 22 个 series 的时间估算

| 模式 | Workers | 本地 Ollama | VectorEngine API |
|------|---------|-------------|------------------|
| 串行 | 1 | ~2 小时 | ~1.5 小时 |
| 并行 | 2 | ~1 小时 | ~45 分钟 |
| 并行 | 4 | ~30 分钟* | ~30 分钟 |
| 并行 | 8 | ~20 分钟* | ~20 分钟 |

\* 需要足够的 GPU 内存或 API 速率限制允许

---

## 8. 最佳实践

### 开发/测试阶段

1. **先测试单个 series**
   ```bash
   TARGET_SERIES=GSE266455 uv run python tests/...
   ```

2. **验证输出质量**
   - 检查 JSON 结构
   - 确认注释准确性

3. **小批量测试并行**
   ```bash
   PARALLEL_MODE=1 NUM_WORKERS=2 TARGET_SERIES=GSE266455,GSE268991 uv run python tests/...
   ```

### 生产/批量处理阶段

1. **使用并行模式加速**
   ```bash
   PARALLEL_MODE=1 NUM_WORKERS=4 uv run python tests/...
   ```

2. **监控进度和错误**
   ```bash
   tail -f debug_parallel_online_multicomics_analysis/run.log
   ```

3. **处理失败的 series**
   ```bash
   # 提取失败的 series ID
   grep '"error"' *_series_results.json | grep -oP 'GSE\d+'

   # 重新处理
   TARGET_SERIES=GSE123456 uv run python tests/...
   ```

---

## 9. 输出文件说明

### 串行模式输出

**合并 JSON** (`{model_slug}_series_results.json`):
```json
{
  "model": "qwen3.5-plus-2026-02-15",
  "generated_at_utc": "2026-03-05T...",
  "series_count": 22,
  "parallel_mode": false,
  "num_workers": 1,
  "results": {
    "GSE266455": { ... },
    "GSE268991": { ... },
    ...
  }
}
```

### 并行模式输出

**单个 series JSON** (`series/{series_id}/{model_slug}_result.json`):
```json
{
  "model": "qwen3.5-plus-2026-02-15",
  "generated_at_utc": "2026-03-05T...",
  "series_id": "GSE266455",
  "result": {
    "series_id": "GSE266455",
    "disease_normalized": "healthy",
    "tissue_normalized": "PBMC",
    "sample_count": 48,
    "samples": [ ... ]
  }
}
```

---

## 10. 常见问题

**Q: 并行模式会覆盖串行模式的结果吗？**

A: 不会。输出目录不同：
- 串行/并行共用: `debug_parallel_online_multicomics_analysis/`
- 但并行模式额外保存到 `series/` 子目录

**Q: 可以中途切换模式吗？**

A: 可以。不同模式的输出文件不会互相覆盖。

**Q: 并行模式下如何知道哪些 series 已完成？**

A: 检查 `series/` 目录下的子目录数量：
```bash
ls -d series/*/ | wc -l
```

**Q: 推荐使用哪种模式？**

A:
- **调试/测试**: 串行模式（稳定）
- **生产/批量**: 并行模式（快速）
- **API 有速率限制**: 串行或低并行数（NUM_WORKERS=2）

---

## 11. 相关文档

- **完整使用指南**: `docs/Usage_Guide.md`
- **LLM Provider 配置**: `docs/LLM_Providers.md`
- **系统架构**: `docs/Architecture.md`

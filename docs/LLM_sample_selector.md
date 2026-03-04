# LLM 生信样本智能筛选（Selector Only）计划书

## 1. 项目定位

本项目目标是做一个 **样本筛选器（Selector）**，不是下载器。

- 输入：自然语言筛选需求 + GEO 系列/样本元数据（Family SOFT 预处理结果）
- 输出：可人工复核的筛选结果表（重点是“选中哪些 sample + 对应下载链接”）
- 当前阶段：Debug 阶段，优先“信息充分、可审计、可复核”

---

## 2. 范围边界（重要）

### 2.1 包含

- 识别目标 sample（例如 ADT / Surface / AbSeq / CITE 蛋白相关）
- 识别假阳性系列（标题提到 CITE-seq，但样本层面无蛋白证据）
- 输出可检查的表格 + 调试字段（证据、置信度、规则命中情况）

### 2.2 不包含

- 不做自动下载
- 不做下载路由执行（仅输出链接与建议）

---

## 3. 关键痛点（Selector 视角）

1. **命名不统一**：ADT 可能叫 ADT / Surface / Antibody / AbSeq / Tags
2. **摘要假阳性**：Series 介绍写 CITE-seq，但样本都是 RNA
3. **GSM 无文件或信息不足**：样本标题有 GEX/ADT 拆分，但 sample 级链接为空
4. **整合对象**：可能是 integrated 对象（如 `.h5ad` / `.rds`），非显式分模态

---

## 4. 输入与输出规范

### 4.1 输入

- `query`：用户自然语言目标（例如：`Extract all CITE-seq protein/ADT samples`）
- `metadata`：Phase 1 预处理后的单个 GSE JSON（包含 sample 列表与精简字段）

### 4.2 输出（核心 JSON）

```json
{
  "is_false_positive": false,
  "download_strategy": "GSM_Level_Separated",
  "selected_samples": [
    {
      "gsm_id": "GSMXXXXXXX",
      "sample_title": "...",
      "modality_inferred": "ADT"
    }
  ],
  "reasoning": "..."
}
```

---

## 5. 人工复核用表格（主输出）

运行后按 **每个 GSE 一行（可展开 sample）** 输出汇总表，至少包含以下列：

| 列名 | 说明 |
|---|---|
| `series_id` | GSE 编号 |
| `is_false_positive` | 是否判定为假阳性 |
| `download_strategy` | 仅用于定位数据组织方式（不执行下载） |
| `selected_gsm_count` | 被选中的 sample 数量 |
| `selected_gsm_ids` | 被选中的 GSM 列表 |
| `selected_sample_titles` | 被选中 sample 标题（可截断） |
| `selected_links` | 被选中 sample 的 supplementary file 链接（尽可能完整） |
| `reasoning` | 简要判定理由 |

---

## 6. Debug 阶段增强字段（建议尽量多输出）

为了便于人工反馈，建议额外输出调试列：

| 列名 | 说明 |
|---|---|
| `total_samples` | 该 GSE 下样本总数 |
| `samples_with_files` | 有 sample 级文件的样本数 |
| `samples_without_files` | 无 sample 级文件的样本数 |
| `candidate_adt_like_count` | 被规则/模型初判为 ADT-like 的样本数 |
| `excluded_rna_like_count` | 被排除的 RNA-only 样本数 |
| `confidence_summary` | 置信度摘要（min/mean/max） |
| `evidence_keywords` | 命中的关键词（ADT/Surface/AbSeq/Antibody 等） |
| `raw_selector_output` | 原始模型输出（建议 JSON 字符串保存） |
| `validation_errors` | JSON 校验或字段修正信息 |

---

## 7. 推荐产物（便于复核）

每次运行建议产出两份文件：

1. `selector_results_table.md`（给人看）
   - Markdown 表格，便于快速浏览和人工打标
2. `selector_results_debug.json`（给程序和追溯）
   - 保留完整字段、链接、原始输出、校验日志

---

## 8. 评估与反馈闭环

人工复核时重点检查：

1. 是否漏掉应选 sample（False Negative）
2. 是否误选 RNA-only sample（False Positive）
3. 链接是否对应被选中的 sample
4. `reasoning` 是否能解释选择依据

根据复核反馈，迭代：

- prompt 规则
- 输出校验器
- 别名词典（Surface/AbSeq/HTO/FB 等）

---

## 9. 分阶段实施（更新版）

### Phase 1：Context 预处理（已做）

- 解析 Family SOFT
- 生成轻量 metadata JSON

### Phase 2：Selector 推理与严格校验（进行中）

- 执行 `select_samples(query, metadata)`
- 校验输出 schema，清洗字段

### Phase 3：表格化调试输出（下一步）

- 将 22 个 GSE 批量结果汇总成 table + debug JSON
- 输出尽可能多的可审查证据

### Phase 4：人工反馈驱动迭代

- 根据你的人工检查结果调整规则与提示词

---

## 10. 示例表头（Markdown）

| series_id | is_false_positive | download_strategy | selected_gsm_count | selected_gsm_ids | selected_links | reasoning | total_samples | samples_with_files | validation_errors |
|---|---:|---|---:|---|---|---|---:|---:|---|
| GSEXXXXXX | false | GSM_Level_Separated | 3 | GSM1; GSM2; GSM3 | link1; link2; link3 | ... | 48 | 12 | |

> 说明：`download_strategy` 在本项目中仅作诊断标签，不触发下载动作。

---

## 11. 当前进展总结（2026-03-04）

### 11.1 已完成

- Phase 1：已完成 22 个 standalone GSE 的 metadata 预处理
- Phase 2：已实现 `select_samples(query, metadata)` + 严格 JSON 校验
- Phase 3：已完成 22 个 GSE 的批量 debug 运行并导出表格

### 11.2 本次批量运行结果（22 个 GSE）

数据来源：`selector_results_debug.json`

- `series_count`: 22
- `series_with_selected_samples`: 18
- `false_positive_count`: 4
- `total_selected_samples`: 178
- `llm_status`: ok
- `model`: `claude-haiku-4-5-20251001`

假阳性（当前结果）：

- `GSE280852`
- `GSE291290`
- `GSE316069`
- `GSE316782`

### 11.3 已生成的复核产物

1. `selector_results_table.md`
   - 人工快速浏览表（每个 GSE 一行）
2. `selector_results_debug.json`
   - 完整调试信息（raw 输出、校验信息、每个 series 的详细字段）
3. `debug_phase1_context.json`
   - Phase 1 预处理上下文（供 selector 输入）
4. `debug_phase1_summary.json`
   - Phase 1 汇总统计

### 11.4 当前观察（用于下一轮迭代）

- 22 个 GSE 中有 18 个被选出目标样本，4 个判为假阳性
- 仅 5 个 GSE 在“被选中 sample”上直接拿到了 sample 级 supplementary links
- 其余部分 series 的目标 sample 缺少直接文件链接，后续可补充 SRA relation 链接或 GSE-level 附件定位信息（仅展示，不下载）

---

## 12. 下一步（你给反馈后迭代）

优先按人工复核反馈修正：

1. 误检（False Positive）和漏检（False Negative）
2. `selected_links` 的完整性（补充 relation/SRA/GSE-level 线索）
3. reasoning 过长或不清晰的条目

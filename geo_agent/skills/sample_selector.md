# SampleSelectorSkill

## What it does

Classifies GSM samples by library type (GEX/ADT/TCR/BCR/HTO/ATAC/OTHER) using LLM. Given a CITE-seq Series with mixed library types, identifies which samples belong to which category.

## Context I/O

| Direction | Field | Type |
|---|---|---|
| Input | `filtered_datasets` | `list[GEODataset]` |
| Input | `target_library_types` | `list[str]` (default `["GEX"]`) |
| Output | `sample_metadata` | `dict[str, list[GEOSample]]` |
| Output | `selected_samples` | `dict[str, list[SampleSelection]]` |

## Code entry

```python
from geo_agent.skills.sample_selector import SampleSelectorSkill
import anthropic

skill = SampleSelectorSkill(
    ncbi_client=ncbi_client,
    llm_client=anthropic.Anthropic(api_key="..."),
    confidence_threshold=0.7,
)
context.target_library_types = ["GEX", "ADT"]
context = skill.execute(context)
```

## Pipeline position

FilterSkill → **SampleSelectorSkill** → (future) DownloadSkill

---

## Real-world classification guide (from 10 series, 566 samples)

### Golden examples — clear cases the LLM should get right

**GSE317605** (168 samples: 84 GEX + 84 ADT) — 最标准的命名

| GSM | Title | characteristics | molecule | → 应判为 |
|---|---|---|---|---|
| GSM9474997 | `Patient 10-02_GEX timepoint T01 scRNAseq` | `library type: mRNA` | `polyA RNA` | **GEX** (≥0.9) |
| GSM9475081 | `Patient 10-02_ADT timepoint T01 scRNAseq` | `library type: ADT` | `protein` | **ADT** (≥0.9) |

所有信号一致：title 含 `_GEX`/`_ADT`，characteristics 有 `library type`，molecule 区分明确。

**GSE306608** (6 samples: 2 GEX + 2 ADT + 2 HTO) — 三种类型都有标记

characteristics 字段完整（`library type: mRNA` / `library type: ADT` / `library type: HTO`），是最容易的 case。

**GSE320155** (60 samples: 20 GEX + 20 ADT + 20 TCR) — 命名略不同

Title 用 `, GEX` 而非 `_GEX`（如 `Liver, GEX`），但 characteristics 字段完整。应该靠 characteristics 判断，不要只看 title 格式。

---

### Failure patterns — LLM 容易犯的错

#### 错误 1: Title 含 "scRNAseq" ≠ GEX

GSE317605 的 ADT 样本 title 是 `Patient 10-02_ADT timepoint T01 scRNAseq`。title 里有 "scRNAseq" 但这是 ADT，不是 GEX。

```
❌ 看到 title 含 "scRNAseq" → 判为 GEX
✅ 看 molecule=protein + library_source=other → 判为 ADT
```

#### 错误 2: 非标准命名导致漏判

GSE268991 用 `5'GEX` 而非 `_GEX`，用 `Surface` 而非 `_ADT`。如果 LLM 只识别 `_GEX`/`_ADT` 模式，会把这些判为 OTHER。

```
❌ title 不含 "_ADT" → 判为 OTHER
✅ molecule=protein + description 含 "antibody" → 判为 ADT
```

#### 错误 3: 混合类型样本

GSE303197 有标为 `ADT/HTO mixed` 的样本 — 一个样本同时包含 ADT 和 HTO。当前分类框架只允许每个样本一个类型。

```
❌ 判为 ADT（丢失 HTO 信息）或 OTHER（丢失 ADT 信息）
✅ 判为 ADT（主要用途），confidence 降低，needs_review=True
```

#### 错误 4: 假阳性 series

GSE280852 的全部 6 个样本都是 `polyA RNA` + `transcriptomic`。这个 series 根本没有 CITE-seq sub-library，是 GEO 搜索的误命中。

```
❌ 把所有样本分类为 GEX，不做任何标记
✅ 所有样本都是 GEX、零 ADT → 应在结果中注明 "this series may not be genuine CITE-seq"
```

#### 错误 5: supplementary_file = NONE

GSE320155 的全部 60 个样本的 `supplementary_file` 都是 `NONE`。数据以 Series 级别的聚合文件形式存在。分类正确但下载链接为空。

```
❌ 忽略这种情况，导致下游 DownloadSkill 拿到空列表
✅ 分类照常，但在结果中标记 "no per-sample files, use Series-level download"
```

---

### Signal priority — 判断顺序

从 10 个 series 的真实数据中归纳的可靠性排序：

| 优先级 | 信号 | 可靠性 | 依据 |
|---|---|---|---|
| 1 | `characteristics` 中的 `library type` | 最高 | 结构化字段，GSE317605/GSE306608/GSE320155 都准确 |
| 2 | `molecule` | 高 | `polyA RNA`=GEX, `protein`=ADT, `genomic DNA`=TCR/ATAC — 基本不出错 |
| 3 | `library_source` | 中 | `transcriptomic`=GEX, `other`=ADT — 但有些 series 不填 |
| 4 | `title` 关键词 | 中低 | 变体太多（`_GEX`, `5'GEX`, `, GEX`, `_RNA`, `_mRNA`），且 ADT 样本也可能含 "scRNAseq" |
| 5 | `description` | 最低 | 有些 series 没有 description，有些用 description 存无关信息 |

---

### Naming variants actually observed (10 series)

| Type | Naming variants | Series |
|---|---|---|
| GEX | `_GEX`, `, GEX`, `_RNA`, `_mRNA`, `5'GEX`, `gene expression` | GSE317605, GSE320155, GSE313153, GSE283984, GSE268991, GSE269123 |
| ADT | `_ADT`, `, ADT`, `Surface`, `ADT/HTO mixed` | GSE317605, GSE320155, GSE268991, GSE303197 |
| TCR | `_VDJ`, `library type: TCR`, `gdTCR`, `abTCR` | GSE317605, GSE320155, GSE269123 |
| HTO | `_HTO`, `ADT/HTO mixed` | GSE306608, GSE303197 |

**Rule-based parsing cannot cover this.** 10 个 series 就有 5+ 种 GEX 命名方式。

---

## Error handling

| Scenario | Handling |
|---|---|
| Family SOFT fetch fails | Skip series, log to `context.errors` |
| Family SOFT is empty | Skip series, log to `context.errors` |
| LLM returns invalid JSON | Retry 1x; still fails → skip series |
| Unknown `library_type` | Map to `OTHER`, set `needs_review=True` |
| Confidence < threshold | Set `needs_review=True`, keep in results |

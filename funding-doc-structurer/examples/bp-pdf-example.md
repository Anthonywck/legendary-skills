# 正例：商业计划书 PDF 全流程

样本：`datas/商业计划书/【半导体】森国科碳化硅SiC D轮项目商业计划书.pdf`（37 页，有完整文本层）

## 1. 抽取

```bash
python scripts/extract.py "datas/商业计划书/【半导体】森国科碳化硅SiC D轮项目商业计划书.pdf"
```

```json
{
  "status": "ok",
  "pages": 37,
  "notes": { "pages_with_text": 37, "text_coverage": 1.0, "cjk_ratio": 0.72 },
  "first_page_text": "碳化硅（SiC）领先企业\n森国科D轮商业计划书\n深圳\n2022年5月\n1"
}
```

`status=ok` 的三个依据：有文本层、覆盖率高、无乱码。

## 2. 字段推导

| 字段 | 值 | 依据 |
| --- | --- | --- |
| `doc_type` | `BP` | `source_root=商业计划书` |
| `topic` | `半导体` | `【半导体】` 命中 `bracket_map` |
| `subject` | `森国科碳化硅SiC` | 去 `【】`、去「…项目商业计划书」后缀，按空白切第一段 |
| `round` | `D轮` | 文件名 `D轮` 优先于正文 |
| `date` | `2022-05` | 封面第 4 行 `2022年5月` 是独立落款行 |
| `date_source` | `doc_text` | 来自正文而非文件名 |
| `version` | `v1.0` | 无版本信号，取默认 |
| `subject` 归属 | `森国科sic` | `subject_core` 归一 |

**日期为什么不是 `2022-05-01`**：原件只有月级信息。补日属于臆造，
产物只保留真实精度。

**日期为什么不是文件里的 `2023`**：正文提到「2027 年 SiC 市场规模」等未来年份，
但这些都在叙述句中，不满足「以日期为主体的独立行」判据，不会入选。

## 3. 产物

路径：`datas-md/by_topic/半导体/2022/BP/2022-05_BP_森国科碳化硅SiC_v1.0.md`

```yaml
---
title: 【半导体】森国科碳化硅SiC D轮项目商业计划书
doc_type: BP
project: null
date: 2022-05
date_source: doc_text
version: v1.0
status: null
round: D轮
subject: 森国科碳化硅SiC
topic: 半导体
tags: [半导体, 森国科碳化硅SiC, SiC]
summary: 【半导体】森国科碳化硅SiC D轮项目商业计划书 森国科碳化硅SiC的商业计划书，
  归属「半导体」赛道。 原文关键数据：轮次 D轮；投后估值 10.2亿元；融资金额 1亿；营收 1亿。
key_facts:
  - "轮次: D轮"
  - "投后估值: 10.2亿元"
  - "融资金额: 1亿"
  - "所在地区: 深圳市"
  - "营收: 1亿"
  - "页数: 37"
alias_full: null
alias_short: 森国科碳化硅SiC
alias_en: null
alias_pinyin: null
source_available: true
source_path: datas/商业计划书/【半导体】森国科碳化硅SiC D轮项目商业计划书.pdf
extraction_status: ok
---
```

正文节选：

```markdown
## 原文证据

| 字段 | 原文片段 |
| --- | --- |
| 投后估值 | …拟增发260万股 l 每股39元 l 融资金额1亿 l 投后估值10.2亿元… |
| 所在地区 | …公司总部设立在深圳市南山区粤海街道科技生态园10栋A座12层… |
| date | 深圳 / 2022年5月 |
```

## 4. 与同主体文档互链

数据里还有 `【半导体】森国科SiC -碳化硅项目商业计划书.pdf`，
两者 `entity_key` 都是 `森国科sic`，但正文相似度 0.995（只差一页水印），
被标记为疑似重复：

```yaml
entity_key: 森国科sic
duplicate_of: datas/商业计划书/【半导体】森国科SiC -碳化硅项目商业计划书.pdf
duplicate_note: 正文相似度 0.996 ≥ 0.92
related_docs:
  - by_topic/半导体/2022/BP/2022-05_BP_森国科SiC_v1.0.md
```

**注意 `【半导体】森国科SiC …` 那份的文件名没写 D 轮，但正文第 1 页是
「森国科D轮商业计划书」**——文件名不可靠，`round` 字段以内文为准时才可信。
本 Skill 的策略是**文件名优先、内文兜底**，且在证据表中保留原句，
让这个矛盾可被人看见。

## 5. 检索验证

```bash
grep "投后估值" datas-md/by_topic/半导体/2022/BP/*.md
grep "森国科"   datas-md/by_topic/半导体/2022/BP/*.md     # 主体、tags、文件名三处均命中
grep "公司简称" datas-md/by_topic/半导体/2022/BP/*.md     # 元数据速查区
```

## 6. 反查原件

```bash
grep "2022-05_BP_森国科碳化硅SiC" datas-md/_index/files_index.csv
# → datas/商业计划书/【半导体】森国科碳化硅SiC D轮项目商业计划书.pdf
```

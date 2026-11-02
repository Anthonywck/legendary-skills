# 正例：PPTX 全流程

样本：`datas/商业计划书/【半导体设备】鹏城半导体 -高端半导体外延设备的国产化项目商业计划书.pptx`（26 页）

数据里 6 份 PPTX 全部是商业计划书，结构与 PDF 版 BP 一致，但抽取细节不同。

## 1. 为什么 PPTX 需要单独规则

| 差异 | PDF | PPTX |
| --- | --- | --- |
| 文本单元 | 页 | 幻灯片（含文本框、表格、备注） |
| 标题 | 靠字号/位置推断 | 每页首个文本框天然是标题 |
| 元数据 | `doc.creationDate` | `core_properties.created` |
| 内嵌图片文字 | 无文本层时判 needs_ocr | python-pptx 同样取不到，需 OCR |

规则之所以按「格式注册表」设计而不是按 PDF/PPTX 写死，
正是为了让 `.docx`（以及未来可能的 `.pptx` 变体）走同一条链路：
`assets/formats.yaml` 里加一行即可，`extract.py` 不动。

## 2. 抽取

```bash
python scripts/extract.py "datas/商业计划书/【半导体设备】鹏城半导体 -高端半导体外延设备的国产化项目商业计划书.pptx"
```

```json
{
  "status": "ok",
  "pages": 26,
  "chars": 3743,
  "meta": {
    "title": "PowerPoint 演示文稿",
    "author": "MLOONG",
    "created": "2019-04-01 05:54:00",
    "modified": "2024-02-27 05:53:23"
  }
}
```

每页生成 `## 第 N 页：{首行}` 作为小节标题，正文是其文本框、表格行与备注：

```markdown
## 第 1 页：高端半导体外延设备的国产化

高端半导体外延设备的国产化

## 第 2 页：市场现状

市场现状
Part-01
market situation
```

## 3. 字段推导

| 字段 | 值 | 依据 |
| --- | --- | --- |
| `doc_type` | `BP` | `source_root=商业计划书` |
| `topic` | `半导体` | `【半导体设备】` → `bracket_map` 映射到一级赛道 `半导体`，原词进 tags |
| `subject` | `鹏城半导体` | 去【】、去后缀，按空格切第一段 |
| `alias_full` | `鹏城半导体技术（深圳）有限公司` | 正文含主体名的工商全称 |
| `date` | `2019-04-01` | 文件名无日期；封面无落款；取 `core_properties.created` |
| `date_source` | `doc_meta` | |
| `author` | `MLOONG` | `core_properties.author` |

**日期为什么用 `created` 而不是 `modified`**：`modified` 是 `2024-02-27`，
明显是后来被批量改过（本批数据多个文件的 modDate 都是同一天）。
`created` 更接近文档真实时间。规则上固定只取 `created`。

**日期为什么不是 `2026-07-28`**：`fs_mtime` 是拷贝到服务器的时间，
本轮数据里所有文件都是这一天，若采用会让年份全部错误。

## 4. 产物

路径：`datas-md/by_topic/半导体/2019/BP/2019-04-01_BP_鹏城半导体_v1.0.md`

```yaml
---
title: 【半导体设备】鹏城半导体 -高端半导体外延设备的国产化项目商业计划书
doc_type: BP
date: 2019-04-01
date_source: doc_meta
version: v1.0
round: null
author: MLOONG
subject: 鹏城半导体
topic: 半导体
tags: [半导体设备, 鹏城半导体, 鹏城半导体技术（深圳）有限公司]
key_facts:
  - "页数: 26"
alias_full: 鹏城半导体技术（深圳）有限公司
source_available: true
source_path: datas/商业计划书/【半导体设备】鹏城半导体 -高端半导体外延设备的国产化项目商业计划书.pptx
extraction_status: ok
---
```

注意 `alias_full` 含括号公司名，且**被写进了 tags**——
这样用户 grep `鹏城半导体技术（深圳）有限公司` 也能命中，
而 grep `鹏城半导体` 同样命中（文件名 + subject + tags 三处都含）。

## 5. 只含图片的 PPTX

若某页内容全为图片，python-pptx 抽不到文字，该页为空。
判据与 PDF 一致：看**有文本层的页占比**，而不是总字数——
只看总字数会被封面/封底的一行文字骗过。

抽出全文为空或过短时：`status: empty` 或 `needs_ocr`，
产物只保留元数据，`summary` 写固定警示语。

## 6. 文件句柄

PPTX 解析器把文件读进内存（`BytesIO`）再交给 python-pptx。
直接传路径会让底层 zip 句柄挂住源文件，在 Windows 上导致
用户无法改名/移动/删除原件——这违反「原件只读、可被外部自由操作」的约定，
也会让 `selftest.py` 的改名场景间歇性失败。

## 7. 检索验证

```bash
grep "鹏城半导体" datas-md/by_topic/半导体/2019/BP/*.md
grep "高端半导体外延设备的国产化" datas-md/by_topic/半导体/2019/BP/*.md   # 内部标题
grep "MLOONG" datas-md/by_topic/半导体/2019/BP/*.md                      # author 字段
```

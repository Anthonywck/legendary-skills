---
name: funding-doc-structurer
description: 把文档批量拆解为「可按 glob/grep 精确检索」的结构化 Markdown 知识库，覆盖 PDF、PPTX、DOCX、旧版 DOC/PPT、图片（OCR）与 Markdown。当用户需要组织 datas 目录、批量生成文档元数据、维护文件名与日期规范、处理同主体多版本或疑似重复文件、对扫描件做 OCR、或在源文件改名/删除后同步索引时使用。只产出 .md 与索引，不做问答，不生成 Term Sheet 等下游文档。
metadata:
  version: "2.0.0"
  tags: [doc-structuring, frontmatter, indexing, dedupe, incremental-sync, ocr, legacy-office]
---

# Funding Doc Structurer

把原件变成**结构可预测、元数据可 grep**的 `.md`。文件组织质量 = 检索质量：
产物结构与落位必须能被规则唯一推导，不得依赖临场判断。

## 何时用

| 信号 | 说明 |
| --- | --- |
| 用户提到「整理投融资文件 / 商业计划书 / 行业报告」 | 走主流程 |
| 用户要「批量生成元数据 / 打标签 / 补 frontmatter」 | 走主流程 |
| 用户问「文件改名/删除后索引怎么同步」 | 只读 `references/sync-and-index.md` |
| 用户问「某份文档落哪个目录、为什么」 | 只读 `references/taxonomy.md` |
| 用户报「某份文件抽不出来 / 乱码 / 扫描件」 | 只读 `references/troubleshooting.md` |
| 用户要「扫描件/图片里的文字也要能检索」 | 走 OCR 两阶段流程，见下方 |

**不做**：检索问答、Term Sheet / 尽调清单生成、向量库、修改 `datas` 内任何原件。

## 支持格式

| 格式 | 解析方式 |
| --- | --- |
| `.pdf` | PyMuPDF 文本层；无文本层的页按需 OCR |
| `.pptx` / `.docx` | python-pptx / python-docx（含表格、备注） |
| `.doc` / `.ppt` | 纯 Python（olefile），不依赖 LibreOffice；失败时给 `soffice` 命令 |
| `.png` `.jpg` `.jpeg` `.bmp` `.tif` `.tiff` `.webp` | OCR |
| `.md` `.markdown` | 原样保留，提取标题层级 |
| `.txt` `.log` | 按 utf-8-sig → utf-8 → gb18030 解码，全文作正文 |
| `.csv` `.tsv` | 自动识别分隔符与编码，转 Markdown 表格 |
| `.xlsx` | 逐工作表转 Markdown 表格（取公式计算结果） |
| `.zip` `.rar` `.7z` | 显式忽略（登记为 intentional，不是遗漏） |

新增格式改 `assets/formats.yaml` 即可，不动代码。

## 触发信号 → 加载文件

只在命中对应信号时读取，不要预先加载。

| 触发信号 | 加载 |
| --- | --- |
| 需要判定赛道、doc_type、或推导产物路径 | `references/taxonomy.md` |
| 需要定文件名、取日期、处理日期缺失 | `references/naming.md` |
| 需要确认 frontmatter 字段与取值约束 | `references/metadata-schema.md` |
| 要处理某一份具体文件（含失败重试） | `references/extraction-sop.md` |
| `--rebuild` / `--sync` / `--prune`、改名、源失联 | `references/sync-and-index.md` |
| 抽取状态异常（needs_ocr / corrupt / encoding_error / too_large / unsupported） | `references/troubleshooting.md` |
| 需要看完整跑通的例子 | `examples/` 下对应文件 |
| 需要知道哪些做法会出错 | `examples/anti-patterns.md` |

## 主流程

```
1. 探环境  → scripts/check_env.py
2. 试跑    → scripts/sync.py --rebuild --limit 5 --dry-run
3. 落地    → scripts/sync.py --rebuild          （阶段一：不内联 OCR）
4. 补 OCR  → scripts/run_ocr.py                 （阶段二：只处理 needs_ocr）
5. 校验    → scripts/validate_output.py --strict
6. 日常    → scripts/sync.py --sync
```

改了产物模板 / 清洗规则后（例如这次的三列证据表），用 `--force-render` 重渲染：
它只跳过「源未变更」的短路，不重跑昂贵的解析与 OCR；**不会**把 OCR 成果打回原状。

**两阶段是默认路径**：OCR 单页约 4 秒，扫描件动辄 20–30 页。
阶段一先让 90%+ 的文件可检索，扫描件只标 `needs_ocr`；
阶段二单独补，可分批（`--limit`）、可断点续跑。小批量想一次到位可用
`FDS_OCR=1` 让 `sync.py` 内联 OCR。

### 1. 探环境

```bash
python .claude/skills/funding-doc-structurer/scripts/check_env.py
```

- **必需**：`pymupdf`、`python-pptx`
- **强烈建议**：`rapidocr`（OCR）、`olefile`（.doc/.ppt）、`openpyxl`（.xlsx）——缺失会丢能力但流程仍能跑完
- **可选**：`pyyaml`（读配置表）、`python-docx`、`pypinyin`、`pymupdf4llm`

> **解释器**：本 Skill 的依赖装在项目内的 `.venv-doc/`，不是系统 Python。
> 直接 `python sync.py` 会因缺 `pymupdf` 把所有文件判成 `unsupported` 并覆盖产物。
> 一律用 `.venv-doc/Scripts/python.exe`（Windows）或 `.venv-doc/bin/python`（POSIX）执行。

缺失时**先打印清单再装**，装在项目内 venv，不动系统 Python：

```bash
python .../check_env.py --install      # 交互确认
```

### 2. 试跑

```bash
python .../sync.py --rebuild --limit 5 --dry-run     # 只报告，不写盘
python .../sync.py --rebuild --limit 5               # 写 5 份
```

### 3. 全量落地

```bash
python .../sync.py --rebuild
```

### 4. 校验

```bash
python .../validate_output.py --strict
```

### 5. 日常增量

```bash
python .../sync.py --sync          # 只处理新增/变更/改名/失联
```

端到端回归（含改名、删除、重建、清理四类场景）：

```bash
python .../selftest.py
```

## IO 契约

**输入（只读）**

`datas/` 下有**任意一级子目录**都会被扫描（源目录不写死）；
排除某些目录用 `_index/overrides.yaml` 的 `exclude_roots`。

当前数据：`商业计划书/`（84）、`行业报告/`（84）、`AICC加密模型服务方案/`（4）。
压缩包（`.zip` / `.rar` / `.7z`）显式忽略。

**输出**

```
datas-md/
├── by_topic/{赛道}/{年份}/{DOC_TYPE}/{日期}_{DOC_TYPE}_{主体}_{版本}[_{状态}].md
└── _index/
    ├── files_index.csv        # 派生缓存，可 --rebuild 重建
    ├── by_subject.csv         # 人工查阅视图
    ├── by_date.csv
    ├── last_run_report.txt    # 最近一次运行的结构化报告（.txt，不参与检索）
    ├── errors.log             # 单点失败记录，不中断
    └── overrides.yaml         # 可选：主体别名、排除目录
```

**绝不写** `datas/` 下的任何文件。

## 硬规则速查

以下为不可协商项，细则见 references：

1. **赛道封闭集**：`topic` 只能取 `assets/taxonomy.yaml` 的一级赛道；方括号原词降为 tag。
2. **主体三处可 grep**：文件名、`subject` 字段、`tags` 都要含企业主体。
3. **防臆造**：抽不到的字段写 `null` / `unknown`；`date_source` 必须如实标注来源。
   **不得为了「填满」而补全、推断、套用模板、行业均值或相邻文档的值**——空字段是合法结果。
4. **只提示不修改**：结构化只在 `datas-md/` 内产出产物。发现原件有逻辑 / 常识 / 专业错误时，
   先交叉验证确认真实存在，再向用户报告疑点与修改建议；**原件、字段值、文件名、目录名一律不动**，
   改不改由用户自己决定。细则见 `references/extraction-sop.md` ⑨。
5. **日期闸门**：只有「以日期为主体」的封面行或落款行才算文档日期，
   正文叙述里出现的年份（如「XX 公司成立于 2002 年」）不得采纳。
6. **同主体互链、疑似重复只标不删**。
7. **源删除后产物保留**并标 `source_available: false`，另带醒目提示。
8. **幂等**：同一文件重复处理，产物逐字节一致。
9. **单点失败不中断**：记 `errors.log` 后继续。
10. **每次运行给结构化报告**：成功数、落位分布、失败清单、原因与建议，终端打印并存 `_index/last_run_report.txt`。

## 产物形态

```markdown
---
title: ...
doc_type: BP
date: 2022-05-15
date_source: doc_text
subject: 森国科
topic: 半导体
tags: [第三代半导体, 森国科, 深圳市森国科科技股份有限公司]
summary: ...
key_facts:
  - "轮次: D轮"
  - "投后估值: 10.2亿元"
source_available: true
source_path: datas/商业计划书/【半导体】森国科SiC -碳化硅项目商业计划书.pdf
---

# 标题

<!-- dedupe:begin -->   ← entity_key / duplicate_of / related_docs
<!-- dedupe:end -->

## 元数据速查        ← 公司全称/简称/英文名/拼音首字母 等口语化检索入口
## 摘要
## 关键事实
## 原文证据          ← 字段 / 值 / 原文片段 三列，供人工回溯
## 正文
```

## 检索配合（不是本 Skill 的职责，仅供下游对齐）

```bash
glob("datas-md/by_topic/**/*.md")               # 索引文件不是 .md，天然不入选
grep("投后估值", "datas-md/by_topic/**/*.md", "-A 3 -B 3")
read("datas-md/by_topic/半导体/2022/BP/2022-05-15_BP_森国科_v1.0.md")
```

优先级与《搭建方案》3.4 一致：`summary`/`key_facts` → 正文 → 按 `date` 降序回溯。

## 自检清单

- [ ] `validate_output.py --strict` 退出码 0
- [ ] `selftest.py` 全通过（覆盖改名 / 源删除 / 重建 / prune）
- [ ] 索引里每条 `md_path` 对应的文件都存在；目录里每个 `.md` 都在索引里
- [ ] `grep "公司简称"` 与 `grep "估值"` 均有命中
- [ ] 两次 `--rebuild` 产物哈希一致
- [ ] `datas/` 下没有任何文件被修改（比对 mtime）

## 偏离与假设

完整登记见 `README.md` 的「偏离说明」「假设清单」两节。
概要：不设 `projects/` 维度（数据无项目概念）、新增 `date_source` 与 `subject` 两个字段、
日期精度允许 `YYYY-MM` / `YYYY`（原件不总是有日级信息）。

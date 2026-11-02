# funding-doc-structurer

把投融资历史文件批量拆解为「可按 glob/grep 精确检索」的结构化 Markdown 知识库。

只做一件事：**把文件变成结构可预测、元数据可 grep 的 `.md`**。
不做检索问答，不做 Term Sheet 生成，不引入向量库。

---

## 目录

- [它是什么 / 不是什么](#它是什么--不是什么)
  - [源文档疑点：只提示不修改](#源文档疑点只提示不修改)
- [5 分钟上手](#5-分钟上手)
- [支持的文件格式](#支持的文件格式)
- [两阶段流程：先落地，再补 OCR](#两阶段流程先落地再补-ocr)
- [日常增量](#日常增量)
- [看懂运行报告](#看懂运行报告)
- [产物长什么样](#产物长什么样)
- [目录与文件名规则](#目录与文件名规则)
- [配置项](#配置项)
- [维护手册](#维护手册)
- [常见问题](#常见问题)
- [文件清单](#文件清单)
- [偏离说明](#偏离说明)
- [假设清单](#假设清单)

---

## 它是什么 / 不是什么

**是**：一个把 `datas/` 下的原始文档，转成 `datas-md/by_topic/…` 结构化 Markdown 的流水线。
每份产物带固定字段的 frontmatter，能被 `grep` 直接命中公司名、融资轮次、估值、赛道。

**不是**：

| 不做 | 为什么 |
| --- | --- |
| 检索问答 | 下游 Skill 的职责 |
| Term Sheet / 尽调清单生成 | 同上 |
| 向量库 | 方案明确用文件系统原生能力 |
| 修改/移动/删除 `datas` 里的原件 | 原件只读是硬约束 |
| 替原件「纠错」 | 发现疑点只提示不修改，见 [源文档疑点](#源文档疑点只提示不修改) |
| OCR 之外的图像理解 | 只做文字识别，不做图表解读 |

### 源文档疑点：只提示不修改

结构化时如果发现原件存在**逻辑 / 常识 / 专业错误**（前后矛盾、单位错配、口径写反等），
本 Skill 的做法是：

1. 先交叉验证，确认错误真实存在（均为原文/算术/公开事实，不凭一次推理下结论）
2. 照原文如实抽取，产物里的字段、文件名、目录**一个都不改**
3. 以「疑点 + 原文 + 依据 + 建议」的格式报告给用户
4. **只给建议，不执行任何修改**——改不改由用户自己决定

完整规则见 `references/extraction-sop.md` ⑨。与「防臆造」是一条原则的两面：
**产出的东西必须是原文里有的，发现的毛病必须让人知道。**

---

## 5 分钟上手

所有命令在**项目根目录**执行。

```bash
S=.claude/skills/funding-doc-structurer/scripts
PY=.venv-doc/Scripts/python.exe      # 或任意已装依赖的解释器
```

### 第 1 步 · 探环境

```bash
$PY $S/check_env.py
```

输出会分三档告诉你缺什么：

| 档位 | 含义 | 缺了会怎样 |
| --- | --- | --- |
| `required` | 缺了跑不起来 | 直接退出 |
| `recommended` | 缺了关键能力降级 | OCR / 旧版 Office 不可用 |
| `optional` | 缺了只影响单项 | 拼音别名、.docx 等 |

缺依赖时**先打印清单再装**，装在项目内 venv，不动系统 Python：

```bash
$PY $S/check_env.py --install
```

### 第 2 步 · 先预演，不写盘

```bash
$PY $S/sync.py --rebuild --limit 5 --dry-run
```

看报告里的「成功 / 降级 / 失联」三个数字和落位分布。确认规则符合预期再往下。

### 第 3 步 · 小批实跑

```bash
$PY $S/sync.py --rebuild --limit 5
$PY $S/validate_output.py --strict
```

### 第 4 步 · 全量

```bash
$PY $S/sync.py --rebuild
```

阶段一很快（172 份约 2–4 分钟，取决于 PDF 页数）。扫描件会被标记 `needs_ocr`，
不阻塞其余内容。

### 第 5 步 · 补 OCR（可选）

```bash
$PY $S/run_ocr.py --dry-run     # 先看有多少份、预估多久
$PY $S/run_ocr.py --limit 3     # 分批跑
$PY $S/run_ocr.py               # 全部补完
```

### 第 6 步 · 复查

```bash
$PY $S/validate_output.py --strict
```

退出码 0 即通过。

---

## 支持的文件格式

| 格式 | 解析方式 | 说明 |
| --- | --- | --- |
| `.pdf` | PyMuPDF | 逐页取文本层；无文本层的页按需 OCR |
| `.pptx` | python-pptx | 逐页文本框 + 表格 + 备注 |
| `.docx` | python-docx | 段落（识别标题层级）+ 表格 |
| `.doc` | 纯 Python（olefile） | 解析 FIB + piece table，不依赖 LibreOffice |
| `.ppt` | 纯 Python（olefile） | 扫描 TextCharsAtom / TextBytesAtom |
| `.png` `.jpg` `.jpeg` `.bmp` `.tif` `.tiff` `.webp` | OCR | 直接识别图片文字 |
| `.md` `.markdown` | 原样读取 | 保留标题层级，不重新渲染 |
| `.txt` `.log` | 纯文本 | 按 `utf-8-sig → utf-8 → gb18030` 依次尝试解码 |
| `.csv` `.tsv` | 标准库 csv | 自动识别 `,` `;` tab `|` 分隔符，转 Markdown 表格 |
| `.xlsx` | openpyxl | 逐工作表转 Markdown 表格；`data_only` 取计算结果而非公式 |
| `.zip` `.rar` `.7z` | 显式忽略 | 不展开、不处理；**登记为「有意忽略」而非遗漏** |
| 其它 | 未登记 | 索引里留一行 `degraded:unsupported`，**不静默跳过** |

新增格式只需改 `assets/formats.yaml`，不用改代码。

### 表格文件（`.csv` / `.tsv` / `.xlsx`）

三种表格走同一条结构化路径：转成 Markdown 表格写入产物的正文区，
同时保留「按行拼接的纯文本」作为 `text`，因此 `grep "森国科"` 与
`grep "| 森国科 |"` 都能命中。

`doc_type` 归为 `SHEET`，落位 `by_topic/{赛道}/{年份}/SHEET/`。

几个实现细节：

- **编码**：按 `utf-8-sig → utf-8 → gb18030` 依次尝试，不用启发式探测（探测结果不稳定，会破坏幂等）
- **分隔符**：`csv.Sniffer` 自动识别 `,` `;` tab `|`；识别失败按逗号并给出告警
- **竖线转义**：单元格内的 `|` 转成 `\|`，否则会把表格结构冲散
- **截断**：单表上限 2000 行 × 40 列，超出会在产物「抽取提示」里写明
- **公式**：`.xlsx` 用 `data_only=True`，取计算结果而不是公式文本

### 旧版 `.doc` / `.ppt` 说明

这两类是二进制 OLE 格式，没有稳定的纯 Python 解析器。本 Skill 的做法：

1. 先用 `olefile` 尽力解析，能读出正文就用
2. 解不出（加密 / 复合结构异常）时**明确标 `unsupported`**，并给出补救命令：

```bash
soffice --headless --convert-to docx  旧文件.doc
soffice --headless --convert-to pptx  旧文件.ppt
```

转换后放回 `datas`，重跑 `--sync` 即可。**原件不要删**——转换是有损的。

> 为什么不用 LibreOffice 直接集成：目标环境是内网 + 无管理员权限，装不了。
> 为什么不依赖 `antiword`：它可能只是 Git for Windows 顺带装的，业务机器上不一定有。

---

## 两阶段流程：先落地，再补 OCR

OCR 单页约 4 秒，一份 25 页扫描件要 2 分多钟。若在全量抽取时同步做，
少数扫描件会把整批拖成几小时。所以拆成两阶段：

```
阶段一  sync.py --rebuild
        快速抽取。扫描件识别出来但只标 needs_ocr，不阻塞其余文件。
        此时 90%+ 的文件已经可检索。

阶段二  run_ocr.py
        单独挑出 needs_ocr 的文件补 OCR。
        可分批（--limit）、可断点续跑、可限定目录（--only）。
```

想一次到位也可以：

```bash
FDS_OCR=1 $PY $S/sync.py --rebuild --limit 20
```

`FDS_OCR=1` 让单次 sync 内联 OCR，适合小批量。大批量仍建议两阶段。

### OCR 相关参数

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `FDS_OCR` | `0` | `1` → sync 内联 OCR |
| `FDS_OCR_DPI` | `150` | 渲染分辨率；扫描件小字/表格可调 `200` |
| `FDS_OCR_MAX_PAGES` | `60` | 单份最多 OCR 页数，防止超大扫描件拖垮批次 |

### 什么时候需要调 DPI

- 正文清晰、只有识别个别数字出错 → 保持 150
- 表格 / 小字号 / 手写体 → 调到 200（耗时约翻倍）
- 整页大面积图形、只有少量文字 → 保持 150，OCR 收益本就有限

---

## 日常增量

源目录加了文件、改了文件、删了文件，都只需要一条命令：

```bash
$PY $S/sync.py --sync
```

它按情况分别处理：

| 情况 | 判定 | 行为 |
| --- | --- | --- |
| 新文件 | 索引里没有该路径 | 抽取、落位、新增索引行 |
| 内容变了 | 路径相同但 `size`/`sha1` 变了 | 重新抽取覆盖 |
| 只是改名 | 路径不同但 `sha1` 相同 | **原地更新索引行**，产物按新规则移动 |
| 源被删了 | 索引有、目录没有 | 产物**保留**，标 `source_available: false` |
| 没变 | 路径/大小/哈希都相同 | 跳过（不重写文件） |

### 源文件被删除后会发生什么

产物**不会**自动删除。这是有意的：它承载的是历史知识，源被误删或归档到别处，
不应该让曾经可检索的结论凭空消失。

产物会多出：

```yaml
source_available: false
```

```markdown
⚠️ 源文件已不存在，本产物为历史留存，最后同步于 2026-10-30
```

确实要清理时，必须显式：

```bash
$PY $S/sync.py --prune --dry-run   # 先列清单
$PY $S/sync.py --prune             # 交互确认
```

---

## 看懂运行报告

每次运行结束会自动打印结构化报告，并写入 `datas-md/_index/last_run_report.txt`。

```
====================================================================
【已写盘】 处理报告  2026-10-30 17:20:11
====================================================================
本次新处理 168 份（新增 168，内容变更/改名 0），跳过未变更 0，失败 0

成功 155 份  |  降级/失败 13 份  |  源已失联 0 份

── 成功产物的目录分布 ──
    84 份  by_topic/半导体/2023/BP/
    41 份  by_topic/半导体/2024/REPORT/
    …

  按文档类型: BP 89，REPORT 66，DOC 2，NOTE 1
  按赛道:     半导体 160，新材料 3，…

── 失败 / 降级明细 ──
  [degraded:needs_ocr] 12 份 —— 正文需 OCR：文档为扫描/图片型
      ・datas/商业计划书/【新材料】中熵科技…pdf
      建议：运行 run_ocr.py 补齐
  [degraded:corrupt] 1 份 —— 文件损坏或 0 字节
      ・datas/行业报告/沙利文：…（15页）.pdf
      建议：从源端重新获取该文件
====================================================================
```

### 怎么读

| 区块 | 你要关注什么 |
| --- | --- |
| 三个数字 | `成功` 是否接近文件总数；`降级` 是否只集中在已知问题文件 |
| 目录分布 | 有没有大批量落到 `其他/` —— 说明赛道词表需要补 |
| 失败明细 | 每类都给了**原因**和**建议**，按建议处理即可 |
| 源已失联 | 非 0 说明源目录有变动，确认是否符合预期 |

### 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 完成；可能有降级项（可接受） |
| 1 | 有文件处理时抛异常，需查 `_index/errors.log` |

便于接入 CI：只要没有异常失败就算通过，降级项另行统计。

---

## 产物长什么样

路径示例：

```
datas-md/by_topic/半导体/2022/BP/2022-05_BP_森国科碳化硅SiC_v1.0.md
```

文件内容：

```markdown
---
title: 【半导体】森国科碳化硅SiC D轮项目商业计划书
doc_type: BP
project: null
date: 2022-05
date_source: doc_text
version: v1.0
round: D轮
subject: 森国科碳化硅SiC
topic: 半导体
tags: [半导体, 森国科碳化硅SiC, SiC]
summary: …原文关键数据：轮次 D轮；投后估值 10.2亿元；融资金额 1亿。
key_facts:
  - "轮次: D轮"
  - "投后估值: 10.2亿元"
  - "融资金额: 1亿"
alias_full: null
alias_short: 森国科碳化硅SiC
alias_pinyin: null
source_available: true
source_path: datas/商业计划书/【半导体】森国科碳化硅SiC D轮项目商业计划书.pdf
extraction_status: ok
---

# 标题

<!-- dedupe:begin -->
entity_key / duplicate_of / related_docs
<!-- dedupe:end -->

## 元数据速查      ← 公司全称 / 简称 / 英文名 / 拼音首字母 逐行列出
## 摘要
## 关键事实
## 原文证据        ← 字段 / 值 / 原文片段 三列，供人工回溯
## 正文
```

### 检索怎么用

```bash
# 1. 先按目录收窄（赛道 + 年份 + 类型）
glob("datas-md/by_topic/半导体/2022/**/*.md")

# 2. 在元数据区精确命中（summary / key_facts）
grep("投后估值", "datas-md/by_topic/**/*.md", "-A 3 -B 3")

# 3. 读命中文件
read("datas-md/by_topic/半导体/2022/BP/2022-05_BP_森国科碳化硅SiC_v1.0.md")
```

主体在**文件名、`subject` 字段、`tags`** 三处都有，
所以 `grep "森国科"`、`grep "森国科碳化硅SiC"` 都能命中。

索引文件是 `.csv` 不是 `.md`，不会进入 `glob("**/*.md")` 的结果。

---

## 目录与文件名规则

```
by_topic/{赛道}/{年份}/{doc_type}/{日期}_{DOC_TYPE}_{主体}_{版本}[_{状态}].md
```

| 段 | 取值 |
| --- | --- |
| 赛道 | 封闭集：半导体 / 新材料 / 新能源 / 企业服务 / 节能环保 / 其他 |
| 年份 | 4 位年 或 `unknown` |
| doc_type | BP / REPORT / WHITEPAPER / DOC / NOTE / OTHER |
| 日期 | `YYYY-MM-DD` / `YYYY-MM` / `YYYY` / `unknown`（按原件真实精度，不补齐） |
| 主体 | 企业简称（报告为发布机构） |
| 版本 | `vX.Y`，无信号时 `v1.0` |

新增赛道要改 `assets/taxonomy.yaml` 的 `topics`——这是**刻意的人工关口**，
不允许脚本自动扩展封闭集。

### 源目录

`datas/` 下**每个一级子目录都会被扫描**。当前识别到：

- `商业计划书/` → 84 份（78 PDF + 6 PPTX）
- `行业报告/` → 84 份（PDF）
- `AICC加密模型服务方案/` → 4 份（2 DOCX + 1 MD + 1 PNG）
- 合计 **172 份**，其中 1 份 zip 被显式忽略

新增目录无需改代码，下次 `--sync` 自动纳入。要排除某些目录：

```yaml
# datas-md/_index/overrides.yaml
exclude_roots: [临时目录, 备份]
```

---

## 配置项

### 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FDS_OCR` | `0` | `1` → sync 内联 OCR |
| `FDS_OCR_DPI` | `150` | OCR 渲染分辨率 |
| `FDS_OCR_MAX_PAGES` | `60` | 单份 OCR 页数上限 |
| `FDS_LLM_MARKDOWN` | `0` | `1` → 用 pymupdf4llm 生成更丰富 Markdown（较慢） |
| `FDS_ROOT` | 未设 | 沙箱演练用；**生产不要设** |

> **执行前必读**：依赖装在项目内 `.venv-doc/`。用系统 `python` 跑会缺 `pymupdf`，
> 把所有文件判成 `unsupported` 并**覆盖掉已有产物**。正确命令：
> `.venv-doc/Scripts/python.exe .claude/skills/funding-doc-structurer/scripts/sync.py --rebuild`

### overrides.yaml

放在 `datas-md/_index/overrides.yaml`：

```yaml
# 主体别名纠正（规则无法处理的特殊情况）
subject_alias:
  森国科: 森国科SiC

# 不扫描的目录
exclude_roots: [临时目录, 备份]
```

改完重跑 `--sync` 生效，不会删数据。

---

## 维护手册

| 需求 | 命令 |
| --- | --- |
| 索引损坏 / 路径迁移后重来 | `sync.py --rebuild` |
| 只想看会做什么 | 任意命令加 `--dry-run` |
| 只处理某个来源目录 | `sync.py --sync --only 商业计划书` |
| 只处理前 N 份 | `sync.py --rebuild --limit 20` |
| 按文件名挑几份 | `sync.py --rebuild --pick 森国科 --pick 烯钻` |
| 补 OCR | `run_ocr.py --limit 5` |
| 清理源已失联的产物 | `sync.py --prune --dry-run` → `sync.py --prune` |
| 校验全部产物 | `validate_output.py --strict` |
| 端到端回归 | `selftest.py` |

### 全量重建会删文件吗

会，但**只在一种情况**：产物目录里存在、但索引不再引用的 `.md`（路径规则变化后遗留）。
安全阀：必须同时满足「在 `by_topic/` 下」「首行是 `---`」「前 3000 字含 `source_path: datas/`」。

源已删除但产物还在的孤儿文件**不会**被重建删除——它们会被重新登记为 `missing`。

### `--rebuild` 会重跑 OCR 吗

**不会**。`--rebuild` 重建的是索引，不是「把每份正文重新解析一遍」：

| 产物状态 | 源未变更时的行为 |
| --- | --- |
| `ok` | 直接沿用，不重抽（**保住阶段二 OCR 的成果**） |
| `degraded:*` / `error` | 重试一次（也许依赖装好了、或 OCR 现在可用了） |
| `missing` / `orphaned` | 源回来了就改回 `ok`，不重抽 |

已 OCR 的文件不会因为一次重建退回 `needs_ocr`。

### 想彻底重来

```bash
rm -rf datas-md          # 产物与索引都是派生的，随时可重建
$PY $S/sync.py --rebuild
```

前提是 `datas/` 完整。产物可以随时丢弃，原件才是事实来源。

---

## 常见问题

### Q：扫描件一直是 `needs_ocr` 怎么办

三选一：

1. 直接补 OCR：`run_ocr.py`
2. 从源端找可搜索版 PDF 替换后 `--sync`
3. 用 Acrobat「优化扫描的 PDF」重建文本层

### Q：`.txt` 抽出来是乱码

文件多半不是 UTF-8 或 GB18030（例如 Big5、Shift-JIS）。产物会带告警
「按 gb18030 解码；若出现乱码，源文件可能是其它编码」。
转成 UTF-8 后重跑 `--sync` 即可。

### Q：`.csv` 只识别出一列

分隔符可能不是常见的四种。产物会告警「只识别出单列，分隔符可能判断有误」。
把 `_parse_csv` 的 `delimiters` 参数加上实际分隔符，或在源端另存为标准 CSV。

### Q：改了 `taxonomy.yaml` 之后要不要手动清空产物

不用。`sync.py` 会对比 `taxonomy.yaml` 的内容哈希，检测到变更就自动重新抽取全部文件：

```
检测到判定规则变更（taxonomy.yaml），本轮将重新抽取全部文件
```

哈希存在 `_index/.rules_fingerprint`。这个机制保证「改配置」与「生效」之间没有隐藏步骤。

### Q：某份 PDF 抽出来全是乱码

字体缺 ToUnicode 映射，标 `encoding_error`。这不是本 Skill 能修的——
需要可搜索版，或对该文件做 OCR 重建文本层。

**为什么拦死不降级**：乱码里同样能匹配到「估值」「亿元」，
放行会让抽取器产出通篇臆造事实。

### Q：为什么很多日期只有年月，没有具体日

原件里就只写了「2022年5月」。补齐成 `2022-05-01` 属于编造日期。
`date_source` 字段记录了这个日期是从哪来的（正文落款 / 文件名 / 文档元数据 / 文件系统时间）。

### Q：主体识别错了

编辑 `overrides.yaml` 的 `subject_alias`，然后 `--sync`。

### Q：`其他` 赛道下堆了很多文件

说明赛道词表没覆盖到。补 `assets/taxonomy.yaml` 的 `bracket_map` 或 `keyword_rules`，
再 `--rebuild`。别让脚本自动扩展——那会让封闭集失去意义。

### Q：两份文件看起来一样，会合并吗

不会。会把 `duplicate_of` 标出来、把两份互链，但**两份都保留**。
重复判定用正文哈希 + 相似度（阈值 0.92），结果交人工确认。

### Q：Windows 上改名/删除报 PermissionError

三类原因：解析器持有句柄（已规避）、杀毒/索引器瞬时占用（重试即可）、文件只读属性（`attrib -R`）。

---

## 文件清单

| 文件 | 行数 | 职责 | 加载时机 |
| --- | --- | --- | --- |
| `SKILL.md` | 220 | 主入口：何时用、主流程、支持格式、硬规则 | 始终 |
| `references/taxonomy.md` | 144 | 赛道封闭集、判定决策树、doc_type、主体、路径推导 | 要判定赛道/类型/落位 |
| `references/naming.md` | 124 | 文件名规范、日期五级优先级、归一化陷阱 | 要定文件名/取日期 |
| `references/metadata-schema.md` | 110 | 字段总表、取值矩阵、别名四件套 | 要确认字段取值 |
| `references/extraction-sop.md` | 217 | 单文件 9 步 SOP、质量判据、疑点报告、幂等要求 | 处理具体文件 |
| `references/sync-and-index.md` | 189 | 索引字段、四种同步行为、源目录发现、两阶段 | 同步/改名/失联 |
| `references/troubleshooting.md` | 197 | 九类异常的现象、根因、处理 | 抽取状态异常 |
| `examples/bp-pdf-example.md` | 121 | BP-PDF 全流程正例 | 需要 BP 例子 |
| `examples/report-pdf-example.md` | 125 | 行业报告全流程正例 | 需要报告例子 |
| `examples/pptx-example.md` | 124 | PPTX 全流程正例 | 需要 PPTX 例子 |
| `examples/sync-example.md` | 156 | 新增/改名/删除/重建/幂等 | 要看同步行为 |
| `examples/anti-patterns.md` | 506 | 28 条真实踩过的坑 + 3 条用户约束 | 要知道什么会出错 |
| `scripts/clean.py` | 71 | 产物空白清洗（代码块保护、语义零改动） | 被 emit / validate 调用 |
| `assets/taxonomy.yaml` | 150 | 赛道封闭集 + 方括号映射 + doc_type 规则 | 脚本运行时 |
| `assets/formats.yaml` | 115 | 格式 → 解析器映射 + 依赖 + 环境变量 | 脚本运行时 |
| `scripts/common.py` | 162 | 路径、配置、哈希、错误日志（重导出命名域/索引域） | 被所有脚本 import |
| `scripts/naming.py` | 389 | 日期、主体、赛道、doc_type、路径推导 | 脚本运行时 |
| `scripts/index_io.py` | 58 | 索引 CSV 与视图读写 | 脚本运行时 |
| `scripts/frontmatter.py` | 55 | frontmatter 序列化（固定字段序保证幂等） | 脚本运行时 |
| `scripts/parsers.py` | 298 | 文档类解析器（PDF/PPTX/DOCX/DOC/PPT/图片）与解析器总表 | 被 extract import |
| `scripts/parsers_data.py` | 213 | 纯文本与表格解析器（TXT/MD/CSV/TSV/XLSX） | 被 parsers import |
| `scripts/extract.py` | 229 | 抽取入口 + 质量判定 + 乱码检测 | 被 sync import；可单独诊断 |
| `scripts/ocr_backend.py` | 111 | RapidOCR 封装（懒加载、单例、日志隔离、失败降级） | 被 parsers 调用 |
| `scripts/legacy_office.py` | 214 | `.doc` / `.ppt` 纯 Python 解析（olefile） | 被 parsers 调用 |
| `scripts/facts.py` | 169 | 事实抽取、摘要、key_facts、同句证据片段 | 被 build_frontmatter import |
| `scripts/date_resolve.py` | 130 | 日期五级优先级与防臆造闸门 | 被 build_frontmatter import |
| `scripts/build_frontmatter.py` | 251 | 记录组装 + 字段校验 | 被 sync import |
| `scripts/dedupe_entities.py` | 182 | 主体归一 + 重复识别 + 互链 | sync 后置阶段 |
| `scripts/emit.py` | 189 | 产物渲染、路径分配、单文件处理 | 被 sync import |
| `scripts/maintenance.py` | 166 | 去重互链、孤儿回收、陈旧清理、按需取正文 | sync 后置阶段 |
| `scripts/report.py` | 231 | 结构化运行报告（终端 + `last_run_report.txt`） | sync 结束 |
| `scripts/run_ocr.py` | 159 | 阶段二：批量补 OCR | 手动运行 |
| `scripts/sync.py` | 377 | `--rebuild` / `--sync` / `--prune` 主流程 + 规则变更检测 | 主入口 |
| `scripts/check_env.py` | 222 | 环境探测（必需/建议/可选三档） | 首次运行 |
| `scripts/validate_output.py` | 267 | 目录/命名/字段/可 grep/索引一致性校验 | 每次全量后 |
| `scripts/selftest.py` | 213 | 端到端回归（45 个断言） | 改动脚本后 |

所有脚本单文件 ≤400 行。`common` 负责无争议的基础设施，`naming` 负责所有落位判定，
`emit` 负责写文件，`maintenance` 负责写完之后的整树整理。

---

## 偏离说明

以下每一条都是对《搭建方案》第三章的**有意偏离**，均已登记。

### D1 · 不设 `projects/` 维度（对应 3.1）

- **原规范**：`projects/{project}/{year}/{quarter}/{type}/`
- **实际**：`by_topic/{赛道}/{year}/{doc_type}/`
- **理由**：真实数据里不存在「项目」这一实体。BP 按企业组织，报告按赛道组织，
  二者没有共同的 project 键。强行造维度只会让所有文件落到 `project-unknown/`。

### D2 · 新增 `date_source` 字段（对应 3.3）

日期可能来自五个不同来源，可信度差异极大。`2026-07-28`（文件系统拷贝时间）
与 `2022-05-15`（正文落款）外观相同但含义天差地别。不留痕就无法审计。

### D3 · 新增 `subject` 字段（对应 3.3）

`project` 已无意义，而主体是唯一稳定的业务标识。`project` 保留但恒为 `null`。

### D4 · 日期精度放宽（对应 3.2）

84 份 BP 里只有 2 份文件名带完整日期，多数只有月级落款。补齐属于编造日期。

### D5 · 文件名增加主体段（对应 3.2）

无 project 维度后，主体是唯一稳定标识；同时满足「主体三处可 grep」。

### D6 · 源目录不写死

原假设是 `商业计划书/` + `行业报告/` 两个固定目录。改为扫描 `datas/` 下
所有一级子目录，`source_root` 字段变成「文件所在的一级目录名」。
这样同一份 Skill 可用于任意目录结构，不需要改代码。

### D7 · 不处理压缩包

`行业报告.zip` 已解压，内容即两个来源目录。在 `formats.yaml` 中显式登记为
`ignored`，是「有意忽略」而非遗漏。

### D8 · 未拆 `by_type/` 交叉维度（对应 3.1 第 3 点）

Windows 软链接需管理员权限，且会让 glob 出现重复命中。
`doc_type` 已是路径段，`glob("by_topic/**/REPORT/*.md")` 即可实现交叉检索。

### D9 · 未实现季度分层（对应 3.1）

数据的时间精度多数只到月甚至年，季度目录会大量混杂。年份一级已满足回溯需求。

### D10 · 默认不使用 `pymupdf4llm`

2.0 起默认触发 RapidOCR，单文件从 5 秒劣化到分钟级，且无法稳定关闭。
默认走 PyMuPDF 纯文本按页拼装；需要时用 `FDS_LLM_MARKDOWN=1` 显式开启。

### D11 · OCR 采用两阶段而非内联

见「两阶段流程」一节。这是为了不让少数扫描件拖垮整批任务。

### D12 · `.doc` / `.ppt` 用纯 Python 解析而非 LibreOffice

目标环境内网 + 无管理员权限，装不了 LibreOffice。纯 Python 解析是「尽力而为」，
失败时明确标 `unsupported` 并给出 `soffice` 命令。

---

## 假设清单

### A1 · 数据规模

任务书曾写「88 份 BP + 74 份报告」。实测 **84（78 PDF + 6 PPTX）+ 84**，
另加用户后续新增的 AICC 目录 4 份，合计 172。
脚本不依赖任何硬编码数量，报告以实测为准。

### A2 · 文件系统时间不可信

所有文件的 mtime 都是拷贝那天。因此 `fs_mtime` 只作最后兜底。

### A3 · 存在损坏文件

`沙利文：…（15页）.pdf` 为 0 字节 → `corrupt`。假定源端可找回。

### A4 · 存在扫描件

`中熵科技 Pre-A+` 26 页中 25 页无文本层 → 阶段一标 `needs_ocr`，
阶段二 OCR 后覆盖率 100%。假定 OCR 识别误差在可接受范围。

### A5 · 存在字体缺映射的 PDF

`中博芯半导体科技` 抽出为乱码 → `encoding_error`。假定需要可搜索版。

### A6 · 疑似重复一律不删不并

| 组 | 判定 | 依据 |
| --- | --- | --- |
| 深圳烯钻科技 ×2 | 重复（1.0） | 归一化正文哈希相同 |
| 森国科 ×2 | 疑似重复（0.995） | 仅一页水印不同 |

两组都保留、标 `duplicate_of`，交人工确认。

### A7 · 森国科文件名与内文不一致

文件名无「D轮」，内文第 1 页写「森国科D轮商业计划书」。
策略是文件名优先、内文兜底，并在「原文证据」保留原句，让矛盾可见。

### A8 · 中文公司名核心 ≥3 字

前缀归并阈值 3 是数据驱动的：森国科(3)、烯钻科技(4)、中熵科技(4)。
2 字核心（中微、华大）歧义过大，不归并。

### A9 · 赛道封闭集覆盖当前数据

6 个一级赛道覆盖全部文件的落位。新增领域需人工扩展词表。

### A10 · 旧版 Office 文件可能仍存在

当前数据里没有 `.doc` / `.ppt`，但规则已支持。
若解析失败会明确报错并给出转换命令，不会静默跳过。

---

## 已知限制

1. **OCR 有误差**：手写体、复杂表格、艺术字识别率明显低于印刷正文。
2. **不做跨语言别名**：英文名只从主体本身提取，不做中英对照。
3. **不做实体消歧**：`中熵科技` 与 `中熵新能源` 若是不同法人，需 `overrides.yaml` 人工区分。
4. **`alias_full` 偏低召回**：只采纳包含主体名的工商全称，宁缺毋滥。
5. **`.ppt` 复杂版式会丢**：只取文本原子，形状/图层关系不保留。
6. **全量耗时**：168 份 PDF 阶段一约 1–3 分钟；扫描件走阶段二，每页约 4 秒。

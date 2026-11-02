# funding-doc-query

在已结构化的投融资 Markdown 知识库上做**事实可溯源**的检索问答与知识文档生成。

## 解决什么问题

投融资业务人员查历史项目时，要的不是「答得快」，而是**答得可核对**：
每条结论都能反查到哪份文档、哪个章节、哪段原文、哪个原始文件。

本 Skill 强制这个链条：

```
结论 → [S#] → 产物路径 → 区段 → 逐字原文片段 → 原始文件 source_path
```

## 上下游

本 Skill 是链路的下游，上游为同级的 **`funding-doc-structurer`**：

```
datas/ ──structurer──▶ datas-md/by_topic/ ──query（本 Skill）──▶ datas-generator/
（原件只读）             （本 Skill 的唯一输入）      （本 Skill 的唯一写入区）
```

上游的 SKILL.md 与 README 定义了产物形态与字段契约；本 Skill **只依赖契约，不依赖实现**——
上游换生成模板不影响检索逻辑，本 Skill 调检索策略也不影响上游落位。

## 安装

```
.claude/skills/funding-doc-query/
├── SKILL.md
├── references/
├── assets/
├── examples/
└── README.md
```

放置到项目的 `.claude/skills/` 下即可被识别。前置依赖：上游 `funding-doc-structurer`
已把原件转成 `datas-md/by_topic/{赛道}/{年份}/{DOC_TYPE}/*.md`。

**不需要安装任何脚本或依赖**——本 Skill 只用 Agent 内置的 glob / grep / read。

## 触发示例

| 用户说 | 走哪条路 |
| --- | --- |
| 「森国科的投后估值是多少？」 | 精准问答 → 点查 |
| 「帮我整理森国科的融资历史」 | 先分流；按生成执行时说明理由 |
| 「半导体赛道有哪些公司做过 SiC？」 | 聚合；先声明口径与去重规则 |
| 「这个判断知识库里有依据吗？」 | 缺失确认；穷尽检索后正向拒答 |
| 「知识库里有哪些文档提到了 X？」 | 聚合；必须附覆盖报告 |

## 与 structurer 的边界

| 本 Skill 做 | structurer 做 |
| --- | --- |
| 消费 `.md` 做检索、问答、文档生成 | 组织目录、命名、生成元数据 |
| 维护引用 ID、来源报告、覆盖报告 | 维护 `_index/` 索引 |
| 判定是否需要联网补足 | 决定赛道与 doc_type |
| 自带金标准题库与验证协议 | 处理 OCR、编码、损坏 |

**只依赖上游稳定契约**，不依赖 structurer 内部脚本。换生成模板不影响本 Skill 的检索逻辑。
上游对下游的承诺见 `../funding-doc-structurer/README.md` 的「下游：funding-doc-query」一节。

### 依赖的契约（实测于 2026-11-02，172 份产物）

| 契约 | 值 |
| --- | --- |
| 路径模板 | `by_topic/{赛道}/{年份}/{doc_type}/{日期}_{DOC_TYPE}_{主体}_{版本}[_{状态}].md` |
| 固定字段 | `subject` / `topic` / `date` / `date_source` / `round` / `key_facts` / `summary` / `extraction_status` / `source_available` / `source_path` / `duplicate_of` |
| 别名字段 | `alias_full` / `alias_short` / `alias_en` / `alias_pinyin` / `tags` / 文件名 / 正文 `entity_key` |
| 正文区段 | `元数据速查` / `摘要` / `关键事实` / `原文证据`（字段→值→原文片段三列）/ `抽取提示` / `正文`（按页分节） |
| 赛道闭集 | 半导体 / 新材料 / 新能源 / 企业服务 / 节能环保 / 其他 |

### 已知的契约缺口（本 Skill 按「有则用、无则降级」处理）

| 现象 | 实测 | 本 Skill 的处理 |
| --- | --- | --- |
| `alias_pinyin` 全库为 `null` | 0/172 非空 | 跳过该解析步，不报错 |
| `## 关键事实` 并非每份都有 | 168/172 | 缺时读 frontmatter 的 `key_facts` |
| `project` 恒为 `null` | 172/172 | 不参与任何检索 |
| 部分 `ok` 产物正文实为乱码 | 3 份（CJK 占比 22% / 15% / 7%） | 按 `needs_ocr` 同等待遇降级；上游已登记为已知限制第 7 条 |
| `duplicate_of` 只标不删 | 2 份 | 聚合时按 `entity_key` 去重 |

## 目录说明（逐文件：职责 / 行数 / 触发信号）

行数为 2026-11-02 实测。「触发信号」对应 `SKILL.md` 的「触发信号 → 加载文件」表。

| 文件 | 行数 | 职责 | 触发信号 / 加载时机 |
| --- | --- | --- | --- |
| `SKILL.md` | 145 | 触发条件、13 条硬约束、主流程、IO 契约、自检清单 | **常驻**（不进 references 也够用） |
| `references/query-intent.md` | 77 | 意图分流表、模糊时 ≤3 问话术、五类检索类型 | 判断是问答/生成/模糊，或需要追问时 |
| `references/retrieval-playbook.md` | 204 | glob 组合、三级检索、主体别名解析、时间权重、回溯、覆盖报告 | 实际执行检索时 |
| `references/output-and-citation.md` | 117 | 两类输出模板、引用 ID 规则、来源报告字段 | 组织输出时 |
| `references/edge-cases.md` | 227 | 冲突并列、未收录、状态降级矩阵、联网闸门、防注入 | 遇到冲突/缺失/降级/联网/疑似注入时 |
| `references/validation-playbook.md` | 119 | V1–V5：出题矩阵、隔离协议、评分维度、迭代出口 | 用户要看验证、复跑验证、或改题库时 |
| `assets/field-map.yaml` | 137 | 问题 → 字段/区段 → 推荐检索词；含实测计数与 P3 风险提示 | 查询解析（Step 1）时 |
| `assets/status-policy.yaml` | 142 | 状态 → 可用性 → 标注要求；含隐藏降级检测口径 | 命中文档含降级状态时 |
| `assets/golden-queries.yaml` | 393 | 12 题金标准题库（`queries` 可读 + `sealed_notes` 封存） | 跑验证时 |
| `examples/qa-point-query.md` | 87 | 正例：单主体单指标，含 P3 核验与去重 | 需要看问答格式时 |
| `examples/qa-aggregation.md` | 98 | 正例：「新材料赛道有哪些文档」，全覆盖无未纳入 | 需要看聚合格式时 |
| `examples/doc-generation.md` | 143 | 正例：生成融资历史 + 完整来源报告 + 落盘 | 需要看生成格式时 |
| `examples/conflict-case.md` | 108 | 正例：光刻胶国产化率三源冲突 + 面板干扰源隔离 | 需要看冲突处理时 |
| `examples/missing-case.md` | 93 | 正例：晶湛半导体未收录 + 降级漏检排查 | 需要看拒答格式时 |
| `examples/validation-run.md` | 655 | **本轮实测**的验证报告（基线 / 逐题 / 评分 / 遗留） | 复跑对照时 |
| `examples/validation-sealed-answers.md` | 194 | 封存答案 + 阶段 4 比对记录 | **仅阶段 4**，阶段 3 禁止打开 |
| `examples/anti-patterns.md` | 172 | 10 条反例，每条对应本库真实产物 | 交付前自查时 |

**加载原则**：未命中信号不加载。`SKILL.md` 单独可用；只做简单点查时理论上不需要打开任何 references。

## 如何复跑验证

```bash
# 阶段 1 · 出题：读库取证，填 golden-queries.yaml 的 queries 与 sealed_notes
# 阶段 2 · 封存：sealed_notes 已独立成 examples/validation-sealed-answers.md
# 阶段 3 · 演练：只读 golden-queries.yaml 的 question 字段，从零执行 Step 0–6
# 阶段 4 · 比对：打开 validation-sealed-answers.md 逐项核对
```

**阶段 3 的反作弊要求**：

- 不打开 `validation-sealed-answers.md`
- 不用记忆中的路径直接 `read`，每个 `read` 都必须能追溯到前一步 `grep`/`glob` 命中
- 发现题目有歧义 → 退回阶段 1 修题并记录，不得就地放宽标准

本轮实测结论：**10 项维度全部通过，1 次修题（G1b）**。
详见 `examples/validation-run.md`。

## 关键设计取舍

| 取舍 | 理由 |
| --- | --- |
| **P3 核验是强制的** | `key_facts` 是规则抽取，实测有单位截断、主语错位、行业值冒充主体值三类错误。P1 命中不等于答案成立 |
| **冲突不消解，连「取最新」也不做** | 去重与排序会掩盖口径差异。用户要的是能自己判断的数据，不是替他们做的决定 |
| **拒答要有信息量** | 「未收录」必须附检索路径、关键词、命中数、降级排查，否则用户无法区分「真没有」与「没搜」 |
| **生成物不回流** | `datas-generator/` 里的文档不参与检索。否则生成物被再次引用，形成自我污染 |
| **验证拆两文件** | 题目与答案物理分文件，把隔离从「自律」变成「结构」 |
| **不写脚本** | 只用内置 glob/grep/read，避免下游部署时要装 Python 环境 |

---

## 偏离说明

| 编号 | Prompt 要求 | 实际做法 | 理由 |
| --- | --- | --- | --- |
| D1 | 知识库基线：doc_type `BP 12 · REPORT 5 · WHITEPAPER 3` | 采用实测 `BP 84 · REPORT 73 · WHITEPAPER 11 · DOC 2 · NOTE 1 · OTHER 1` | Prompt 步骤 1 要求「以**实际产物**为准」；基线值已严重过期 |
| D2 | `duplicate_of` 非空 4 份 | 实测 2 份（2 个文件，各在 frontmatter 与 dedupe 块出现一次） | 原数把「字符串出现次数」当成了「文件数」 |
| D3 | 赛道「6 个，无空档」 | 保留 6 个，但显式标注**极度倾斜**（半导体 159/172） | 不标注倾斜会让聚合题被误读为全市场结论 |
| D4 | `alias_pinyin` 未提及 | 实测全库 0 条非空，标 `not_observable` | 无样本，不虚构 |
| D5 | 金标准 8–10 题 | **12 题**（G1、G3 各拆两题） | G1 拆成两个独立公司用 P1+P3；G3 拆成「小赛道全量」与「跨年类型计数」，各验证不同能力 |
| D6 | `golden-queries.yaml` 含「题目 + 封存答案两段」 | 保留两段，**另**在 `examples/validation-sealed-answers.md` 复写一份 | YAML 内两段同文件，工具层无法阻止「顺手翻到下面」；拆文件把隔离从自律提升到结构 |
| D7 | 验证报告模板六节 | 六节齐全，另加「本轮验证的已知局限」小节 | 出题与执行同源是方法论固有局限，须显式登记 |
| D8 | examples 中的「业务类」5 个 | 全部落地，另加 `validation-sealed-answers.md` | 该文件属验证协议产物，非业务类 |
| D9 | 未要求写 `README.md` 的偏离/假设章节 | 写在本 README 末尾 | Prompt 步骤 11 要求交付时输出「偏离说明」「假设清单」「无法实测清单」，放 README 便于随包携带 |
| D10 | G8 取材 `needs_ocr` 真实文件 | 改用 `encoding_error` 的中博芯 | 2026-11-02 14:00 上游补 OCR，原 2 份 `needs_ocr` 全部转为 `ok`，无样本可用；换样本保留「降级不作答」的验证意图 |

## 假设清单

| 编号 | 假设 | 影响范围 | 若不成立会怎样 |
| --- | --- | --- | --- |
| A1 | `datas-md/` 是唯一知识源，`datas-md.bak-20261102/` 不参与检索 | 全部 glob | 若备份目录也在工作区且被 glob 到，会重复计数 |
| A2 | `source_path` 相对**项目根**，可直接用于打开原件 | 来源清单 | 若工作目录变了，路径需重算基准 |
| A3 | `## 原文证据` 的「原文片段」是逐字摘录（不是改写） | P3 核验的有效性 | 若上游改写了片段，P3 逐字比对会失效 |
| A4 | 赛道闭集只有 6 个 | glob 组合 | 新增赛道时需更新 `field-map.yaml` |
| A5 | `entity_key` 相同 = 同一实体 | 去重 | **已知反例**：`赛迪译丛` 3 份是同一发布机构的不同报告；`云潼科技` 两份注册地不同。已在 `retrieval-playbook.md` 写明「同名不代表同一家」 |
| A6 | 中文关键词为主，英文并查 | 聚合召回 | `SiC` 50 / `碳化硅` 53，只搜一个会漏 20+ 份 |
| A7 | 用户能接受「不给出单一数字」 | G10 类问题 | 若必须给数字，须先与用户确认口径 |
| A8 | 生成物落 `datas-generator/`，与 `datas-md/` 同级 | 写盘边界 | 若部署环境改了相对位置，写入区需重配 |
| A9 | 知识库快照是**静态**的 | 金标准题库、状态计数、examples 中的样本 | **已被证伪**：2026-11-02 14:00/14:26 上游两次重跑，2 份 `needs_ocr` 转 `ok`、全部产物重新渲染。引用任何状态或样本前必须实查，不得依赖 README/examples 中的快照数字 |

## 无法实测清单

以下路径**无真实样本**，本轮标 `not_observable`，**未虚构任何样本文件或验证结果**：

| 路径 | 无样本原因 | 本 Skill 的处理 | 补测建议 |
| --- | --- | --- | --- |
| `source_available: false` 降级 | 全库 172 份全为 `true` | 只在 `edge-cases.md` 与 `status-policy.yaml` 定义标注文案 | 用 `datas-md.bak-20261102` 构造临时样本（**不写正式库**） |
| `alias_pinyin` 解析 | 全库 0 条非空（`pypinyin` 未参与本批生成） | 跳过该解析步，不报错不臆造 | 上游装 `pypinyin` 重生成后再补 G7 拼音分支 |
| `too_large` / `unsupported` | 全库 0 份 | 定义在状态矩阵中，未演练 | 构造超 512MB / 未登记格式的测试文件 |
| 联网闸门 | 演练中未触发（需用户授权） | 三条件闸门 + 输出隔离格式已定义 | 由第二人在真实场景中触发并记录 |
| 防注入 | 库内无真实注入样本 | 规则已写入 `SKILL.md` 硬约束 9 与 `edge-cases.md` 五 | 在**临时目录**构造含「忽略以上要求」的测试文档 |
| 冷启动会话 | 12 题在同一上下文内完成 | — | 换新会话重跑阶段 3 |
| 「出题人与执行人分离」 | 本轮为同一执行者 | 靠「不打开 `sealed_notes`」自证 | 下一轮由第二人执行阶段 3 |

# 异常排查

每种异常都有明确的 `extraction_status`，都会写进索引 `md_status`（`degraded:*`），
都会被 `validate_output.py` 统计。**没有「静默跳过」这条路。**

## 快速定位

```bash
# 看所有降级产物
grep "degraded:" datas-md/_index/files_index.csv

# 看最近失败
tail -20 datas-md/_index/errors.log

# 单文件诊断
python scripts/extract.py "datas/商业计划书/xxx.pdf"
```

---

## needs_ocr —— 扫描件 / 图片型 PDF

**现象**：`text_coverage < 0.30`，正文为空或只有末页水印。

**真实案例**：`【新材料】中熵科技项目-半导体制热材料…Pre-A+轮…pdf`
共 26 页，前 25 页 0 字符，第 26 页有一段 383 字的微信群推广文案。
若按「总字数 > 0」判断会误判为正常，实际 96% 内容不可检索。

**为什么按页覆盖率判**：扫描件几乎都带一页水印/封底文字，
总字数判据必然被骗过。

**处理**：本 Skill 内置 OCR（RapidOCR），但走**两阶段**，避免少数扫描件拖垮整批：

```bash
# 阶段一：正常 sync，扫描件只标 needs_ocr（其余文件立刻可检索）
python scripts/sync.py --sync

# 阶段二：只对 needs_ocr 的文件补 OCR
python scripts/run_ocr.py --dry-run     # 看清单与预估耗时
python scripts/run_ocr.py --limit 3     # 分批跑，可断点续跑
python scripts/run_ocr.py               # 全部补完
```

小批量想一次到位：

```bash
FDS_OCR=1 python scripts/sync.py --sync --only 商业计划书
```

**OCR 参数**：`FDS_OCR_DPI`（默认 150；小字/表格调到 200）、
`FDS_OCR_MAX_PAGES`（单份上限，默认 60）。

**为什么阶段一不做 OCR**：单页约 4 秒，25 页扫描件要 2 分多钟。
168 份里若有十几份扫描件，内联 OCR 会把一次全量拖成半小时以上。

---

## encoding_error —— 正文字体缺 ToUnicode 映射

**现象**：能抽出文本，但全是西里尔/亚美尼亚/格鲁吉亚等码位。

**真实案例**：`【GaN基半导体】中博芯半导体科技…pdf`，抽取结果为
`ԗцЗԧ৾ / ԠجѼय۪ / ޥୡҷ՚`——原文是中文，PDF 字体没有 ToUnicode 表，
PyMuPDF 只能按字形索引映射到错误码位。

**判据**：异域脚本字符占比 ≥ 15%（`pymupdf_garble_ratio`）。
不用「中文占比低」判断，否则英文原版报告会被误杀。

**为什么必须拦死**：乱码文本里依然能匹配到「估值」「亿元」等关键词，
放行会让抽取器产出通篇臆造事实。

**处理**：

- 产物只保留元数据，`summary` 写固定警示语，正文区留空
- 恢复途径：
  1. 找回可搜索版 PDF（原始导出，而非扫描/截图打印）
  2. 或对 PDF 做 OCR 重建文本层
  3. 或用 Acrobat「另存为其他 → 优化扫描的 PDF」重建字体映射

---

## unsupported —— 旧版 .doc / .ppt 解析失败

本 Skill 用纯 Python（olefile）解析这两类二进制格式，能读就用。失败常见于：

- 文档加密（FIB flags 带加密位）
- 复合文档结构异常（某些工具导出的非标准 OLE）
- 旧版 PPT 的文本存在非标准容器里

**处理**：

```bash
soffice --headless --convert-to docx  旧文件.doc
soffice --headless --convert-to pptx  旧文件.ppt
```

转换后放回 `datas`，重跑 `--sync`。**原件不要删**——转换是有损的。

若机器上没有 LibreOffice（内网无管理员），可让上游提供 `.docx` / `.pptx` 版本。

## corrupt —— 0 字节或无法打开

**真实案例**：`沙利文：2023中国半导体石英坩埚行业市场独立研究报告（15页）.pdf` 为 0 字节。

**处理**：索引留行、产物只登记元数据、`md_status=degraded:corrupt`。
从源端重新获取文件即可，本 Skill 不需要改动。

不要因为一份坏文件就中断整批——`errors.log` 记一行，继续下一份。

---

## encrypted —— 需要密码

`doc.needs_pass` 为真。不解密、不猜测密码。
产物只有元数据；拿到密码后用其他工具解密再放入 `datas`，重跑 `--sync` 即可。

---

## too_large —— 超过 512 MB

批量场景下超大文件会拖垮整体耗时。当前上限 512 MB，超出直接登记不解析。
确实需要时改 `extract.py` 的 `MAX_BYTES`，并单独跑该文件。

---

## unsupported —— 格式未登记

`.ppt` / `.doc` 是最常见的两种（二进制 OLE 格式，无稳定的纯 Python 解析器）。

**处理**：

```bash
soffice --headless --convert-to pptx "xxx.ppt"
soffice --headless --convert-to docx "xxx.doc"
```

转换后放回 `datas`，重跑 `--sync`。原文件**不要删除**——转换是有损的，
保留原件才能回溯。

`.zip` 属于显式忽略：既不展开也不引用。

---

## 抽取能跑但字段全空

按这个顺序查：

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `subject: unknown` | 文件名没有可用前缀 | 检查 `overrides.yaml` 加别名 |
| `date: unknown` | 封面/落款都没有独立日期行 | 正常，按规则不应臆造 |
| `key_facts` 只有「页数」 | 正文确实没有融资数据 | 正常 |
| `alias_full: null` | 正文没出现包含主体名的工商全称 | 正常，不猜 |
| `topic: 其他` | 方括号未登记且关键词未命中 | 补 `assets/taxonomy.yaml` 的 `bracket_map` |

**「字段空」不等于「脚本坏了」**——大多数情况是原件里确实没有这个信息。
翻产物的「原文证据」表可以确认抽取器看到了什么。

---

## 产物路径漂移 / 出现带哈希后缀的文件

**现象**：`2023-07-31_BP_深圳烯钻科技_v1.0-38b3db91.md`

哈希后缀说明**两个不同的源文件推导出了同一个路径**，属于正常的消歧行为，
不是 bug。查到撞车的两份文件后，若它们其实是同一主体，应通过
`overrides.yaml` 的 `subject_alias` 统一主体，再 `--rebuild`。

---

## --rebuild 删了不该删的文件

只有一种可能：这些 `.md` 在产物目录里存在，但索引不再引用。
`--rebuild` 的陈旧清理有安全阀（必须是 `by_topic` 下、带 `---` 开头、含
`source_path: datas/`）。若仍误删：

1. 立即 `--rebuild` 重建（源文件还在就能恢复）
2. 若源文件已删，从备份恢复——**这正是为什么源删除时产物默认不删**

---

## Windows 上改名/删除报 PermissionError

三类原因：

1. **解析器持有文件句柄** —— 本 Skill 所有解析器都读进内存再解析（`BytesIO`），已规避
2. **杀毒软件/搜索索引器瞬时占用** —— 重试即可，`selftest.py` 内部已加重试
3. **文件本身是只读属性** —— `attrib -R <file>`

---

## 批次跑到一半中断

- 已写入的产物与索引是一致的，不会留下半截文件（先写产物再写索引）
- 直接重跑 `--sync` 即可，已完成的会被跳过
- 想强制全部重来：`--rebuild`
- 想看会做什么而不写盘：任何命令加 `--dry-run`

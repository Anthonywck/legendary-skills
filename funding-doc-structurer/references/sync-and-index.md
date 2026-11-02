# 索引与增量同步

索引是**可重建的派生缓存**，不是事实来源。事实来源永远是
`datas/` 下的原件 + `datas-md/by_topic/` 下的产物。删掉索引再 `--rebuild`，
必须得到与原来一致的结论。

## 索引字段

文件：`datas-md/_index/files_index.csv`

| 字段 | 说明 |
| --- | --- |
| `source_root` | 源文件所在的一级目录名（`商业计划书` / `行业报告` / 其它） |
| `source_path` | 相对项目根的原始路径（**反查原件的钥匙**） |
| `source_size` / `source_mtime` | 用于快速判定「未变更」 |
| `source_sha1` | 二进制哈希，用于**改名识别** |
| `md_path` | 产物相对路径（`datas-md/` 之后） |
| `doc_type` / `subject` / `date` / `date_source` / `topic` / `round` / `stage` | 与产物 frontmatter 一致 |
| `duplicate_of` | 疑似重复时指向主文档的 `source_path`（**仅索引**；产物内的同名字段用产物相对路径） |
| `source_status` | `active` / `missing` / `renamed` |
| `md_status` | `ok` / `degraded:{status}` / `stale` / `orphaned` / `error` / `pruned` |
| `renamed_from` | 改名场景记录旧路径 |
| `text_sha1` | 正文归一化哈希，用于**重复识别** |
| `last_run` | 最后一次同步日期 |

**`source_sha1` 与 `text_sha1` 分工**：前者判改名（同一份字节换了名字），
后者判重复（不同的字节抽出了同样的正文）。
二者不能混用——真实数据里的「同文重命名」正是二进制不同、正文完全相同。

配套视图（只读、供人查阅，不参与检索）：
`by_subject.csv`、`by_date.csv`。

## --rebuild：全量重建

```bash
python sync.py --rebuild
```

行为：

1. 重扫 `datas` 两个来源目录
2. 逐文件抽取、写入/覆盖产物
3. **孤儿回收**：扫描 `by_topic/**/*.md`，凡是产物里记着 `source_path`
   但源已不存在的，重新登记为 `missing / orphaned`
4. **陈旧清理**：产物目录里存在、但索引不再引用的 `.md`（路径规则变化遗留）删除
5. 生成两份视图 CSV

`--rebuild` 不依赖历史索引。但**必须依赖产物本身**——否则源已删除的历史知识
会在重建瞬间被判定为「陈旧文件」删除，直接违反「源删除时不得静默丢弃产物」。

安全阀：只删除**同时满足**「在 `by_topic` 下」「首行是 `---`」
「前 3000 字含 `source_path: datas/`」的 `.md`，用户手工放进来的 Markdown 不会被误删。

`--rebuild` 是唯一会删除文件的同步模式（陈旧清理）。其余模式只增改不删。

## --sync：增量

```bash
python sync.py --sync
```

判定顺序：

```
1. 路径相同 且 size 相同 且 sha1 相同 且产物存在   → 跳过
2. 路径相同 但 size/sha1 变了                    → 重新抽取覆盖，索引原行更新
3. 路径不存在、但 sha1 命中已有行                 → 判定为改名（见下）
4. 以上都不满足                                   → 新增
5. 索引里存在、本次扫描不到                       → 源失联（见下）
```

不做全量重跑，单份新增/改动只影响自己那一行。

## 改名 / 移动

判据：**哈希相同、路径不同**。

处理：

1. 原地更新索引行（`source_path` 改为新路径，`source_status=renamed`，
   `renamed_from` 记录旧路径）——**不新建行**
2. 产物路径按新文件名重算，若变化则 `move` 而不是复制
3. 旧路径不再生成 `missing` 行
4. `related_docs` 中的引用由随后的 dedupe 阶段重算，不会断链

示例（`selftest.py` 里就有这条回归）：

```
改名前: active  | datas/商业计划书/A.pptx           | by_topic/…/2019-04-01_BP_A_v1.0.md
改名后: renamed | datas/商业计划书/A-renamed.pptx   | by_topic/…/2019-04-01_BP_A_v1.0.md
                renamed_from: datas/商业计划书/A.pptx
```

注意产物路径**未必**因改名而变：主体、日期、赛道都没变时文件名不变，
此时只需更新索引、无需移动文件。

## 源文件失联

判据：索引里有、源目录里没有。

处理（顺序即优先级，不可省）：

1. 产物 `.md` **保留在原处**，仍可被 glob/grep 命中
2. frontmatter `source_available: false`
3. 正文顶部插入：

   ```
   ⚠️ 源文件已不存在，本产物为历史留存，最后同步于 2026-10-30
   ```
4. 索引记 `source_status=missing`、`md_status=orphaned`
5. **不自动删除**。要清理必须显式：

   ```bash
   python sync.py --prune --dry-run   # 先列清单
   python sync.py --prune             # 交互确认
   python sync.py --prune --yes       # 非交互
   ```

## 双向可查

- 产物 → 原件：产物 frontmatter 的 `source_path`
- 原件 → 产物：索引行的 `md_path`

`validate_output.py` 会双向核对：

- 索引指向的产物不存在 → `I4_INDEX_DRIFT`（FAIL）
- 目录里的产物不在索引 → `I3_UNINDEXED_FILES`（WARN）

## 源目录发现

`datas/` 下每个一级子目录都会被扫描，**不写死目录名**：

```python
source_roots() == [d.name for d in DATAS.iterdir() if d.is_dir()]
```

因此新增 `datas/新目录/` 后，下次 `--sync` 自动纳入，无需改代码。
`source_root` 字段记录「文件来自哪个一级目录」，可回溯性不受影响。

排除某些目录：

```yaml
# _index/overrides.yaml
exclude_roots: [临时目录, 备份]
```

压缩包（`.zip` / `.rar` / `.7z`）在扫描阶段就过滤掉，不进索引。

## 两阶段与索引

OCR 走独立脚本，它改变的是**产物内容与正文哈希**，因此完成后会：

1. 重写该文件对应的索引行（`md_status` 由 `degraded:needs_ocr` 变 `ok`）
2. 重跑一次去重后置阶段——正文变了，相似度与 `duplicate_of` 都可能变

`run_ocr.py` 支持 `--limit` 分批，已完成的文件不会被重复处理（状态已不是 `needs_ocr`）。

## overrides.yaml

人工纠正通道，放在 `datas-md/_index/overrides.yaml`：

```yaml
subject_alias:
  森国科: 森国科SiC
```

用于修正规则无法处理的别名。修改后重跑 `--sync` 即可生效，不会删数据。

## 索引自身不得进入检索结果

`_index/` 下只放 `.csv` / `.yaml` / `.log`，不放 `.md`。
任何 glob 示例都从 `by_topic` 起、并限定 `*.md`：

```bash
glob("datas-md/by_topic/**/*.md")   # ✓
glob("datas-md/**/*")               # ✗ 会带上索引 CSV
```

`validate_output.py` 的 `I5_INDEX_NOT_MD` 会检查这一点。

## 沙箱演练

改名 / 删除属于破坏性操作。演练时用 `FDS_ROOT` 指向临时目录：

```bash
FDS_ROOT=/tmp/sandbox python sync.py --rebuild
```

生产运行**不要**设置该变量。`selftest.py` 就是基于它做的全链路回归。

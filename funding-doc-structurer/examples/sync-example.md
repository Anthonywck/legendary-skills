# 正例：三类同步场景

以下输出均来自 `scripts/selftest.py` 的真实运行（沙箱环境，不触碰 `datas`）。

## 场景一：新增

源目录加入一份新文件后：

```bash
python scripts/sync.py --sync
```

```
处理完成
  新处理 1（新增 1，改名 0）
  跳过未变更 2，失败 0
  索引共 3 行：active 3 / missing 0 / renamed 0
```

新增行：

```
source_status=active  source_path=datas/商业计划书/新文件.pptx
md_path=by_topic/半导体/2019/BP/2019-04-01_BP_A_v1.0.md
```

未变更的两份被直接跳过——不重抽、不重写、产物 mtime 不变。

## 场景二：改名

```bash
mv "datas/商业计划书/A.pptx" "datas/商业计划书/A-renamed.pptx"
python scripts/sync.py --sync
```

```
处理完成
  新处理 1（新增 0，改名 1）
  跳过未变更 2，失败 0
  索引共 3 行：active 2 / missing 0 / renamed 1
```

索引**原地更新**，不是新增行：

```
source_status=renamed
source_path=datas/商业计划书/A-renamed.pptx
renamed_from=datas/商业计划书/A.pptx
md_path=by_topic/半导体/2019/BP/2019-04-01_BP_A_v1.0.md
```

三个关键点：

1. **行数不变**（3 行），旧路径不生成 `missing` 行
2. **产物路径未漂移**：主体/日期/赛道都没变，产物无需移动
3. `renamed_from` 保留旧路径，可追溯

若改名同时改变了主体或日期（例如把 `A.pptx` 改成 `【新材料】B项目商业计划书.pptx`），
则产物路径会重算并**移动**文件，`related_docs` 由 dedupe 阶段重算，不会断链。

## 场景三：源删除

```bash
rm "datas/商业计划书/B.pdf"
python scripts/sync.py --sync
```

```
处理完成
  新处理 0（新增 0，改名 0）
  跳过未变更 2，失败 0
  索引共 3 行：active 2 / missing 1 / renamed 0
```

索引行：

```
source_status=missing  md_status=orphaned
source_path=datas/商业计划书/B.pdf
md_path=by_topic/半导体/2022/BP/2022-05_BP_B_v1.0.md
```

产物**仍然存在**，且仍可被 grep 命中：

```bash
$ grep -c "源文件已不存在" datas-md/by_topic/半导体/2022/BP/2022-05_BP_B_v1.0.md
1
```

产物内部变化：

```yaml
source_available: false          # 原来为 true
```

```markdown
⚠️ 源文件已不存在，本产物为历史留存，最后同步于 2026-10-30
```

**为什么不自动删除**：这份产物承载的是历史知识。源文件在服务器上被误删、
或归档到别处，都不应该让曾经可检索的结论凭空消失。清理必须是主动行为：

```bash
$ python scripts/sync.py --prune --dry-run
以下 1 份产物的源文件已失联，将被删除：
  - by_topic/半导体/2022/BP/2022-05_BP_B_v1.0.md   ← 源: datas/商业计划书/B.pdf
```

确认后加 `--yes` 才会真正删除。

## 场景四：重建后的状态保持

```bash
python scripts/sync.py --rebuild
```

```
处理完成
  新处理 2（新增 2，改名 0）
  索引共 3 行：active 2 / missing 1 / renamed 0
```

关键断言（selftest 覆盖）：

- `--rebuild` 不依赖历史索引，但**不能**因为「索引里没有」就把孤儿产物当成陈旧文件删掉
- 实现方式：重建时扫描产物自身的 `source_path`，凡是源已不存在的，重新登记为 `missing/orphaned`
- 因此重建前后，`missing` 行与孤儿产物都保持不变

## 场景五：幂等

```bash
python scripts/sync.py --rebuild && sha1sum datas-md/**/*.md > a.txt
python scripts/sync.py --rebuild && sha1sum datas-md/**/*.md > b.txt
diff a.txt b.txt        # 无输出
```

两次全量重建，产物逐字节一致。`last_run` 只写进索引 CSV，不写进产物，
所以「今天跑」和「明天跑」的产物完全相同。

## 破坏性操作的沙箱演练

改名 / 删除会动文件，演练时务必隔离：

```bash
export FDS_ROOT=/tmp/fds-sandbox
python scripts/sync.py --rebuild
```

或者直接跑内置回归：

```bash
python scripts/selftest.py
# 19/19 通过
```

`selftest.py` 覆盖：重建 → 幂等 → 改名 → 源删除 → 再重建 → prune → 只读校验。

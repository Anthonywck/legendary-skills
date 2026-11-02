# -*- coding: utf-8 -*-
"""运行报告：把一次同步的结果整理成可读的结构化报告。

要求：成功多少、成功落在哪些目录、失败多少、失败在哪、为什么、怎么办。

产出两份：
1. 终端摘要是人读的，按「结论 → 目录分布 → 失败明细」组织
2. `_index/last_run_report.txt` 是留档的，含逐条明细，可直接贴进工单或周报
"""

from __future__ import annotations

import io
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import common as C

# 每种降级状态的成因与建议，集中维护，报告与文档共用同一套话术
REASON = {
    "needs_ocr": (
        "正文需 OCR：文档为扫描/图片型，或无文本层的页占比过高",
        "确认 OCR 依赖可用（rapidocr）；或从源端获取可搜索版 PDF 后重跑 --sync",
    ),
    "corrupt": (
        "文件损坏或 0 字节",
        "从源端重新获取该文件，覆盖后重跑 --sync",
    ),
    "encrypted": (
        "文件已加密，需要密码",
        "另行解密后放回 datas，重跑 --sync；不要在本工具内尝试破解",
    ),
    "too_large": (
        "超过单文件大小上限，未解析",
        "确认该文件是否必要；必要时提高 extract.py 的 MAX_BYTES 后单独处理",
    ),
    "unsupported": (
        "格式未登记或解析失败",
        "查 assets/formats.yaml；旧版 Office 可用 soffice 转成 .docx/.pptx 后重跑",
    ),
    "encoding_error": (
        "正文字体缺少 ToUnicode 映射，抽取结果为乱码已作废",
        "获取可搜索版 PDF，或对该文件做 OCR 重建文本层后重跑",
    ),
    "empty": (
        "未抽取到正文（文档为空或内容不可读）",
        "人工确认该文件是否有效；无效可从 datas 移除",
    ),
    "error": (
        "处理过程抛出异常",
        "查看 _index/errors.log 中该文件的堆栈，按提示修复后重跑 --sync",
    ),
}


def _reason_of(md_status: str) -> tuple[str, str]:
    key = (md_status or "").split(":", 1)[-1] if md_status.startswith("degraded:") else md_status
    return REASON.get(key, ("未知状态", "检查 errors.log 与索引 md_status"))


def collect(rows: list[dict], stats: dict, dry: bool) -> dict:
    ok_rows = [r for r in rows if r.get("md_status") == "ok" and r.get("source_status") != "missing"]
    bad_rows = [r for r in rows
                if r.get("md_status") not in ("ok", "pruned")
                and r.get("source_status") != "missing"]
    missing_rows = [r for r in rows if r.get("source_status") == "missing"]

    by_dir = Counter()
    for r in ok_rows:
        md = r.get("md_path") or ""
        parts = md.split("/")
        by_dir["/".join(parts[:3]) if len(parts) >= 3 else "未落位"] += 1

    by_type = Counter(r.get("doc_type") or "?" for r in ok_rows)
    by_topic = Counter(r.get("topic") or "?" for r in ok_rows)

    failures = defaultdict(list)
    for r in bad_rows:
        failures[r.get("md_status") or "?"].append(r)

    return {
        "dry": dry,
        "total_indexed": len(rows),
        "ok": len(ok_rows),
        "bad": len(bad_rows),
        "missing": len(missing_rows),
        "missing_rows": missing_rows,
        "by_dir": by_dir,
        "by_type": by_type,
        "by_topic": by_topic,
        "failures": failures,
        "stats": stats,
        "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def render_console(rep: dict) -> str:
    st = rep["stats"]
    L: list[str] = []
    head = "【预演 / 未写盘】" if rep["dry"] else "【已写盘】"
    L.append("=" * 68)
    L.append(f"{head} 处理报告  {rep['when']}")
    L.append("=" * 68)
    L.append(f"本次新处理 {st.get('processed', 0)} 份"
             f"（新增 {st.get('new', 0)}，内容变更/改名 {st.get('renamed', 0)}），"
             f"跳过未变更 {st.get('skipped', 0)}，失败 {st.get('failed', 0)}")
    if st.get("stale_removed"):
        L.append(f"清理陈旧产物 {st['stale_removed']} 份（路径规则变化后不再被索引引用）")
    L.append("")
    L.append(f"成功 {rep['ok']} 份  |  降级/失败 {rep['bad']} 份  |  源已失联 {rep['missing']} 份")
    L.append("")

    if rep["by_dir"]:
        L.append("── 成功产物的目录分布 ──")
        for d, n in sorted(rep["by_dir"].items(), key=lambda x: (-x[1], x[0])):
            L.append(f"  {n:>4} 份  {d}/")
        L.append("")
        L.append("  按文档类型: " + "，".join(f"{k} {v}" for k, v in rep["by_type"].most_common()))
        L.append("  按赛道:     " + "，".join(f"{k} {v}" for k, v in rep["by_topic"].most_common()))
        L.append("")

    if rep["failures"]:
        L.append("── 失败 / 降级明细 ──")
        for status, rows in sorted(rep["failures"].items(), key=lambda x: -len(x[1])):
            why, how = _reason_of(status)
            L.append(f"  [{status}] {len(rows)} 份 —— {why}")
            for r in rows[:5]:
                L.append(f"      ・{r.get('source_path', '')}")
            if len(rows) > 5:
                L.append(f"      ・…… 另 {len(rows) - 5} 份，见 _index/last_run_report.txt")
            L.append(f"      建议：{how}")
        L.append("")

    if rep["missing"]:
        L.append(f"── 源已失联 {rep['missing']} 份（产物已保留，仍可检索）──")
        for r in rep["missing_rows"][:5]:
            L.append(f"      ・{r.get('source_path', '')}  →  {r.get('md_path', '')}")
        if rep["missing"] > 5:
            L.append(f"      ・…… 另 {rep['missing'] - 5} 份")
        L.append("      建议：确认源文件是否被移动/删除；确需清理用 --prune")
        L.append("")

    L.append(f"索引: {C.rel_posix(C.INDEX_CSV)}")
    if rep["failures"] or st.get("failed"):
        L.append(f"错误日志: {C.rel_posix(C.ERROR_LOG)}")
    L.append(f"完整报告: {C.rel_posix(C.INDEX_DIR / 'last_run_report.txt')}")
    L.append("=" * 68)
    return "\n".join(L)


def write_markdown(rep: dict) -> Path:
    st = rep["stats"]
    path = C.INDEX_DIR / "last_run_report.txt"
    L: list[str] = []
    L.append(f"# 处理报告 {rep['when']}")
    L.append("")
    L.append(f"> {'预演（未写盘）' if rep['dry'] else '已写盘'}")
    L.append("")
    L.append("## 总览")
    L.append("")
    L.append("| 指标 | 数量 |")
    L.append("| --- | --- |")
    L.append(f"| 新处理 | {st.get('processed', 0)}（新增 {st.get('new', 0)}，改名/变更 {st.get('renamed', 0)}） |")
    L.append(f"| 跳过未变更 | {st.get('skipped', 0)} |")
    L.append(f"| 处理失败（异常） | {st.get('failed', 0)} |")
    L.append(f"| 成功产物 | {rep['ok']} |")
    L.append(f"| 降级/失败产物 | {rep['bad']} |")
    L.append(f"| 源已失联 | {rep['missing']} |")
    if st.get("stale_removed"):
        L.append(f"| 清理陈旧产物 | {st['stale_removed']} |")
    L.append(f"| 索引总行数 | {rep['total_indexed']} |")
    L.append("")

    if rep["by_dir"]:
        L.append("## 成功产物落位")
        L.append("")
        L.append("| 目录 | 数量 |")
        L.append("| --- | --- |")
        for d, n in sorted(rep["by_dir"].items(), key=lambda x: (-x[1], x[0])):
            L.append(f"| `{d}/` | {n} |")
        L.append("")
        L.append("按文档类型：" + "，".join(f"{k} {v}" for k, v in rep["by_type"].most_common()))
        L.append("")
        L.append("按赛道：" + "，".join(f"{k} {v}" for k, v in rep["by_topic"].most_common()))
        L.append("")

    if rep["failures"]:
        L.append("## 失败与降级")
        L.append("")
        for status, rows in sorted(rep["failures"].items(), key=lambda x: -len(x[1])):
            why, how = _reason_of(status)
            L.append(f"### `{status}` — {len(rows)} 份")
            L.append("")
            L.append(f"- **原因**：{why}")
            L.append(f"- **建议**：{how}")
            L.append("")
            L.append("| 源文件 | 产物 |")
            L.append("| --- | --- |")
            for r in rows:
                L.append(f"| `{r.get('source_path', '')}` | `{r.get('md_path', '') or '（无产物）'}` |")
            L.append("")

    if rep["missing"]:
        L.append("## 源已失联")
        L.append("")
        L.append("产物已保留在原处，仍可被 glob/grep 命中，frontmatter 标记 `source_available: false`。")
        L.append("")
        L.append("| 源路径 | 产物路径 |")
        L.append("| --- | --- |")
        for r in rep["missing"]:
            L.append(f"| `{r.get('source_path', '')}` | `{r.get('md_path', '')}` |")
        L.append("")
        L.append("清理需显式执行 `sync.py --prune`。")
        L.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    return path


def emit(rows: list[dict], stats: dict, dry: bool = False) -> dict:
    """生成并打印报告；返回汇总 dict 供调用方判断退出码。"""
    rep = collect(rows, stats, dry)
    print(render_console(rep))
    if not dry:
        try:
            write_markdown(rep)
        except OSError as exc:
            C.log_error(f"报告写入失败: {exc}")
    return rep

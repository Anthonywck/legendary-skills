# -*- coding: utf-8 -*-
"""产物渲染与单文件处理：元数据记录 → Markdown 文本 → 落盘。

本模块只负责「把已经抽好的内容写成文件」，不做扫描、不做索引、不做同步判定。
"""

from __future__ import annotations

import io
from pathlib import Path

import common as C
from build_frontmatter import build_record, validate_fields
from clean import clean_text
from extract import extract

WARN_MISSING = "⚠️ 源文件已不存在，本产物为历史留存，最后同步于 {last_run}"


# ---------------------------------------------------------------------------
# 产物渲染
# ---------------------------------------------------------------------------


def render_md(rec: dict, res, *, last_run: str, source_available: bool) -> str:
    fm = dict(rec["frontmatter"])
    fm["source_available"] = source_available

    body: list[str] = []
    body.append(f"# {fm['title']}")
    body.append("")
    if not source_available:
        body.append(WARN_MISSING.format(last_run=last_run))
        body.append("")

    body.append(C.EMPTY_DEDUPE_BLOCK)
    body.append("")
    body.append("## 元数据速查")
    body.append("")
    body.append(f"- 公司全称: {fm.get('alias_full') or 'null'}")
    body.append(f"- 公司简称: {fm.get('alias_short') or 'null'}")
    body.append(f"- 英文名: {fm.get('alias_en') or 'null'}")
    body.append(f"- 拼音首字母: {fm.get('alias_pinyin') or 'null'}")
    body.append(f"- 文档类型: {fm['doc_type']}")
    body.append(f"- 所属赛道: {fm['topic']}")
    body.append(f"- 文件日期: {fm['date']}（来源: {fm['date_source']}）")
    body.append(f"- 融资轮次: {fm.get('round') or 'null'}")
    body.append(f"- 原始文件: {fm['source_path']}")
    body.append("")
    body.append("## 摘要")
    body.append("")
    body.append(fm["summary"])
    body.append("")

    if fm.get("key_facts"):
        body.append("## 关键事实")
        body.append("")
        for f in fm["key_facts"]:
            body.append(f"- {f}")
        body.append("")

    if rec.get("evidence"):
        body.append("## 原文证据")
        body.append("")
        body.append("| 字段 | 值 | 原文片段 |")
        body.append("| --- | --- | --- |")
        for k, (val, snippet) in rec["evidence"].items():
            body.append(f"| {k} | {val.replace('|', '／')} | {snippet.replace('|', '／')} |")
        body.append("")

    if rec.get("warnings"):
        body.append("## 抽取提示")
        body.append("")
        for w in rec["warnings"]:
            body.append(f"- {w}")
        body.append("")

    body.append("## 正文")
    body.append("")
    content = res.markdown or res.text
    if content:
        body.append(content.strip())
    else:
        body.append(f"（无可抽取正文。extraction_status: {res.status}）")
    body.append("")

    # 整份产物统一清洗：frontmatter 由 render_frontmatter 生成（本身规整），
    # 这里只处理正文与证据表；代码围栏内的内容不受影响。
    return clean_text(C.render_frontmatter(fm) + "\n\n" + "\n".join(body))


# ---------------------------------------------------------------------------
# 路径分配
# ---------------------------------------------------------------------------


class PathAllocator:
    def __init__(self, taken: dict[str, str]):
        # md_path -> source_path（已有归属）
        self.taken = dict(taken)

    def assign(self, base: str, source_path: str, sha1: str) -> str:
        if self.taken.get(base, source_path) == source_path:
            self.taken[base] = source_path
            return base
        stem = base[:-3]
        for n in (8, 12, 16):
            cand = f"{stem}-{sha1[:n]}.md"
            if self.taken.get(cand, source_path) == source_path:
                self.taken[cand] = source_path
                return cand
        raise RuntimeError(f"路径无法消歧: {base}")


# ---------------------------------------------------------------------------
# 单文件处理
# ---------------------------------------------------------------------------


def process(src: dict, tax: dict, last_run: str) -> tuple[dict, object] | tuple[None, str]:
    try:
        res = extract(src["abs"])
    except Exception as exc:  # noqa: BLE001
        return None, f"{src['source_path']}: 抽取失败 {type(exc).__name__}: {exc}"
    if not res.notes.get("fs_mtime"):
        res.notes["fs_mtime"] = src["mtime"]
    try:
        rec = build_record(src=src["abs"], source_root=src["source_root"], res=res,
                           tax=tax, last_run=last_run)
    except Exception as exc:  # noqa: BLE001
        return None, f"{src['source_path']}: 元数据生成失败 {type(exc).__name__}: {exc}"
    errs = validate_fields(rec, tax)
    if errs:
        rec["warnings"] = list(rec.get("warnings") or []) + [f"字段校验: {e}" for e in errs]
    return rec, res


def write_md(rec: dict, res, md_path: str, last_run: str, dry: bool) -> None:
    target = C.OUT / md_path
    text = render_md(rec, res, last_run=last_run, source_available=True)
    if dry:
        return
    if target.exists() and io.open(target, encoding="utf-8").read() == text:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    io.open(target, "w", encoding="utf-8", newline="\n").write(text)


def row_of(src: dict, rec: dict, res, md_path: str, sha1: str, last_run: str) -> dict:
    fm = rec["frontmatter"]
    return {
        "source_root": src["source_root"],
        "source_path": src["source_path"],
        "source_size": str(src["size"]),
        "source_mtime": src["mtime"],
        "source_sha1": sha1,
        "md_path": md_path,
        "doc_type": fm["doc_type"],
        "subject": fm["subject"],
        "date": fm["date"],
        "date_source": fm["date_source"],
        "topic": fm["topic"],
        "round": fm.get("round") or "",
        "stage": fm.get("status") or "",
        "duplicate_of": "",
        "source_status": "active",
        "md_status": "ok" if res.status == "ok" else f"degraded:{res.status}",
        "text_sha1": res.text_sha1 if res.status == "ok" else "",
        "last_run": last_run,
    }


# ---------------------------------------------------------------------------
# 失联 / 孤儿
# ---------------------------------------------------------------------------


def mark_missing(row: dict, last_run: str, dry: bool) -> None:
    row["source_status"] = "missing"
    row["md_status"] = "orphaned"
    md = C.OUT / row["md_path"] if row.get("md_path") else None
    if dry or not md or not md.exists():
        return
    text = io.open(md, encoding="utf-8").read()
    if "source_available: true" in text:
        text = text.replace("source_available: true", "source_available: false", 1)
    warn = WARN_MISSING.format(last_run=last_run)
    if warn not in text:
        marker = "\n## 元数据速查"
        text = text.replace(marker, f"\n{warn}\n{marker}", 1) if marker in text else text + "\n" + warn
    io.open(md, "w", encoding="utf-8", newline="\n").write(text)


# -*- coding: utf-8 -*-
"""日期解析与标题/主体辅助：防臆造的日期闸门都在这里。

本模块只决定「日期取什么值、来自哪里」，不写文件、不碰索引。
"""

from __future__ import annotations

import re

import common as C
from extract import ExtractResult

HEAD_LINES = 6
TAIL_LINES = 12
DATE_EVIDENCE_KEYS = {"date"}


def _resolve_date(name: str, source_root: str, res: ExtractResult) -> tuple[str, str, dict]:
    """返回 (date, date_source, evidence)。

    优先级严格按《蒸馏约束》第 2 条：
    filename 之外的 doc_text 只在「封面/落款行的日期为主体」时才采纳，
    这是本 Skill 防止日期臆造的核心闸门。
    """
    # 1. 正文落款（优先级最高，但判定最严）
    if res.text:
        d, prec, line = _date_from_zone(res)
        if d:
            return d, "doc_text", {"date": (d, line)}
    # 2. 文件名
    d, _prec = C.date_from_filename(name, source_root)
    if d:
        return d, "filename", {"date": (d, f"文件名: {name}")}
    # 3. 文档内部元数据
    d, _ = C.date_from_meta(res.meta)
    if d:
        raw = str(res.meta.get("creationDate") or res.meta.get("created") or "")
        return d, "doc_meta", {"date": (d, raw)}
    # 4. 文件系统 mtime
    if res.notes.get("fs_mtime"):
        return res.notes["fs_mtime"], "fs_mtime", {"date": (res.notes["fs_mtime"], "文件系统 mtime")}
    return "unknown", "unknown", {}


def _date_zone(res: ExtractResult) -> str:
    """保留给调试与文档示例：返回封面 + 收尾的原始窗口文本。"""
    return _zone_text(res)


def _zone_text(res: ExtractResult) -> str:
    lines = [ln for ln in (res.text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    head = lines[:HEAD_LINES]
    tail = lines[-TAIL_LINES:]
    return "\n".join(head + tail)


def _date_from_zone(res: ExtractResult) -> tuple[str | None, str | None, str]:
    """只在封面区与落款区找「以日期为主体」的行。

    封面区只认 年月/全日期 精度，不认单独年份（封面常印「2023」品牌年份）。
    """
    lines = [ln for ln in (res.text or "").splitlines() if ln.strip()]
    if not lines:
        return None, None, ""
    candidates: list[tuple[str, str, str]] = []
    for ln in lines[:HEAD_LINES]:
        hit = C.date_line_of(ln)
        if hit and hit[1] in ("day", "month"):
            candidates.append((hit[0], hit[1], ln.strip()))
    for ln in lines[-TAIL_LINES:]:
        hit = C.date_line_of(ln)
        if hit:
            candidates.append((hit[0], hit[1], ln.strip()))
    if not candidates:
        return None, None, ""
    # 精度优先，同日取出现位置最靠前者（封面优先于尾页）
    order = {"day": 0, "month": 1, "year": 2}
    candidates.sort(key=lambda c: order[c[1]])
    d, prec, ln = candidates[0]
    return d, prec, ln


_TITLE_ILLEGAL = re.compile(r"[\\/:*?\"<>|]")


def _title(res: ExtractResult, name: str) -> str:
    """标题优先取文件名主干（干净、稳定），清洗非法字符但保留可读性。"""
    stem = re.sub(r"\.[^.]+$", "", name)
    stem = _TITLE_ILLEGAL.sub("", stem).strip()
    return stem or res.path


def _doc_type_guess(name: str, source_root: str) -> str:
    return "BP" if source_root == "商业计划书" else "REPORT"


_REPORT_PREFIX = re.compile(r"^[^：:]{2,12}[：:]\s*")


def _report_subject(name: str) -> str:
    """行业报告的主体 = 发布机构。

    券商/咨询报告几乎都是「机构：标题…」，因此以冒号前为机构；
    没有机构前缀时退回文件名第一段（与 BP 同规则）。
    """
    stem = re.sub(r"\.[^.]+$", "", name)
    m = _REPORT_PREFIX.match(stem)
    if m:
        org = m.group(0).rstrip("：: ").strip()
        org = re.sub(r"^(?:&|and)\s*", "", org)
        if org and len(org) <= 12:
            return C.sanitize_component(org, maxlen=20)
    return C.subject_from_filename(name)


def _degraded_summary(res: ExtractResult) -> str:
    m = {
        "needs_ocr": "⚠️ 文本层为空（疑似扫描/图片型文档），需 OCR 后重新抽取；本产物仅登记元数据。",
        "empty": "⚠️ 未抽取到正文（文档为空或内容不可读）；本产物仅登记元数据。",
        "corrupt": "⚠️ 文件损坏或无有效内容（可能为 0 字节）；本产物仅登记元数据。",
        "encrypted": "⚠️ 文件已加密，未解析；本产物仅登记元数据。",
        "too_large": "⚠️ 文件体积超限，未解析；本产物仅登记元数据。",
        "unsupported": "⚠️ 格式未支持，未解析；本产物仅登记元数据。",
        "encoding_error": "⚠️ 正文字体缺少 ToUnicode 映射，抽取结果为乱码已作废；本产物仅登记元数据，需重新获取可搜索版 PDF 或 OCR。",
    }
    return m.get(res.status, "⚠️ 抽取异常，仅登记元数据。")



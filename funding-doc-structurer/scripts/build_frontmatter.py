# -*- coding: utf-8 -*-
"""元数据生成与校验。

设计原则：字段值一律来自可回溯来源，抽不到就写 null / unknown。
本模块不调用任何模型 —— 摘要与 key_facts 走「规则抽取 + 原文摘录」，
宁可少写，不编造。

入口：
    build_record(...) -> dict      单个文件的完整记录（含 frontmatter 数据与路径）
    validate_fields(rec) -> list   字段级校验（返回错误列表）
"""

from __future__ import annotations

import re
from pathlib import Path

import common as C
from date_resolve import (_date_from_zone, _date_zone, _report_subject, _resolve_date,
                          _title, _doc_type_guess, _degraded_summary)
from extract import ExtractResult, usable_text  # noqa: F401  再导出供 tests/调用
from facts import (build_evidence, build_key_facts, build_summary, extract_facts,
                   _clean_lines, _doc_headline, _PATTERNS)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

_PATTERNS = {
    "投前估值": [r"投前估值[：:\s]*([0-9.,]+\s*(?:亿|万|百万|千万)?[元美]?[人民币美元]?[币]?)"],
    "投后估值": [r"投后估值[：:\s]*([0-9.,]+\s*(?:亿|万|百万|千万)?[元美]?[人民币美元]?[币]?)",
                 r"估值[：:\s]*([0-9.,]+\s*(?:亿|万)[元]?[人民币]?)"],
    "融资金额": [r"融资(?:金额|额)[：:\s]*([0-9.,]+\s*(?:亿|万|百万|千万)[元美]?[人民币美元]?)",
                 r"拟(?:融资|增发)[^。\n]{0,20}?([0-9.,]+\s*(?:亿|万)[元]?)"],
    "轮次": [r"(Pre-?[A-E]\+{0,2}轮|[A-E]\+{0,2}轮|种子轮|天使轮)"],
    # 成立时间只在主语就是文档主体时才成立；这里要求句子以「公司/本公司/我们」为主语，
    # 否则「SMEE 成立于 2002 年」会被误记成该 BP 主体的成立时间。
    "成立时间": [r"(?:^|[。；;\n])\s*(?:公司|本公司|我们)(?:成立|创立)于\s*((?:19|20)\d{2}年(?:\d{1,2}月)?)",
                 r"公司成立于\s*((?:19|20)\d{2}年(?:\d{1,2}月)?)"],
    "所在地区": [r"(?:总部(?:位于|设在)?|公司(?:位于|地址))[：:\s]*([^\n，。；;]{2,12}?(?:市|区|省|县))"],
    "营收": [r"(?:营收|营业收入|销售额)[：:\s约]*([0-9.,]+\s*(?:亿|万)[元]?)"],
}

_MAX_EVIDENCE = 120


def _find(patterns: list[str], text: str) -> tuple[str | None, str | None]:
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1) if m.groups() else m.group(0)
            val = re.sub(r"\s+", "", val)
            # 去掉「设立在/位于/设在」这类谓语残留，只留地名
            val = re.sub(r"^(?:设立在|位于|设在|坐落于|地处)", "", val)
            start = max(0, m.start() - 40)
            ev = re.sub(r"\s+", " ", text[start:m.end() + 40]).strip()
            return val, ev[:_MAX_EVIDENCE]
    return None, None


def extract_facts(text: str) -> dict[str, tuple[str | None, str | None]]:
    return {k: _find(v, text) for k, v in _PATTERNS.items()}


# ---------------------------------------------------------------------------
# 摘要：原文摘录式，不生成新句子
# ---------------------------------------------------------------------------

_BOILERPLATE = re.compile(r"行业报告资源群|扫码|公众号|微信群|免责声明|风险提示|客服微信|进群即领")


def build_key_facts(facts: dict, res: ExtractResult, doc_type: str) -> list[str]:
    """统一 `字段: 值` 一行一条。只收有原文证据的。"""
    out: list[str] = []
    for key in ("轮次", "投前估值", "投后估值", "融资金额", "成立时间", "所在地区", "营收"):
        val, _ = facts.get(key, (None, None))
        if val:
            out.append(f"{key}: {val}")
    if doc_type == "REPORT":
        authors = _find([r"([一-龥]{2,4})\s*[（(]证券分析师[）)]"], res.text)
        if authors[0]:
            out.append(f"分析师: {authors[0]}")
        org = _find([r"\n([一-龥]{2,8}(?:证券|研究所|咨询|资本|研究院))"], res.text)
        if org[0]:
            out.append(f"发布机构: {org[0]}")
    if res.pages:
        out.append(f"页数: {res.pages}")
    return out


def build_evidence(facts: dict) -> dict[str, tuple[str, str]]:
    """字段 → (值, 原文证据片段)。写入 frontmatter 之外的正文附录，供人工回溯。

    值和证据必须成对出现：只给片段时，读者无法判断片段是否真的支持该值。
    """
    ev = {}
    for key, (val, snippet) in facts.items():
        if val and snippet:
            ev[key] = (val, snippet)
    return ev


# ---------------------------------------------------------------------------
# 别名：全称 / 简称 / 英文名 / 拼音首字母
# ---------------------------------------------------------------------------


def _pinyin_initials(s: str) -> str | None:
    try:
        from pypinyin import Style, lazy_pinyin
    except Exception:  # noqa: BLE001
        return None
    letters = [x[0] for x in lazy_pinyin(s, style=Style.FIRST_LETTER, errors="ignore") if x]
    res = "".join(letters).lower()
    return res or None


def build_aliases(subject: str, full_names: list[str]) -> dict:
    """别名只做「同一实体的写法扩展」，绝不做跨实体推断。

    alias_full 必须是「包含主体名」的工商全称：正文里第一个出现的全称可能是
    完全不相干的公司（例如 BP 里提到的行业巨头），直接取首条即为臆造。
    """
    alias_short = subject if subject != "unknown" else None
    core = C.subject_key(subject)
    alias_full = None
    for n in full_names:
        if core and core in C.subject_key(n):
            alias_full = n
            break
    # 英文名要求：主体里整段就是拉丁字母（如 Imsys、VisIC）。
    # 不能用「含拉丁字母」判定——「森国科SiC」里的 SiC 是技术缩写而不是英文名。
    alias_en = subject if subject and re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'-]{1,40}", subject) else None
    return {
        "alias_full": alias_full,
        "alias_short": alias_short,
        "alias_en": alias_en,
        "alias_pinyin": _pinyin_initials(subject) if alias_short else None,
    }


# ---------------------------------------------------------------------------
# 记录组装
# ---------------------------------------------------------------------------


def build_record(*, src: Path, source_root: str, res: ExtractResult, tax: dict,
                 last_run: str, source_available: bool = True) -> dict:
    name = src.name
    text = usable_text(res)
    subject = C.subject_from_filename(name)
    full_names = C.full_names_from_text(text) if text else []
    if subject == "unknown" and full_names:
        subject = C.sanitize_component(full_names[0])
    if _doc_type_guess(name, source_root) == "REPORT":
        subject = _report_subject(name)
        full_names = []            # 行业报告正文里的公司名不是「本文件主体」，不可做别名

    topic, tags, topic_reason = C.classify_topic(name, text, tax)
    doc_type = C.doc_type_of(name, source_root, tax)

    date, date_source, date_evidence = _resolve_date(name, source_root, res)
    rnd = C.round_of(name, text)
    version = C.version_of(name)
    status = C.status_of(name)

    facts = extract_facts(text) if text else {k: (None, None) for k in _PATTERNS}
    title = _title(res, name)
    summary = build_summary(res, subject, doc_type, topic, facts, title) \
        if res.status == "ok" else _degraded_summary(res)
    key_facts = build_key_facts(facts, res, doc_type)

    aliases = build_aliases(subject, full_names)
    alias_tags = [v for v in (aliases["alias_full"], aliases["alias_en"]) if v]
    all_tags = C.dedup(tags + [subject] + alias_tags)

    md_path = C.build_relative_md_path(topic=topic, date=date, doc_type=doc_type,
                                       subject=subject, version=version, status=status)

    fm = {
        "title": title,
        "doc_type": doc_type,
        "project": None,
        "date": date,
        "date_source": date_source,
        "version": version,
        "status": status,
        "round": rnd,
        "author": res.meta.get("author") or None,
        "reviewers": [],
        "subject": subject,
        "topic": topic,
        "tags": all_tags,
        **aliases,
        "summary": summary,
        "key_facts": key_facts,
        "related_docs": [],
        "duplicate_of": None,
        "source_available": source_available,
        "source_root": source_root,
        "source_path": C.rel_posix(src),
        "extraction_status": res.status,
    }
    return {
        "frontmatter": fm,
        "md_path": md_path,
        "topic": topic, "topic_reason": topic_reason, "tags": all_tags,
        "subject": subject, "doc_type": doc_type, "date": date, "date_source": date_source,
        "round": rnd or "", "evidence": {**build_evidence(facts), **date_evidence},
        "warnings": list(res.warnings), "extraction_status": res.status,
    }


# 落款搜索窗口（行数）—— 只看封面与收尾，不看正文中段，避免把历史事件日期当文档日期
# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

VALID_DATE_SOURCE = {"doc_text", "filename", "doc_meta", "fs_mtime", "unknown"}
REQUIRED = ["title", "doc_type", "date", "date_source", "subject", "topic", "summary"]


def validate_fields(rec: dict, tax: dict) -> list[str]:
    errs: list[str] = []
    fm = rec["frontmatter"]
    for k in REQUIRED:
        if k not in fm:
            errs.append(f"缺少必需字段 {k}")
    if fm.get("date_source") not in VALID_DATE_SOURCE:
        errs.append(f"date_source 非法: {fm.get('date_source')}")
    if fm.get("date") != "unknown":
        if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", str(fm["date"])):
            errs.append(f"date 格式非法: {fm['date']}")
        if fm.get("date_source") == "unknown":
            errs.append("date 有值但 date_source=unknown")
    else:
        if fm.get("date_source") != "unknown":
            errs.append("date=unknown 但 date_source 非 unknown")
    if fm.get("topic") not in (tax.get("topics") or {}):
        errs.append(f"topic 不在封闭集: {fm.get('topic')}")
    if fm.get("doc_type") not in (tax.get("doc_types") or {}):
        errs.append(f"doc_type 不在枚举: {fm.get('doc_type')}")
    # 与 validate_output 保持同一口径：技术文档/笔记本、以及正文不可用的文件，
    # key_facts 允许为空。否则每份这类文件都会被写进「抽取提示」，噪声淹掉真问题。
    usable = str(fm.get("extraction_status") or "ok") == "ok"
    if not fm.get("key_facts") and fm.get("doc_type") not in ("DOC", "NOTE", "SHEET") and usable:
        errs.append("key_facts 为空")
    for line in fm.get("key_facts") or []:
        if ": " not in line:
            errs.append(f"key_facts 条目不符合 `字段: 值`: {line}")
            break
    if fm.get("subject") and fm["subject"] not in "".join(fm.get("tags") or []):
        errs.append("subject 未出现在 tags 中")
    return errs

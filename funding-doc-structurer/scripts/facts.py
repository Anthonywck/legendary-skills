# -*- coding: utf-8 -*-
"""事实抽取与摘要生成：全部为规则 + 原文摘录，不调用模型。

设计约束：抽不到就返回 None，绝不推断；每个值都附原文证据片段。
"""

from __future__ import annotations

import re

from extract import ExtractResult, usable_text

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
# 证据片段只在「同一句」内截取：跨句拼出来的片段读起来像乱码，也无法自证
_SENT_END = "。；;！!？?\n"


def _snippet(text: str, start: int, end: int) -> str:
    """取匹配所在的整句（同句内前后各留一段），保留换行以贴近原文版式。

    不跨句：向前找最近的句末标点，向后找最近的句末标点。
    """
    b = max(text.rfind(c, 0, start) for c in _SENT_END) + 1
    e = min((text.find(c, end) if text.find(c, end) != -1 else len(text)) for c in _SENT_END)
    b, e = max(0, b), (e + 1 if e < len(text) else len(text))
    seg = text[b:e].strip()
    if len(seg) > _MAX_EVIDENCE:
        seg = seg[:_MAX_EVIDENCE].rstrip() + "…"
    return re.sub(r"[ \t]+", " ", seg)


def _find(patterns: list[str], text: str) -> tuple[str | None, str | None]:
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1) if m.groups() else m.group(0)
            val = re.sub(r"\s+", "", val)
            # 去掉「设立在/位于/设在」这类谓语残留，只留地名
            val = re.sub(r"^(?:设立在|位于|设在|坐落于|地处)", "", val)
            return val, _snippet(text, m.start(), m.end())
    return None, None


def extract_facts(text: str) -> dict[str, tuple[str | None, str | None]]:
    return {k: _find(v, text) for k, v in _PATTERNS.items()}


# ---------------------------------------------------------------------------
# 摘要：原文摘录式，不生成新句子
# ---------------------------------------------------------------------------

_BOILERPLATE = re.compile(r"行业报告资源群|扫码|公众号|微信群|免责声明|风险提示|客服微信|进群即领")


def _clean_lines(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or len(s) < 8:
            continue
        if _BOILERPLATE.search(s):
            continue
        out.append(s)
    return out


_KIND_LABEL = {
    "BP": "商业计划书",
    "REPORT": "行业研究报告",
    "WHITEPAPER": "白皮书",
    "DOC": "技术方案文档",
    "NOTE": "笔记",
    "SHEET": "表格数据",
    "OTHER": "文档",
}


def build_summary(res: ExtractResult, subject: str, doc_type: str, topic: str,
                  facts: dict, title: str = "") -> str:
    """1-3 句事实摘要。全部来自原文，句式固定，便于 grep。

    首句优先取文件名（对用户稳定可读），文件名不可用时才取可信正文首行。
    """
    text = usable_text(res)
    lines = _clean_lines(text)
    parts: list[str] = []

    head = title or _doc_headline(res)
    if head:
        parts.append(head)

    who = f"{subject}" if subject and subject != "unknown" else "主体未识别"
    kind = _KIND_LABEL.get(doc_type, "文档")
    parts.append(f"{who}的{kind}，归属「{topic}」赛道。")

    fact_bits = []
    for key in ("轮次", "投前估值", "投后估值", "融资金额", "成立时间", "营收"):
        val, _ = facts.get(key, (None, None))
        if val:
            fact_bits.append(f"{key} {val}")
    if fact_bits:
        parts.append("原文关键数据：" + "；".join(fact_bits) + "。")
    elif doc_type == "REPORT" and lines:
        lead = min(lines[:2], key=len)
        if len(lead) > 60:
            lead = lead[:60] + "…"
        parts.append(f"报告主线：{lead}")
    else:
        parts.append("原文未提供明确的融资数据。")
    return " ".join(parts)


def _doc_headline(res: ExtractResult) -> str:
    """首页标题。只用可信正文；乱码/扫描件回退为空，由调用方省略首句。"""
    text = usable_text(res)
    if not text:
        return ""
    lines = _clean_lines(res.first_page_text or text[:600])
    for ln in lines:
        if len(ln) >= 6 and not re.fullmatch(r"[\d\W]+", ln):
            return ln[:60]
    return ""


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


def build_evidence(facts: dict) -> dict[str, str]:
    """字段 → 原文证据片段。写入 frontmatter 之外的正文附录，供人工回溯。"""
    ev = {}
    for key, (val, snippet) in facts.items():
        if val and snippet:
            ev[key] = snippet
    return ev



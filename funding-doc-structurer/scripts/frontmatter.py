# -*- coding: utf-8 -*-
"""Frontmatter 序列化：固定字段序 → 保证幂等。

只负责「把 dict 写成 YAML 块」，不参与任何取值判定。
"""

from __future__ import annotations

import json
import re

# 字段序固定：同一数据的两次序列化必须逐字节一致
FM_ORDER = [
    "title", "doc_type", "project", "date", "date_source", "version", "status",
    "round", "author", "reviewers", "subject", "topic", "tags",
    "summary", "key_facts", "related_docs", "duplicate_of", "source_available",
    "source_root", "source_path",
]

_NEEDS_QUOTE = re.compile(r'[:#\[\]{}&*!|>\'"%@`,\n\t]')


def _scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or _NEEDS_QUOTE.search(s) or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    return s


def render_frontmatter(data: dict) -> str:
    lines = ["---"]
    keys = [k for k in FM_ORDER if k in data] + [k for k in data if k not in FM_ORDER]
    for k in keys:
        v = data[k]
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {_scalar(item)}")
        elif isinstance(v, str) and "\n" in v:
            lines.append(f"{k}: |")
            for ln in v.splitlines():
                lines.append(f"  {ln}")
        else:
            lines.append(f"{k}: {_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)

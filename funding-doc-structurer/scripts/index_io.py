# -*- coding: utf-8 -*-
"""索引读写：files_index.csv 与其分组视图。

索引是可重建的派生缓存，不是唯一事实来源；本模块只负责序列化，
不参与任何判定。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from common import ERROR_LOG, INDEX_CSV, INDEX_FIELDS, OVERRIDES, log_error

# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------

def read_index(path: Path = INDEX_CSV) -> list[dict]:
    if not path.exists():
        return []
    with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_index(rows: list[dict], path: Path = INDEX_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r.get("source_root", ""), r.get("source_path", "")))
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in INDEX_FIELDS})


def write_view(rows: list[dict], by: str, path: Path) -> None:
    """生成分组视图 CSV（只读派生，供人肉查阅；不参与检索）。"""
    key = {"subject": "subject", "date": "date", "topic": "topic"}[by]
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([key, "doc_count", "source_root", "source_path", "md_path", "date", "source_status"])
        for r in sorted(rows, key=lambda x: (x.get(key, ""), x.get("date", ""))):
            w.writerow([r.get(key, ""), "", r.get("source_root", ""), r.get("source_path", ""),
                        r.get("md_path", ""), r.get("date", ""), r.get("source_status", "")])


def load_overrides() -> dict:
    if not OVERRIDES.exists():
        return {}
    try:
        import yaml
        with io.open(OVERRIDES, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        log_error(f"overrides.yaml 解析失败: {exc}")
        return {}

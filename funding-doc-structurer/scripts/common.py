# -*- coding: utf-8 -*-
"""funding-doc-structurer 公共库：路径、配置、哈希、日期、赛道、主体、命名、索引。

所有判定都是纯函数 + 显式配置表，保证同一输入两次运行结果完全一致。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    # FDS_ROOT 仅用于沙箱演练（改名/删除等破坏性场景），生产运行不要设置
    override = os.environ.get("FDS_ROOT")
    if override:
        return Path(override).resolve()
    # .claude/skills/<name>/scripts/common.py
    # parents: 0=scripts 1=<name> 2=skills 3=.claude 4=项目根
    p = Path(__file__).resolve()
    for cand in p.parents:
        if (cand / "datas").is_dir():
            return cand
    return Path.cwd()


ROOT = project_root()
SKILL = skill_root()
DATAS = ROOT / "datas"
OUT = ROOT / "datas-md"
INDEX_DIR = OUT / "_index"
INDEX_CSV = INDEX_DIR / "files_index.csv"
ERROR_LOG = INDEX_DIR / "errors.log"
OVERRIDES = INDEX_DIR / "overrides.yaml"

INDEX_FIELDS = [
    "source_root", "source_path", "source_size", "source_mtime", "source_sha1",
    "md_path", "doc_type", "subject", "date", "date_source", "topic",
    "round", "stage", "duplicate_of", "source_status", "md_status", "renamed_from",
    "text_sha1", "last_run",
]

# 索引只记录真实存在的产物；空串表示该文件尚无产物（抽取失败等）
EMPTY_DEDUPE_BLOCK = "<!-- dedupe:begin -->\n<!-- dedupe:end -->"

# ---------------------------------------------------------------------------
# 配置加载（pyyaml 缺失时回退内置默认）
# ---------------------------------------------------------------------------

_BUILTIN_TAXONOMY = {
    "unknown_year": "unknown",
    "unknown_date": "unknown",
    "unknown_subject": "unknown",
    "default_version": "v1.0",
    "topics": {"半导体": {}, "新材料": {}, "新能源": {}, "企业服务": {}, "节能环保": {}, "其他": {}},
    "bracket_map": {},
    "keyword_rules": [],
    "doc_types": {"BP": {}, "REPORT": {}, "WHITEPAPER": {}, "OTHER": {}},
    "doc_type_rules": [],
}

_BUILTIN_FORMATS = {
    "default": {"status": "unsupported", "reason": "格式未登记"},
    "formats": {
        ".pdf": {"status": "supported", "parser": "pymupdf"},
        ".pptx": {"status": "supported", "parser": "python-pptx"},
        ".docx": {"status": "supported", "parser": "python-docx"},
        ".ppt": {"status": "unsupported", "reason": "需先另存为 .pptx"},
        ".doc": {"status": "unsupported", "reason": "需先另存为 .docx"},
        ".zip": {"status": "ignored", "reason": "压缩包不处理"},
    },
}


def load_yaml(name: str) -> dict:
    path = SKILL / "assets" / name
    try:
        import yaml  # noqa: WPS433
    except Exception:
        yaml = None
    if yaml is not None and path.exists():
        with io.open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return _BUILTIN_TAXONOMY if name == "taxonomy.yaml" else _BUILTIN_FORMATS


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------


def sha1_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def norm_text(text: str) -> str:
    """归一化正文以防止伪差异（空白、全半角）。用于重复识别。"""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text).lower()


def file_mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def rel_posix(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def log_error(msg: str) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with io.open(ERROR_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t{msg}\n")

# ---------------------------------------------------------------------------
# 兼容导出：命名域与索引域拆到独立模块，但保留 common.X 的调用方式
# ---------------------------------------------------------------------------
from naming import (  # noqa: E402,F401
    DATE_FULL, DATE_MONTH, DATE_YEAR_PAREN, nfkc, date_from_text, date_line_of,
    date_from_filename, date_from_meta, year_of, subject_from_filename,
    full_names_from_text, subject_core, subject_key, merge_entity_keys,
    classify_topic, doc_type_of, round_of, version_of, status_of,
    build_relative_md_path, depth_ok, sanitize_component, dedup,
)
from index_io import (  # noqa: E402,F401
    read_index, write_index, write_view, load_overrides,
)
from frontmatter import FM_ORDER, render_frontmatter  # noqa: E402,F401

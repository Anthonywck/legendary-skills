# -*- coding: utf-8 -*-
"""多格式正文抽取（格式注册表驱动）。

对外只有一个入口：extract(path) -> ExtractResult
结果中的 quality 字段是本 Skill 的异常兜底核心：
    ok / empty / needs_ocr / corrupt / encrypted / unsupported / too_large

用法（调试单文件）：
    python extract.py <file> [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from common import load_yaml, norm_text, sha1_text
from ocr_backend import ocr_pdf_pages
from parsers import (PARSERS, _pages_markdown, _parse_docx, _parse_image, _parse_legacy,
                     _parse_markdown, _parse_pdf, _parse_pptx, _pdf_has_images,
                     _try_pymupdf4llm)

MAX_BYTES = 512 * 1024 * 1024     # 超过则不解析，登记 too_large
MAX_CHARS = 4_000_000             # 正文上限，超出截断并标记
MIN_TEXT_CHARS = 50               # 低于此值判 needs_ocr / empty
USE_LLM_MARKDOWN = os.environ.get("FDS_LLM_MARKDOWN", "0") == "1"
TEXT_COVERAGE_MIN = 0.30          # 有文本层的页占比低于此值判 needs_ocr

# OCR 开关：**默认关闭**，采用两阶段流程。
#   阶段一（sync.py）：快速抽取，扫描件只标 needs_ocr —— 全量可在分钟级跑完
#   阶段二（run_ocr.py）：单独对 needs_ocr 的文件补 OCR，可分批、可断点续跑
# 设 FDS_OCR=1 可让单次 sync 直接内联 OCR（小批量时更省一步）。
@dataclass
class ExtractResult:
    path: str
    ext: str
    status: str                       # ok | empty | needs_ocr | corrupt | encrypted | unsupported | too_large
    parser: str
    text: str = ""
    markdown: str = ""
    pages: int = 0
    meta: dict = field(default_factory=dict)
    first_page_text: str = ""
    warnings: list[str] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    @property
    def text_sha1(self) -> str:
        return sha1_text(norm_text(self.text)) if self.text else ""

    def as_dict(self, with_text: bool = False) -> dict:
        d = {
            "path": self.path, "ext": self.ext, "status": self.status, "parser": self.parser,
            "pages": self.pages, "meta": self.meta, "first_page_text": self.first_page_text,
            "warnings": self.warnings, "notes": self.notes,
            "chars": len(self.text), "text_sha1": self.text_sha1,
        }
        if with_text:
            d["text"] = self.text
            d["markdown"] = self.markdown
        return d


def _registry() -> dict:
    return load_yaml("formats.yaml")


def usable_text(res: ExtractResult) -> str:
    """只有可信正文才参与元数据抽取；乱码/扫描失败件的正文一律不喂给抽取器。

    放在 extract 层是因为它判定的正是「抽取结果能不能用」这件事，
    facts / build_frontmatter 都从这里取，避免各自实现一份。
    """
    return res.text if res.status == "ok" else ""


def _entry(ext: str, reg: dict) -> dict:
    return (reg.get("formats") or {}).get(ext.lower()) or (reg.get("default") or {})


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def extract(path: str | Path) -> ExtractResult:
    p = Path(path)
    ext = p.suffix.lower()
    reg = _registry()
    entry = _entry(ext, reg)
    status = entry.get("status", "unsupported")
    res = ExtractResult(path=str(p), ext=ext, status="", parser=entry.get("parser", "none"))

    if status == "ignored":
        res.status = "unsupported"
        res.warnings.append(f"格式 {ext} 被显式忽略: {entry.get('reason', '')}")
        return res
    if status == "unsupported" or ext not in (reg.get("formats") or {}):
        res.status = "unsupported"
        res.warnings.append(entry.get("reason") or f"格式 {ext} 未登记")
        if entry.get("remedy"):
            res.notes["remedy"] = entry["remedy"]
        return res

    parser = PARSERS.get(entry.get("parser", ""))
    if parser is None:
        res.status = "unsupported"
        res.warnings.append(f"解析器 {entry.get('parser')} 未实现")
        return res

    try:
        size = p.stat().st_size
    except OSError as exc:
        res.status, res.warnings = "corrupt", [f"无法读取文件属性: {exc}"]
        return res
    if size == 0:
        res.status, res.warnings = "corrupt", ["文件大小为 0，判定为损坏"]
        return res
    if size > MAX_BYTES:
        res.status, res.warnings = "too_large", [f"文件 {size/1048576:.0f} MB 超过上限，未解析"]
        return res

    try:
        res = parser(p, res)
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        if "password" in msg.lower() or "encrypt" in msg.lower():
            res.status = "encrypted"
        elif isinstance(exc, ImportError):
            res.status = "unsupported"
        else:
            res.status = "corrupt"
        res.warnings.append(f"解析异常: {msg}")
        return res

    if len(res.text) > MAX_CHARS:
        res.text = res.text[:MAX_CHARS]
        res.warnings.append(f"正文超过 {MAX_CHARS} 字符，已截断")
    res.text = _clean(res.text)
    res.markdown = _clean(res.markdown)

    # 乱码检测：字体缺 ToUnicode 映射时，PyMuPDF 会抽出西里尔/亚美尼亚等码位。
    # 这类文本不可检索，必须显式降级，不能当作正常正文使用。
    if res.status == "ok":
        ratio = cjk_ratio(res.text)
        res.notes["cjk_ratio"] = round(ratio, 3)
        if pymupdf_garble_ratio(res.text) >= GARBLE_MAX:
            res.status = "encoding_error"
            res.warnings.append(
                f"抽取文本中非正文语言字符占比 {pymupdf_garble_ratio(res.text):.0%}"
                f"（CJK 仅 {ratio:.0%}）：字体缺少 ToUnicode 映射，判定为编码异常，正文不可用"
            )
        elif ratio < CJK_MIN_RATIO:
            res.warnings.append(f"中文占比偏低（{ratio:.0%}），可能是外文文档")
    return res


_GARBLE_RANGES = (
    (0x0400, 0x04FF),   # 西里尔
    (0x0530, 0x058F),   # 亚美尼亚
    (0x10A0, 0x10FF),   # 格鲁吉亚
    (0x0E00, 0x0E7F),   # 泰文
    (0x0900, 0x097F),   # 天城文
    (0x0B80, 0x0BFF),   # 泰米尔
    (0x0A80, 0x0AFF),   # 古吉拉特
)


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or (0x3000 <= o <= 0x303F)


def cjk_ratio(text: str) -> float:
    letters = [c for c in text if not c.isspace() and not c.isdigit()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _is_cjk(c)) / len(letters)


def pymupdf_garble_ratio(text: str) -> float:
    """非中文、非 ASCII 的「异域脚本」字符占比。中文正规文档应接近 0。"""
    letters = [c for c in text if not c.isspace() and not c.isdigit()]
    if not letters:
        return 0.0
    bad = 0
    for c in letters:
        if ord(c) < 128 or _is_cjk(c):
            continue
        if any(lo <= ord(c) <= hi for lo, hi in _GARBLE_RANGES):
            bad += 1
    return bad / len(letters)


GARBLE_MAX = 0.15      # 异域脚本字符占比超过此值 → encoding_error
CJK_MIN_RATIO = 0.15   # 中文占比低于此值 → 提示可能为外文文档（仅告警）


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str) -> str:
    text = _CTRL.sub("", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{4,}", "\n\n\n", text).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="抽取单个文件正文")
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--text", action="store_true", help="打印正文")
    args = ap.parse_args()
    res = extract(args.file)
    if args.text:
        print(res.text)
        return 0
    print(json.dumps(res.as_dict(with_text=args.json), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

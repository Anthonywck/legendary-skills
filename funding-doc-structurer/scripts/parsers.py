# -*- coding: utf-8 -*-
"""各格式的解析器实现：把文件变成 ExtractResult 的 text / markdown。

本模块只关心「怎么把内容读出来」；质量判定（coverage / 乱码 / needs_ocr）
留在 extract.py，二者刻意分开，便于单独测试某个格式。
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

from ocr_backend import ocr_image, ocr_pdf_pages
from parsers_data import (_decode_text, _md_cell, _parse_csv, _parse_markdown,
                          _parse_text, _parse_xlsx, _rows_to_markdown,
                          _text_result)

MIN_TEXT_CHARS = 50
TEXT_COVERAGE_MIN = 0.30
def ocr_enabled() -> bool:
    """在调用时读取，而不是模块导入时固化。

    两阶段流程里 run_ocr.py 会先设置 FDS_OCR=1 再调用 extract；
    若常量在 import 时求值，setenv 就永远不生效。
    """
    return os.environ.get("FDS_OCR", "0") == "1"
USE_LLM_MARKDOWN = os.environ.get("FDS_LLM_MARKDOWN", "0") == "1"

# 解析器需要 ExtractResult 上的字段，为避免循环导入，只做类型提示用途的延迟导入
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # pragma: no cover
    from extract import ExtractResult

# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------


def _parse_pdf(path: Path, res: ExtractResult) -> ExtractResult:
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        if doc.needs_pass:
            res.status, res.warnings = "encrypted", res.warnings + ["PDF 需要密码，未解析"]
            return res
        res.meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        res.pages = doc.page_count
        chunks: list[str] = []
        empty_idx: list[int] = []
        for i, page in enumerate(doc):
            t = page.get_text().strip()
            if not t:
                empty_idx.append(i)
            chunks.append(t)
            if i == 0:
                res.first_page_text = t
    finally:
        doc.close()

    # 扫描件常带一页水印/封底文字，总字数会骗过「非空」判断，因此以页覆盖率为主判据。
    with_text = res.pages - len(empty_idx)
    coverage = with_text / res.pages if res.pages else 0
    res.notes["pages_with_text"] = with_text
    res.notes["text_coverage"] = round(coverage, 3)

    # OCR 补全：只对「无文本层」的页做，不重跑已有文本的页。
    if empty_idx and ocr_enabled() and (coverage < TEXT_COVERAGE_MIN or not res.text.strip()):
        res.notes["ocr_pages"] = len(empty_idx)
        ocr_text, warns = ocr_pdf_pages(path, empty_idx)
        res.warnings.extend(warns)
        if ocr_text:
            for i, t in ocr_text.items():
                chunks[i] = f"[OCR] {t}"
            res.notes["ocr_filled"] = len(ocr_text)
            with_text = sum(1 for c in chunks if c.strip())
            coverage = with_text / res.pages if res.pages else 0
            res.notes["pages_with_text"] = with_text
            res.notes["text_coverage"] = round(coverage, 3)
            res.notes["ocr_applied"] = True
            res.warnings.append(
                f"已对 {len(ocr_text)} 页做过 OCR（引擎 RapidOCR），OCR 文本可能有个别识别误差"
            )
        else:
            res.notes["ocr_applied"] = False

    res.text = "\n\n".join(chunks)
    res.first_page_text = res.first_page_text or (chunks[0] if chunks else "")
    # 默认用 PyMuPDF 纯文本按页拼装：确定性高、无隐式 OCR。
    res.markdown = _try_pymupdf4llm(path, res) if USE_LLM_MARKDOWN else _pages_markdown(chunks)

    if not res.text.strip():
        images = _pdf_has_images(path)
        if images:
            res.status = "needs_ocr"
            res.warnings.append(f"文本层为空且 OCR 未取得内容，检测到 {images} 张图像")
        else:
            res.status = "empty"
            res.warnings.append("文本层为空且无图像，判定为空文档")
        return res

    if coverage < TEXT_COVERAGE_MIN:
        res.status = "needs_ocr"
        res.warnings.append(
            f"仅 {with_text}/{res.pages} 页有可用文本（覆盖率 {coverage:.0%} < "
            f"{TEXT_COVERAGE_MIN:.0%}）；OCR 未启用或无有效结果"
        )
    elif len(res.text.strip()) < MIN_TEXT_CHARS:
        res.status = "empty"
        res.warnings.append(f"可抽取文本仅 {len(res.text.strip())} 字")
    else:
        res.status = "ok"
    if empty_idx and coverage >= TEXT_COVERAGE_MIN and not res.notes.get("ocr_applied"):
        res.warnings.append(f"{len(empty_idx)}/{res.pages} 页无文本层")
    return res


def _pdf_has_images(path: Path) -> int:
    try:
        import pymupdf
        with pymupdf.open(str(path)) as doc:
            return sum(len(p.get_images(full=True)) for p in doc)
    except Exception:  # noqa: BLE001
        return 0


def _pages_markdown(chunks: list[str]) -> str:
    out = []
    for i, t in enumerate(chunks, 1):
        if not t:
            continue
        out.extend([f"### 第 {i} 页", "", t, ""])
    return "\n".join(out)


def _try_pymupdf4llm(path: Path, res: ExtractResult) -> str:
    try:
        import pymupdf4llm
        md = pymupdf4llm.to_markdown(str(path), show_progress=False)
        return md or ""
    except ImportError:
        res.notes["markdown"] = "pymupdf4llm 未安装，正文降级为纯文本"
        return ""
    except Exception as exc:  # noqa: BLE001
        res.warnings.append(f"pymupdf4llm 转换失败，降级为纯文本: {exc}")
        return ""


def _parse_pptx(path: Path, res: ExtractResult) -> ExtractResult:
    from pptx import Presentation

    # 传 BytesIO 而不是路径：python-pptx 会保留底层 zip 句柄，导致源文件被占用，
    # 在 Windows 上会让后续改名/删除失败（并违反「原件只读、可随时被外部移动」的约定）。
    import io as _io
    prs = Presentation(_io.BytesIO(path.read_bytes()))
    slides = list(prs.slides)
    res.pages = len(slides)
    md_parts: list[str] = []
    text_parts: list[str] = []
    for idx, slide in enumerate(slides, 1):
        lines = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                t = shape.text_frame.text.strip()
                if t:
                    lines.append(t)
            if getattr(shape, "has_table", False):
                try:
                    for row in shape.table.rows:
                        lines.append(" | ".join(c.text.strip() for c in row.cells))
                except Exception:  # noqa: BLE001
                    pass
        if slide.has_notes_slide:
            note = slide.notes_slide.notes_text_frame.text.strip()
            if note:
                lines.append(f"[备注] {note}")
        block = "\n".join(lines).strip()
        text_parts.append(block)
        if block:
            first = block.splitlines()[0]
            md_parts.extend([f"## 第 {idx} 页：{first}", "", block, ""])
    res.text = "\n\n".join(p for p in text_parts if p)
    res.markdown = "\n".join(md_parts)
    res.first_page_text = text_parts[0] if text_parts else ""
    core = (prs.core_properties if hasattr(prs, "core_properties") else None)
    if core is not None:
        res.meta = {
            "title": core.title or "", "author": core.author or "",
            "created": str(core.created) if core.created else "",
            "modified": str(core.modified) if core.modified else "",
        }
        res.meta = {k: v for k, v in res.meta.items() if v}
    res.status = "ok" if len(res.text.strip()) >= MIN_TEXT_CHARS else "empty"
    if res.status != "ok":
        res.warnings.append("PPTX 文本为空或过短（可能内容全为图片）")
    return res


def _parse_docx(path: Path, res: ExtractResult) -> ExtractResult:
    import docx

    import io as _io
    d = docx.Document(_io.BytesIO(path.read_bytes()))   # 同上：不占用源文件句柄
    parts: list[str] = []
    for p in d.paragraphs:
        t = p.text.strip()
        if t:
            # 第三方生成的 docx 常缺 w:pStyle，p.style 可能为 None，必须防空
            style_obj = getattr(p, "style", None)
            style = (getattr(style_obj, "name", None) or "").lower()
            if style.startswith("heading"):
                parts.append(f"## {t}")
            else:
                parts.append(t)
    for ti, table in enumerate(d.tables, 1):
        rows = []
        for row in table.rows:
            rows.append(" | ".join(c.text.strip() for c in row.cells))
        if rows:
            parts.append(f"\n### 表格 {ti}\n" + "\n".join(rows))
    res.text = "\n".join(parts)
    res.markdown = res.text
    res.first_page_text = res.text[:500]
    res.pages = 0
    cp = d.core_properties
    res.meta = {k: str(getattr(cp, k)) for k in ("author", "created", "modified", "title")
                if getattr(cp, k, None)}
    res.status = "ok" if len(res.text.strip()) >= MIN_TEXT_CHARS else "empty"
    return res


def _parse_image(path: Path, res: ExtractResult) -> ExtractResult:
    """图片：无文本层可抽，直接走 OCR。"""
    res.pages = 1
    res.meta = {}
    if not ocr_enabled():
        res.status = "needs_ocr"
        res.warnings.append("图片需 OCR；阶段一不处理，运行 run_ocr.py 补齐")
        return res
    if path.stat().st_size > 50 * 1024 * 1024:
        res.status = "too_large"
        res.warnings.append("图片超过 50 MB，未做 OCR")
        return res
    text, err = ocr_image(path)
    if err:
        res.status = "needs_ocr"
        res.warnings.append(err)
        return res
    res.text = text
    res.markdown = text
    res.first_page_text = text[:500]
    res.notes["ocr_applied"] = True
    if len(text.strip()) < MIN_TEXT_CHARS:
        res.status = "empty"
        res.warnings.append("OCR 未识别出足够文字（可能是纯图形/图标）")
    else:
        res.status = "ok"
        res.warnings.append("文本由 OCR 识别，可能有个别误差")
    return res


def _parse_legacy(path: Path, res: ExtractResult) -> ExtractResult:
    """`.doc` / `.ppt`：纯 Python 解析，不依赖 LibreOffice。"""
    from legacy_office import extract_legacy

    text, err = extract_legacy(path, res.ext)
    if err:
        res.warnings.append(err)
        remedy = {" .doc": "soffice --headless --convert-to docx", ".doc": "soffice --headless --convert-to docx",
                  ".ppt": "soffice --headless --convert-to pptx"}
        res.notes["remedy"] = remedy.get(res.ext, "")
        # 解析失败不等于「没有文字」：仍可能被 OCR 救回来（旧版 PPT 常见整页截图）
        res.status = "unsupported"
        return res
    res.text = text
    res.markdown = text
    res.first_page_text = text[:500]
    res.pages = 0
    if res.ext == ".ppt":
        res.pages = max(1, text.count("\n") // 6)
    res.status = "ok" if len(text.strip()) >= MIN_TEXT_CHARS else "empty"
    if res.status == "ok":
        res.warnings.append("旧版二进制格式，已用纯 Python 解析，复杂版式可能丢失")
    return res


PARSERS = {
    "pymupdf": _parse_pdf,
    "python-pptx": _parse_pptx,
    "python-docx": _parse_docx,
    "image-ocr": _parse_image,
    "plain-text": _parse_text,
    "markdown": _parse_markdown,
    "csv": _parse_csv,
    "xlsx": _parse_xlsx,
    "legacy-office": _parse_legacy,
}



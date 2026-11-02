# -*- coding: utf-8 -*-
"""OCR 后端：可插拔，默认 RapidOCR（纯 onnxruntime，无需系统级依赖）。

设计约束：
- 引擎**懒加载**：不用 OCR 的运行不为它付启动代价（约 1.3 秒）
- 单例：同一进程多文件复用同一个模型实例
- 失败即降级：OCR 不可用时返回 None 并附原因，调用方据此标记 needs_ocr，
  绝不让 OCR 故障中断批次
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# RapidOCR 默认把 INFO 日志打到 stdout，会污染 CLI 的 JSON 输出，
# 也会混进正文抓取的日志流。这里统一降到 WARNING，并确保有 handler。
logging.getLogger("RapidOCR").setLevel(logging.WARNING)
logging.getLogger("rapidocr").setLevel(logging.WARNING)

_ENGINE = None
_ENGINE_ERR: str | None = None
_TRIED = False

# 单页 OCR 分辨率。150 对正文够用；扫描件表格/小字可调到 200，代价约翻倍
DPI = int(os.environ.get("FDS_OCR_DPI", "150"))
# 总 OCR 页数上限：防止一份 300 页扫描件把批次拖死
MAX_PAGES = int(os.environ.get("FDS_OCR_MAX_PAGES", "60"))


def available() -> tuple[bool, str]:
    """探测 OCR 是否可用，返回 (可用, 原因)。结果缓存。"""
    global _ENGINE, _ENGINE_ERR, _TRIED
    if _TRIED:
        return (_ENGINE is not None), (_ENGINE_ERR or "")
    _TRIED = True
    try:
        import contextlib
        import sys
        from rapidocr import RapidOCR  # noqa: WPS433

        # RapidOCR 初始化时会往 stdout 打版本/模型路径；CLI 的 JSON 输出不能被污染
        with contextlib.redirect_stdout(sys.stderr):
            _ENGINE = RapidOCR()
    except Exception as exc:  # noqa: BLE001
        _ENGINE = None
        _ENGINE_ERR = f"{type(exc).__name__}: {exc}"
    return (_ENGINE is not None), (_ENGINE_ERR or "")


def _texts(result) -> list[str]:
    """兼容不同版本的返回结构：RapidOCR 2.x 返回带 .txts 的对象或 (boxes, txts, scores)。"""
    if result is None:
        return []
    txts = getattr(result, "txts", None)
    if txts is None and isinstance(result, (tuple, list)) and len(result) >= 2:
        txts = result[1]
    if txts is None and hasattr(result, "to_dict"):
        txts = (result.to_dict() or {}).get("txts")
    return [str(t).strip() for t in (txts or []) if str(t).strip()]


def ocr_image(path: str | Path) -> tuple[str, str]:
    """对单张图片做 OCR，返回 (文本, 错误)。"""
    ok, reason = available()
    if not ok:
        return "", f"OCR 引擎不可用: {reason}"
    try:
        res = _ENGINE(str(path))  # type: ignore[union-attr]
        return "\n".join(_texts(res)), ""
    except Exception as exc:  # noqa: BLE001
        return "", f"OCR 失败: {type(exc).__name__}: {exc}"


def ocr_pdf_pages(path: Path, page_indexes: list[int]) -> tuple[dict[int, str], list[str]]:
    """对 PDF 的指定页（0-based）做 OCR，返回 ({页号: 文本}, 告警)。"""
    ok, reason = available()
    if not ok:
        return {}, [f"OCR 引擎不可用，跳过: {reason}"]
    try:
        import pymupdf  # noqa: WPS433
    except ImportError:
        return {}, ["pymupdf 不可用，无法渲染 PDF 页面"]

    out: dict[int, str] = {}
    warns: list[str] = []
    todo = page_indexes[:MAX_PAGES]
    if len(page_indexes) > MAX_PAGES:
        warns.append(
            f"仅 OCR 前 {MAX_PAGES} 页（共 {len(page_indexes)} 页无文本层），"
            f"其余保持空白；可用 FDS_OCR_MAX_PAGES 调整"
        )
    doc = pymupdf.open(str(path))
    try:
        for i in todo:
            try:
                pix = doc[i].get_pixmap(dpi=DPI)
                png = pix.tobytes("png")
                import contextlib
                import sys
                with contextlib.redirect_stdout(sys.stderr):
                    res = _ENGINE(png)  # type: ignore[union-attr]
                txt = "\n".join(_texts(res))
                if txt.strip():
                    out[i] = txt.strip()
            except Exception as exc:  # noqa: BLE001
                warns.append(f"第 {i + 1} 页 OCR 失败: {type(exc).__name__}: {exc}")
    finally:
        doc.close()
    return out, warns

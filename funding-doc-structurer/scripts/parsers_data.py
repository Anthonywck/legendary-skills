# -*- coding: utf-8 -*-
"""纯文本与表格类解析器：.txt / .log / .md / .csv / .tsv / .xlsx。

与 parsers.py 分开的原因：这一组共享「解码 → 结构化 → 转 Markdown 表格」的
同一套逻辑，和 PDF/Office 那组依赖重型库的解析器没有交集，放一起会让
单文件超长且职责混杂。
"""

from __future__ import annotations

import re
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # pragma: no cover
    from extract import ExtractResult

MIN_TEXT_CHARS = 50


def _decode_text(raw: bytes) -> tuple[str, str]:
    """把字节解成文本，返回 (文本, 采用的编码)。失败返回 ("", "")。

    顺序有讲究：带 BOM 的优先（最确定），其次 UTF-8（现代文件主流），
    最后 GB18030（覆盖 GBK/GB2312，是中文老文件的常见编码，且是 GBK 的超集）。
    不用 chardet 之类启发式探测：同一份文件两次探测可能给出不同结论，破坏幂等。
    """
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return "", ""


def _text_result(text: str, res: ExtractResult, *, kind: str) -> ExtractResult:
    """`.txt` / `.md` 这类纯文本共用的收尾逻辑。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    res.text = text
    res.markdown = text
    res.first_page_text = text[:500]
    res.pages = 0
    res.notes["lines"] = text.count("\n") + (1 if text else 0)
    res.status = "ok" if len(text.strip()) >= MIN_TEXT_CHARS else "empty"
    if res.status != "ok":
        res.warnings.append(f"{kind} 正文过短（{len(text.strip())} 字），可能是空文件或占位文件")
    return res


def _parse_text(path: Path, res: ExtractResult) -> ExtractResult:
    """.txt：纯文本。无结构信息，全部作为正文。"""
    raw = path.read_bytes()
    text, enc = _decode_text(raw)
    if not text and raw:
        res.status = "encoding_error"
        res.warnings.append("无法以 UTF-8 / GB18030 解码，非纯文本或已损坏")
        return res
    res.notes["encoding"] = enc
    if enc != "utf-8-sig" and enc != "utf-8":
        res.warnings.append(f"按 {enc} 解码；若出现乱码，源文件可能是其它编码")
    return _text_result(text, res, kind="TXT")


def _parse_markdown(path: Path, res: ExtractResult) -> ExtractResult:
    """.md：本身就是结构化的，原样作为正文；同时抽出标题层级。"""
    raw = path.read_bytes()
    text, enc = _decode_text(raw)
    if not text and raw:
        res.status = "encoding_error"
        res.warnings.append("无法以 UTF-8 / GB18030 解码")
        return res
    res.notes["encoding"] = enc

    text = text.replace("\r\n", "\n")
    res.text = text
    res.markdown = text
    res.first_page_text = text[:500]
    res.pages = 0
    heads = re.findall(r"^#{1,6}\s+(.+)$", text, re.M)
    res.notes["headings"] = len(heads)
    if heads:
        res.meta = {"title": heads[0].strip()}
    res.status = "ok" if len(text.strip()) >= MIN_TEXT_CHARS else "empty"
    return res


def _md_cell(v) -> str:
    """把单元格值转成可放进 Markdown 表格的字符串。

    竖线要转义，否则会把表格结构冲散；换行改成空格，保持一行一记录。
    """
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).replace("\r", " ").replace("\n", " ").strip()
    return s.replace("|", "\\|")


def _rows_to_markdown(rows: list[list], *, max_rows: int, max_cols: int,
                      res: ExtractResult, label: str) -> list[str]:
    """把二维表转成 Markdown。首行作表头；列过宽或行过多时截断并记录。"""
    rows = [r for r in rows if any(_md_cell(c) for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    if width > max_cols:
        res.warnings.append(f"{label} 有 {width} 列，仅保留前 {max_cols} 列")
        width = max_cols
    truncated = len(rows) > max_rows + 1
    if truncated:
        res.warnings.append(f"{label} 共 {len(rows)} 行，仅保留前 {max_rows + 1} 行")
        rows = rows[:max_rows + 1]

    header = [_md_cell(c) for c in rows[0]] + [""] * (width - len(rows[0]))
    header = [h or f"列{i + 1}" for i, h in enumerate(header)]
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows[1:]:
        cells = [_md_cell(c) for c in r] + [""] * (width - len(r))
        out.append("| " + " | ".join(cells) + " |")
    return out


def _parse_csv(path: Path, res: ExtractResult) -> ExtractResult:
    """.csv：识别分隔符与编码，转成 Markdown 表格，便于 grep 与阅读。"""
    import csv as _csv

    raw = path.read_bytes()
    text, enc = _decode_text(raw)
    if not text and raw:
        res.status = "encoding_error"
        res.warnings.append("无法以 UTF-8 / GB18030 解码，非纯文本或已损坏")
        return res
    res.notes["encoding"] = enc

    sample = text[:8192]
    try:
        dialect = _csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except _csv.Error:
        delim = ","
        res.warnings.append("未能识别分隔符，按逗号处理")
    res.notes["delimiter"] = {"\t": "tab"}.get(delim, delim)

    rows = list(_csv.reader(text.splitlines(), delimiter=delim))
    res.notes["rows"] = len(rows)
    if rows and len(rows[0]) == 1 and len(rows) > 3:
        res.warnings.append("只识别出单列，分隔符可能判断有误")

    table = _rows_to_markdown(rows, max_rows=2000, max_cols=40, res=res, label="CSV")
    header = [ _md_cell(c) for c in (rows[0] if rows else [])]
    res.text = "\n".join(" | ".join(_md_cell(c) for c in r) for r in rows)
    res.markdown = "\n".join(table)
    res.first_page_text = " | ".join(header[:8])
    res.pages = 0
    # 表格的判据是「有没有数据」，不是字数：一行三列的对照表只有 48 字，但信息完整。
    # 沿用正文 50 字阈值会把它误判成 empty。
    res.status = "ok" if rows and any(_md_cell(c) for c in rows[0]) else "empty"
    if res.status != "ok":
        res.warnings.append("CSV 无有效数据行")
    return res


def _parse_xlsx(path: Path, res: ExtractResult) -> ExtractResult:
    """.xlsx：逐工作表转 Markdown 表格。公式取计算结果，不取公式文本。"""
    import io as _io
    import openpyxl

    wb = openpyxl.load_workbook(_io.BytesIO(path.read_bytes()), read_only=True,
                                data_only=True)
    try:
        parts: list[str] = []
        plain: list[str] = []
        total_rows = 0
        sheets = wb.worksheets
        res.pages = len(sheets)
        for ws in sheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append(list(row))
                if len(rows) > 2002:      # 读到这里已经足够，后续只影响截断提示
                    break
            rows = [r for r in rows if any(_md_cell(c) for c in r)]
            total_rows += len(rows)
            if not rows:
                continue
            title = f"### 工作表：{ws.title}"
            table = _rows_to_markdown(rows, max_rows=2000, max_cols=40, res=res,
                                      label=f"工作表「{ws.title}」")
            if not table:
                continue
            parts.extend([title, ""] + table + [""])
            plain.extend(" | ".join(_md_cell(c) for c in r) for r in rows)
        res.notes["sheets"] = [ws.title for ws in sheets]
        res.notes["rows"] = total_rows
        res.text = "\n".join(plain)
        res.markdown = "\n".join(parts)
        res.first_page_text = (sheets[0].title if sheets else "")
        if len(sheets) == 1:
            first = plain[0] if plain else ""
            res.first_page_text = first[:500]
        # 同 CSV：判据是「有没有数据单元格」，不是字数
        if total_rows == 0:
            res.status = "empty"
            res.warnings.append("所有工作表均为空（或只含空单元格）")
        else:
            res.status = "ok"
    finally:
        wb.close()
    return res



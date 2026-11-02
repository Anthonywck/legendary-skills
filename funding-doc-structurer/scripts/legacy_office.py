# -*- coding: utf-8 -*-
"""旧版二进制 Office 格式的纯 Python 解析（.doc / .ppt）。

为什么不用 LibreOffice：目标环境是「内网 + 无管理员」，装不了。
为什么不用 antiword：它是 Git for Windows 顺带装的，不能假设业务机器上有。

策略：
- `.doc`：OLE 复合文档 → `WordDocument` 流 → 按 FIB 定位文本片段（piece table）
- `.ppt`：OLE 复合文档 → `PowerPoint Document` 流 → 扫描 TextCharsAtom / TextBytesAtom

两者都是「尽力而为」：成功则返回文本，失败返回明确错误，由调用方降级。
解析不了就明确报 unsupported 并给出可执行的补救命令——不静默跳过。
"""

from __future__ import annotations

import struct
from pathlib import Path


# ---------------------------------------------------------------------------
# .doc
# ---------------------------------------------------------------------------

def _extract_doc(path: Path) -> tuple[str, str]:
    """返回 (正文, 错误)。"""
    try:
        import olefile
    except ImportError:
        return "", "缺少 olefile，无法解析 .doc"

    try:
        ole = olefile.OleFileIO(str(path))
    except Exception as exc:  # noqa: BLE001
        return "", f"不是合法的 OLE 复合文档或已损坏: {type(exc).__name__}: {exc}"

    try:
        if not ole.exists("WordDocument"):
            return "", "OLE 内无 WordDocument 流，可能不是 Word 文档"
        wd = ole.openstream("WordDocument").read()
        if len(wd) < 0x200:
            return "", "WordDocument 流过短"

        # FIB：wIdent(2) nFib(2) unused(2) lid(2) pnNext(2) flags(2) ...
        wIdent, _nFib = struct.unpack_from("<HH", wd, 0)
        if wIdent != 0xA5EC:
            return "", "FIB 标识不符（非 Word 二进制格式）"
        flags = struct.unpack_from("<H", wd, 0x0A)[0]
        if flags & 0x0100:
            return "", "文档已加密，无法解析"

        table_name = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(table_name):
            table_name = "1Table" if ole.exists("1Table") else "0Table"
        if not ole.exists(table_name):
            return "", "缺少 Table 流，无法定位文本片段"
        table = ole.openstream(table_name).read()

        ccp_text, fc_clx, lcb_clx = _fib_text_info(wd)
        if not lcb_clx:
            # 极老版本没有 piece table：退化为主文档裸文本
            return _doc_fallback(wd, ccp_text), ""

        clx = table[fc_clx:fc_clx + lcb_clx]
        pieces = _parse_piece_table(clx)
        if not pieces:
            return _doc_fallback(wd, ccp_text), "piece table 解析失败，已退化为主文档文本"

        buf: list[str] = []
        for cp_start, cp_end, fc, compressed in pieces:
            n = cp_end - cp_start
            if n <= 0:
                continue
            if compressed:
                raw = wd[fc:fc + n]
                buf.append(raw.decode("cp1252", errors="replace"))
            else:
                raw = wd[fc:fc + n * 2]
                buf.append(raw.decode("utf-16-le", errors="replace"))
        return "".join(buf), ""
    finally:
        try:
            ole.close()
        except Exception:  # noqa: BLE001
            pass


def _fib_text_info(wd: bytes) -> tuple[int, int, int]:
    """从 FIB 读出 (正文字符数, CLX 在 Table 流中的偏移, CLX 长度)。

    Word 97+ 的 FibRgFcLcb97 里，fcClx/lcbClx 位于固定偏移 0x01A2/0x01A6。
    更细的版本会移动它，这里以 97 布局为准，失败时由调用方退化。
    """
    try:
        ccp_text = struct.unpack_from("<I", wd, 0x004C)[0]
        fc_clx = struct.unpack_from("<I", wd, 0x01A2)[0]
        lcb_clx = struct.unpack_from("<I", wd, 0x01A6)[0]
        return ccp_text, fc_clx, lcb_clx
    except struct.error:
        return 0, 0, 0


def _parse_piece_table(clx: bytes) -> list[tuple[int, int, int, bool]]:
    """解析 Clx → [(cp_start, cp_end, fc, compressed)]。

    Clx = *Prc(0x01) + Pcdt(0x02) len(4) PlcPcd
    PlcPcd = aCP[(n+1)×4] + aPcd[n×8]
    """
    i = 0
    while i < len(clx):
        if clx[i] == 0x01:                      # Prc：跳过
            cb = struct.unpack_from("<h", clx, i + 1)[0]
            i += 3 + cb
        elif clx[i] == 0x02:                    # Pcdt
            lcb = struct.unpack_from("<I", clx, i + 1)[0]
            plc = clx[i + 5:i + 5 + lcb]
            return _parse_plcpcd(plc)
        else:
            break
    return []


def _parse_plcpcd(plc: bytes) -> list[tuple[int, int, int, bool]]:
    if len(plc) < 12:
        return []
    n = (len(plc) - 4) // 12                    # 每片：4 字节 CP 差 + 8 字节 PCD
    if n <= 0:
        return []
    cps = [struct.unpack_from("<I", plc, k * 4)[0] for k in range(n + 1)]
    base = (n + 1) * 4
    out = []
    for k in range(n):
        pcd_off = base + k * 8
        fc_raw = struct.unpack_from("<I", plc, pcd_off + 2)[0]
        compressed = bool(fc_raw & 0x40000000)
        fc = fc_raw & 0x3FFFFFFF
        if compressed:
            fc //= 2
        out.append((cps[k], cps[k + 1], fc, compressed))
    return out


def _doc_fallback(wd: bytes, ccp_text: int) -> str:
    """piece table 不可用时的退化：从 0x800 起按 UTF-16 解一段。"""
    start = 0x800
    end = min(len(wd), start + max(ccp_text, 2000) * 2)
    raw = wd[start:end]
    txt = raw.decode("utf-16-le", errors="ignore")
    return "".join(ch for ch in txt if ch.isprintable() or ch in "\n\t")


# ---------------------------------------------------------------------------
# .ppt
# ---------------------------------------------------------------------------

def _extract_ppt(path: Path) -> tuple[str, str]:
    """扫描 PowerPoint Document 流里的文本原子。

    PPT 记录结构：recVer/recInstance(2) recType(2) recLen(4) data
    文本相关类型：TextCharsAtom(0x0FA0, UTF-16LE) / TextBytesAtom(0x0FA8, cp1252)
    """
    try:
        import olefile
    except ImportError:
        return "", "缺少 olefile，无法解析 .ppt"
    try:
        ole = olefile.OleFileIO(str(path))
    except Exception as exc:  # noqa: BLE001
        return "", f"不是合法的 OLE 复合文档或已损坏: {type(exc).__name__}: {exc}"

    try:
        if not ole.exists("PowerPoint Document"):
            return "", "OLE 内无 PowerPoint Document 流，可能不是 PPT"
        data = ole.openstream("PowerPoint Document").read()
    finally:
        try:
            ole.close()
        except Exception:  # noqa: BLE001
            pass

    blocks: list[str] = []
    pos = 0
    size = len(data)
    # 逐个记录线性扫描。真实 PPT 的容器记录嵌套很深，但文本原子本身是平的，
    # 因此直接全量扫 recType 比维护递归栈更稳。
    while pos + 8 <= size:
        rec_ver_inst, rec_type, rec_len = struct.unpack_from("<HHI", data, pos)
        if rec_len > size - pos - 8 or rec_len < 0:
            pos += 1
            continue
        body = data[pos + 8:pos + 8 + rec_len]
        if rec_type == 0x0FA0:                      # TextCharsAtom
            t = body.decode("utf-16-le", errors="ignore")
            if t.strip():
                blocks.append(t)
        elif rec_type == 0x0FA8:                    # TextBytesAtom
            t = body.decode("cp1252", errors="replace")
            if t.strip():
                blocks.append(t)
        pos += 8 + rec_len
    return "\n".join(blocks), ""


# ---------------------------------------------------------------------------
# 对外
# ---------------------------------------------------------------------------

def extract_legacy(path: Path, ext: str) -> tuple[str, str]:
    """返回 (正文, 错误)。ext 为 .doc 或 .ppt。"""
    if ext == ".doc":
        return _extract_doc(path)
    if ext == ".ppt":
        return _extract_ppt(path)
    return "", f"未支持的旧格式: {ext}"

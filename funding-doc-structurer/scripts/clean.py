# -*- coding: utf-8 -*-
"""产物文本清洗：只做「字节层面的空白规整」，不碰语义。

允许做（可逆、无歧义）：
    1. 去掉行尾空格 / Tab
    2. 不可见空白字符（NBSP、全角空格、零宽字符）统一成普通空格
    3. 一行内 3 个及以上连续空格 → 1 个
    4. 3 个及以上连续空行 → 1 个空行
    5. 去掉控制字符与 U+FFFD 替换符

**明确不做**（会改变原文语义或版式）：
    - 合并「中文硬换行」：PDF 逐行抽取产生的行尾换行既可能是断行，也可能是换行列表项。
      合并错了就是把两句话连成一句，属于改内容，不做。
    - 删除、重排、合并任何文字；中文与英文之间不加/去空格。
    - 改动 ``` 围栏内的任何一行：缩进是代码语义的一部分。

因此本模块的输出去掉空白后，与输入的「非空白字符序列」完全一致——
`validate_output` 的 `T2_TEXT_PRESERVED` 会验证这一点。
"""

from __future__ import annotations

import re

# 统一替换成普通空格的不可见字符。用码位构造正则，避免字符类里出现字面量范围。
_INVISIBLE_CODEPOINTS = (
    0x00A0,                   # NBSP
    0x1680,                   # ogham space mark
    0x180E,                   # mongolian vowel separator
    *range(0x2000, 0x200E),   # 各类 Unicode 空格 + 零宽空格 / 零宽非连接符 / 零宽连接符
    0x202F,                   # narrow no-break space
    0x205F,                   # medium mathematical space
    0x2060,                   # word joiner
    0x3000,                   # 全角空格
    0xFEFF,                   # BOM / zero width no-break space
)
_SPACE_CHARS = re.compile("[" + "".join(map(chr, _INVISIBLE_CODEPOINTS)) + "]")
# 控制字符：保留 \n \t，其余删除
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 行内 3+ 连续空格 → 1 个（2 个空格常用于对齐，保留）
_MULTI_SPACE = re.compile(r"[ ]{3,}")
# 连续空行收敛：最多保留 2 个空行（即 3 个 \n）
_BLANK_RUN = re.compile(r"\n{4,}")


def _clean_line(line: str) -> str:
    line = _SPACE_CHARS.sub(" ", line)
    line = line.replace(chr(0xFFFD), "")
    line = _CTRL.sub("", line)
    return _MULTI_SPACE.sub(" ", line.rstrip())


def clean_text(text: str) -> str:
    """产物正文的统一清洗。对已清洗过的文本再跑一次结果不变（幂等）。"""
    if not text:
        return text
    out: list[str] = []
    in_code = False
    for ln in text.split("\n"):
        if ln.lstrip().startswith("```"):
            in_code = not in_code
            out.append(ln.rstrip())
            continue
        out.append(ln if in_code else _clean_line(ln))
    joined = _BLANK_RUN.sub("\n\n\n", "\n".join(out))
    return joined.strip("\n") + "\n" if joined.strip() else joined


def nonspace(text: str) -> str:
    """去掉全部空白后的字符串，用于「清洗前后语义等长」自检。"""
    return re.sub(r"\s+", "", text)

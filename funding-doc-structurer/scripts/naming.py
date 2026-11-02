# -*- coding: utf-8 -*-
"""命名域：日期、主体、赛道、文档类型、轮次版本、路径推导。

全部为纯函数 + 显式配置表；同一输入两次运行结果完全一致。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from common import load_yaml

# ---------------------------------------------------------------------------
# 日期
# ---------------------------------------------------------------------------

# 中文 PDF 常用 CJK 部首字形（⽉ ⽇ ⾃ …）代替常用字，正则必须按「单字类」匹配，
# 否则 2017年5⽉26⽇ 这类写法会漏匹配或错匹配。统一走 NFKC 归一化再匹配。
DATE_FULL = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-./年]\s*(\d{1,2})\s*[-./月]\s*(\d{1,2})\s*日?(?!\d)")
DATE_MONTH = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-./年]\s*(\d{1,2})\s*月(?!\d)")
DATE_YEAR_ONLY = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*(?:年|年度)?(?!\d)")
DATE_YEAR_PAREN = re.compile(r"[（(]((?:19|20)\d{2})[）)]")

# 日期行：整行几乎只有日期，用于排除「2017年5月26日，Veeco 完成收购…」这类正文事实日期
_DATE_LINE_NOISE = re.compile(r"^[\s\-—–·•:：/|年月日\d.,，()（）]+$")


def _valid(y: int, m: int = 1, d: int = 1) -> bool:
    return 1990 <= y <= datetime.now().year + 1 and 1 <= m <= 12 and 1 <= d <= 31


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def date_from_text(text: str) -> tuple[str | None, str | None]:
    """在片段内按 全日期 → 年月 → 括号年份 的精度降级取日期。

    注意：不在本函数里做「是否属于正文事实」的判断，那是调用方的责任
    （见 build_frontmatter._date_zone），否则会把历史事件日期当成文档日期。
    """
    text = nfkc(text)
    m = DATE_FULL.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}", "day"
    m = DATE_MONTH.search(text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if _valid(y, mo):
            return f"{y:04d}-{mo:02d}", "month"
    m = DATE_YEAR_PAREN.search(text)
    if m:
        y = int(m.group(1))
        if _valid(y):
            return f"{y:04d}", "year"
    return None, None


def date_line_of(line: str) -> tuple[str, str] | None:
    """单行落款判定：该行必须以日期为主体，才认作文档日期。

    「2022年5月」→ 接受；「2022年5月，公司完成A轮融资」→ 拒绝（正文事实）。
    """
    s = nfkc(line).strip()
    if not s or len(s) > 24:
        return None
    d, prec = date_from_text(s)
    if not d:
        return None
    residue = re.sub(r"(?:19|20)\d{2}|\d{1,2}|[年月日\-./()（）\s]", "", s)
    if len(residue) > 6:          # 剩余文字过多 → 是叙述句而非落款
        return None
    return d, prec


def date_from_filename(name: str, source_root: str) -> tuple[str | None, str | None]:
    """文件名取日期。行业报告常见 -YYMMDD（N页）；BP 常见 YYYYMMDD / YYYY年。

    先剥离扩展名和「（N页）」页码标记，避免页码被当作数字。
    """
    stem = re.sub(r"\.[^.]+$", "", name)
    stem = re.sub(r"[（(]\s*\d+\s*页\s*[）)]", "", stem)
    stem = re.sub(r"[（(]\s*\d{4}\s*[）)]", lambda m: m.group(0), stem)  # 保留 (2021) 形式

    # 8 位日期 YYYYMMDD
    m = re.search(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)", stem)
    if m and _valid(int(m.group(1)), int(m.group(2)), int(m.group(3))):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "day"

    # 6 位日期 YYMMDD —— 仅当不是 8 位日期的一部分
    for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", stem):
        yy, mo, dd = int(m.group(1)[:2]), int(m.group(1)[2:4]), int(m.group(1)[4:])
        y = 2000 + yy if yy <= 40 else 1900 + yy
        if _valid(y, mo, dd) and 2010 <= y <= datetime.now().year + 1:
            return f"{y:04d}-{mo:02d}-{dd:02d}", "day"

    # 中文年月 / 括号年份
    d, prec = date_from_text(stem)
    if d:
        return d, prec
    return None, None


def date_from_meta(meta: dict) -> tuple[str | None, str | None]:
    for key in ("creationDate", "creation_date", "CreationDate", "created"):
        raw = (meta or {}).get(key)
        if not raw:
            continue
        m = re.search(r"((?:19|20)\d{2})[-:]?(\d{2})?[-:]?(\d{2})?", str(raw).replace("D:", ""))
        if m:
            y = int(m.group(1))
            mo = int(m.group(2)) if m.group(2) else 1
            dd = int(m.group(3)) if m.group(3) else 1
            if _valid(y, mo, dd):
                if m.group(3):
                    return f"{y:04d}-{mo:02d}-{dd:02d}", "day"
                if m.group(2):
                    return f"{y:04d}-{mo:02d}", "month"
                return f"{y:04d}", "year"
    return None, None


def year_of(date: str) -> str:
    m = re.match(r"(\d{4})", date or "")
    return m.group(1) if m else "unknown"


# ---------------------------------------------------------------------------
# 主体 / 赛道 / 文档类型
# ---------------------------------------------------------------------------

_BP_SUFFIX = re.compile(
    r"[-—_ ]*(项目)?(商业计划书|融资计划书|BP|business\s*plan)\s*([（(][^）)]*[）)])?\s*$",
    re.I,
)
_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')
_LEAD_NOISE = re.compile(r"^[【\[].*?[】\]]\s*")


def sanitize_component(s: str, maxlen: int = 40) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = _ILLEGAL.sub("", s)
    s = re.sub(r"\s+", "", s)
    s = s.strip(" .-_")
    if len(s) > maxlen:
        s = s[:maxlen].rstrip(" .-_")
    return s or "unknown"


def subject_from_filename(name: str) -> str:
    """从文件名推企业主体。纯规则，不猜。

    1. 去扩展名、去【】前缀、去「项目商业计划书」类后缀
    2. 取第一段：任何空白 / 连字符 / 冒号 / 下划线 / 斜杠都是主体与产品名的分界
    3. 主体长度上限 20 字：超出说明第一条分界规则失效，宁可截断也不把整句当主体

    之所以把「任意空白」也当分界：真实文件名里既有「深圳烯钻科技 半导体…」，
    也有「鹏城半导体 -高端…」，只按「空格+连字符」切会把前者的产品名并入主体。
    """
    stem = re.sub(r"\.[^.]+$", "", name)
    stem = _LEAD_NOISE.sub("", stem)
    stem = _BP_SUFFIX.sub("", stem)
    stem = re.sub(r"^[\s\-—_]+", "", stem)
    first = re.split(r"[\s\-—–_：:|/、，,]+", stem, maxsplit=1)[0]
    first = re.sub(r"(项目)?商业计划书.*$", "", first).strip(" 　-—_·")
    first = sanitize_component(first, maxlen=20)
    return first or "unknown"


# 左边界必须是「非公司名字符」：句读、空白、行首或非中文。否则会从
# 「……传播科技股份有限公司」这类折行句子里截出「梭科技股份有限公司」这种假全称。
FULLNAME_RE = re.compile(
    r"(?<![一-龥A-Za-z0-9（）()])"
    r"([一-龥A-Za-z0-9（）()]{2,30}?"
    r"(?:股份有限公司|有限责任公司|有限公司))"
)
FULLNAME_BAD_HEAD = re.compile(r"^(?:的|是|为|由|在|与|和|及|称|即|含|于|对|从|到|本|该|其)")


def full_names_from_text(text: str, limit: int = 3) -> list[str]:
    """从正文捞全称。只做抽取，不做推断；按出现顺序去重。"""
    seen: list[str] = []
    for m in FULLNAME_RE.finditer(text[:20000]):
        n = m.group(1)
        n = re.sub(r"^[一二三四五六七八九十\d、.．]+", "", n)
        if len(n) < 6 or FULLNAME_BAD_HEAD.match(n):
            continue
        if n not in seen:
            seen.append(n)
        if len(seen) >= limit:
            break
    return seen


_REGION_PREFIX = re.compile(
    r"^(?:深圳市?|上海市?|北京市?|杭州市?|苏州市?|东莞市?|广州市?|成都市?|南京市?|武汉市?"
    r"|安徽|江苏|浙江|山东|湖南|重庆|福建|广东)"
)


def subject_core(name: str) -> str:
    """主体识别核心：去地区前缀、去公司形式、只留开头的连续中文。

    「森国科SiC」「森国科碳化硅SiC」→ 都收敛到「森国科」开头的中文串。
    """
    s = unicodedata.normalize("NFKC", name or "")
    s = re.sub(r"(股份有限公司|有限责任公司|有限公司|集团)", "", s)
    s = _REGION_PREFIX.sub("", s)
    # 只取开头的连续汉字；「森国科SiC」「森国科碳化硅SiC」都收敛到「森国科」
    m = re.match(r"[一-龥]+", s)
    if not m:
        return ""
    core = m.group(0)
    # 核心本身可能被分界符污染（如从文件名带出的残余），截到第一个非汉字段已由正则保证
    return core


def subject_key(name: str) -> str:
    """实体归一键：去地区前缀噪声、去公司形式、去空白与连接符。"""
    s = unicodedata.normalize("NFKC", name or "")
    s = _REGION_PREFIX.sub("", s)
    s = re.sub(r"(股份有限公司|有限责任公司|有限公司|集团)$", "", s)
    s = re.sub(r"[\s\-—_·（）()]", "", s)
    return s.lower()


# 前缀归并至少共享 3 个中文字：中文公司名核心普遍是 3-4 字（森国科 / 烯钻 / 中熵），
# 4 字阈值会让 3 字主体永远无法归并。2 字以下不归并（「中微」「华大」这类歧义太大）。
CORE_MIN_PREFIX = 3


def merge_entity_keys(keys: list[str], cores: dict[str, str]) -> dict[str, str]:
    """把「中文核心互为前缀且长度均 ≥4」的实体键归并到同一个组。

    这是**确定性**规则（不依赖人工记忆），且只在核心前缀明确重合时触发：
      森国科(sic) 与 森国科碳化硅(sic) → 森国科
    仍然保留 overrides.yaml 的 subject_alias 作为人工纠正通道。
    """
    mapping = {k: k for k in keys}
    ordered = sorted(keys, key=lambda k: (len(cores.get(k, "")), k))
    for k in ordered:
        core = cores.get(k, "")
        if len(core) < CORE_MIN_PREFIX:
            continue
        for other in ordered:
            if other == k:
                continue
            ocore = cores.get(other, "")
            if len(ocore) < CORE_MIN_PREFIX:
                continue
            if not (ocore.startswith(core) or core.startswith(ocore)):
                continue
            # 以较短核心为代表；同长时取字典序小者，保证结果与遍历顺序无关
            if (len(core), core) <= (len(ocore), ocore):
                mapping[other] = mapping[k]
    # 传递闭包：a→b、b→c 时 a 也要指向 c
    for _ in range(len(keys)):
        changed = False
        for k in list(mapping):
            t = mapping[mapping[k]]
            if t != mapping[k]:
                mapping[k] = t
                changed = True
        if not changed:
            break
    return mapping


def classify_topic(name: str, text: str, tax: dict) -> tuple[str, list[str], str]:
    """返回 (topic, tags, reason)。顺序：方括号表 → 关键词规则 → 兜底。"""
    tags: list[str] = []
    m = re.search(r"【(.+?)】", name)
    bracket = m.group(1).strip() if m else None
    bmap = tax.get("bracket_map") or {}
    if bracket and bracket in bmap:
        entry = bmap[bracket]
        tags = list(entry.get("tags") or [])
        tags.append(bracket)
        return entry["topic"], dedup(tags), f"方括号命中: {bracket}"

    hay = f"{name}\n{text[:3000]}"
    for rule in tax.get("keyword_rules") or []:
        for kw in rule.get("any_of") or []:
            if kw and kw.lower() in hay.lower():
                t = list(rule.get("tags") or [])
                t.append(bracket) if bracket else None
                return rule["topic"], dedup(t), f"关键词命中: {kw}"

    if bracket:
        return "其他", dedup([bracket]), f"方括号未登记且无关键词命中: {bracket}"
    return "其他", [], "无赛道信号，落兜底"


def doc_type_of(name: str, source_root: str, tax: dict) -> str:
    """按规则表判定 doc_type。

    规则匹配顺序即优先级；source_root 用「包含」匹配而不是相等，
    这样 `商业计划书`、`商业计划书-2024` 这类目录都能命中同一条规则。
    """
    rules = tax.get("doc_type_rules") or []
    for rule in rules:
        when = rule.get("when") or {}
        root_pat = when.get("source_root")
        if root_pat and root_pat not in (source_root or ""):
            continue
        kws = when.get("name_contains_any")
        if kws and not any(k in name for k in kws):
            continue
        ext = when.get("ext_any")
        if ext and not any(name.lower().endswith(e) for e in ext):
            continue
        return rule["doc_type"]
    return tax.get("default_doc_type", "OTHER")


def dedup(seq: list[str]) -> list[str]:
    out: list[str] = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# 轮次 / 版本 / 状态
# ---------------------------------------------------------------------------

ROUND_RE = re.compile(
    r"(种子轮|天使轮|Pre-?IPO轮?|Pre-?A\+{0,2}轮?|A\+{0,2}轮|B\+{0,2}轮|C\+{0,2}轮|D\+{0,2}轮|E\+{0,2}轮|战略融资|第[一二三四五六七八九十]轮)"
)
VERSION_RE = re.compile(r"(?<![A-Za-z0-9])v(\d+)(?:\.(\d+))?(?![0-9])", re.I)


def round_of(name: str, text: str) -> str | None:
    m = ROUND_RE.search(name)
    if m:
        return _canon_round(m.group(1))
    m = ROUND_RE.search(text[:8000])
    return _canon_round(m.group(1)) if m else None


def _canon_round(s: str) -> str:
    s = s.replace("＋", "+").replace(" ", "")
    if not s.endswith("轮") and s not in ("战略融资",):
        s += "轮"
    return s


def version_of(name: str) -> str:
    m = VERSION_RE.search(name)
    if m:
        major = m.group(1)
        minor = m.group(2) or "0"
        return f"v{major}.{minor}"
    return load_yaml("taxonomy.yaml").get("default_version", "v1.0")


def status_of(name: str) -> str | None:
    if re.search(r"简版|精简版|摘要版", name):
        return "draft"
    if re.search(r"终版|定稿|final", name, re.I):
        return "final"
    if re.search(r"修订|复审|review", name, re.I):
        return "review"
    return None


# ---------------------------------------------------------------------------
# 命名与路径
# ---------------------------------------------------------------------------

def build_relative_md_path(*, topic: str, date: str, doc_type: str, subject: str,
                           version: str, status: str | None) -> str:
    year = year_of(date)
    suffix = f"_{status}" if status else ""
    fname = f"{date}_{doc_type}_{sanitize_component(subject)}_{version}{suffix}.md"
    # 只允许两层目录：by_topic/{topic}/{year}/{doc_type}/ —— 深度 ≤4（by_topic 不计）
    return f"by_topic/{sanitize_component(topic)}/{year}/{doc_type}/{fname}"


def depth_ok(rel_path: str) -> bool:
    parts = rel_path.split("/")
    return len(parts) == 5 or (len(parts) == 4 and parts[0] == "by_topic")



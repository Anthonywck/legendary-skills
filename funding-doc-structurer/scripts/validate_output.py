# -*- coding: utf-8 -*-
"""产物校验：目录/命名/字段/可 grep 性/索引一致性/只读原件。

用法：
    python validate_output.py              # 全量校验，输出报告
    python validate_output.py --strict     # 有 FAIL 时退出码 1
    python validate_output.py --sample     # 只校验索引中 md_status=ok 的样本
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

import common as C
from clean import clean_text, nonspace

# 与 naming.build_relative_md_path 保持一致：
#   日期三段精度 + doc_type 全枚举 + 可选哈希消歧后缀 + 可选状态后缀
NAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{4}|unknown)"
    r"_(?P<doc_type>BP|REPORT|WHITEPAPER|DOC|NOTE|SHEET|OTHER)"
    r"_(?P<subject>[^_]+)"
    r"_(?P<version>v\d+\.\d+)"
    r"(?:_(?P<status>draft|review|final))?"
    r"(?P<disambig>-[0-9a-f]{8,16})?$"
)
SAMPLE_GREP = ["估值", "公司简称", "融资"]


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def add(self, level: str, code: str, msg: str) -> None:
        self.items.append((level, code, msg))

    def fail(self, code: str, msg: str) -> None:
        self.add("FAIL", code, msg)

    def warn(self, code: str, msg: str) -> None:
        self.add("WARN", code, msg)

    def ok(self, code: str, msg: str) -> None:
        self.add("OK", code, msg)

    @property
    def failed(self) -> bool:
        return any(lvl == "FAIL" for lvl, _, _ in self.items)

    def render(self) -> str:
        out = []
        order = {"FAIL": 0, "WARN": 1, "OK": 2}
        for lvl, code, msg in sorted(self.items, key=lambda x: order[x[0]]):
            out.append(f"[{lvl}] {code}: {msg}")
        n_fail = sum(1 for x in self.items if x[0] == "FAIL")
        n_warn = sum(1 for x in self.items if x[0] == "WARN")
        out.append("")
        out.append(f"FAIL {n_fail} / WARN {n_warn} / OK {len(self.items) - n_fail - n_warn}")
        return "\n".join(out)


def parse_frontmatter(text: str) -> dict:
    """只解析本 Skill 写出的单层 frontmatter（列表 / 标量），不引入 yaml 依赖。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[4:end].splitlines()
    data: dict = {}
    cur_list: str | None = None
    for ln in block:
        if not ln.strip():
            continue
        if ln.startswith("  - ") and cur_list:
            data.setdefault(cur_list, []).append(_unquote(ln[4:].strip()))
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", ln)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            data[key] = []
            cur_list = key
        elif val == "[]":
            data[key] = []
            cur_list = None
        elif val.startswith("["):
            data[key] = [_unquote(x.strip()) for x in val.strip("[]").split(",") if x.strip()]
            cur_list = None
        elif val.startswith("|"):
            data[key] = ""
            cur_list = None
        else:
            cur_list = None
            data[key] = _coerce(_unquote(val))
    return data


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        try:
            return json.loads(s) if s[0] == '"' else s[1:-1]
        except Exception:  # noqa: BLE001
            return s[1:-1]
    return s


def _coerce(s: str):
    if s in ("null", "~", ""):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    return s


# ---------------------------------------------------------------------------
# 产物质量：结构完整 + 格式规整
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS = ["## 元数据速查", "## 摘要", "## 正文"]
EVIDENCE_HEADER = "| 字段 | 值 | 原文片段 |"
# 清洗白名单之外仍算「脏」的字符：控制符、替换符、不可见空白
_DIRTY_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f 　​-‍﻿�]")


def _split_product(text: str) -> tuple[str, str]:
    """→ (frontmatter 块, 正文块)。"""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    return (text[:end], text[end:]) if end != -1 else ("", text)


def _check_product(text: str, md: str, fm: dict, rep: Report) -> None:
    head, body = _split_product(text)

    # T1 结构：必需小节齐备且有序
    pos = [body.find(s) for s in REQUIRED_SECTIONS]
    if any(p < 0 for p in pos):
        absent = [s for s, p in zip(REQUIRED_SECTIONS, pos) if p < 0]
        rep.fail("T1_SECTIONS", f"{md} 缺少小节: {', '.join(absent)}")
    elif pos != sorted(pos):
        rep.fail("T1_SECTIONS", f"{md} 小节顺序错乱")
    if "<!-- dedupe:begin -->" not in body or "<!-- dedupe:end -->" not in body:
        rep.fail("T1_DEDUPE", f"{md} 缺少 dedupe 锚点")

    # T2 正文未被清洗改动：非空白字符序列必须与清洗前一致
    cleaned = clean_text(text)
    if nonspace(cleaned) != nonspace(text):
        rep.fail("T2_TEXT_PRESERVED", f"{md} 含清洗器无法安全处理的字符（重跑 sync.py 可修复）")
    elif cleaned != text:
        rep.warn("T2_NOT_CLEAN", f"{md} 存在未清洗的空白，重跑 sync.py 可修复")

    # T3 脏字符（跳过代码块）
    in_code = False
    for ln in body.split("\n"):
        if ln.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        bad = _DIRTY_CHARS.search(ln)
        if bad:
            rep.fail("T3_DIRTY_CHAR", f"{md} 正文含 U+{ord(bad.group(0)):04X} 等不可见/控制字符")
            break

    # T4 证据表：必须是「字段 | 值 | 原文片段」三列，否则无法核对
    if "## 原文证据" in body:
        ev = body[body.find("## 原文证据"):]
        ev = ev[:ev.find("\n## ", 5) if ev.find("\n## ", 5) != -1 else len(ev)]
        if EVIDENCE_HEADER not in ev:
            rep.fail("T4_EVIDENCE", f"{md} 原文证据表不是「字段 | 值 | 原文片段」三列")
        # 证据片段不能是空串占位
        for ln in ev.split("\n"):
            if ln.startswith("| ") and ln.count("|") >= 4:
                cells = [c.strip() for c in ln.strip("|").split("|")]
                if len(cells) >= 2 and not cells[1] and not cells[2]:
                    rep.fail("T5_EVIDENCE_EMPTY", f"{md} 证据条目的值与片段均为空: {ln[:40]}")
                    break

    # T6 引用基准：产物内 duplicate_of / related_docs 必须是产物相对路径
    for key in ("related_docs", "duplicate_of"):
        val = fm.get(key)
        items = val if isinstance(val, list) else ([val] if val else [])
        for it in items:
            if str(it).startswith("datas/"):
                rep.fail("T6_PATH_BASE",
                         f"{md} 的 {key} 用了源文件路径 {it}，应为产物相对路径")
                break

    # T7 摘要不得为空或被截断成单字符
    if len(str(fm.get("summary") or "").strip()) < 8:
        rep.fail("T7_SUMMARY", f"{md} summary 过短或为空")


def check(rows: list[dict], rep: Report, tax: dict) -> None:
    seen_md: dict[str, str] = {}
    checked = [0]
    for r in rows:
        sp, md = r["source_path"], r.get("md_path")
        if not md:
            rep.warn("M0_NO_ARTIFACT", f"{sp} 无产物（{r.get('md_status')}）")
            continue
        p = C.OUT / md
        if not p.exists():
            rep.fail("M1_MISSING_FILE", f"{sp} 的产物不存在: {md}")
            continue
        if md in seen_md:
            rep.fail("M2_PATH_COLLISION", f"{md} 被 {seen_md[md]} 与 {sp} 共用")
        seen_md[md] = sp

        text = io.open(p, encoding="utf-8").read()
        fm = parse_frontmatter(text)
        if not fm:
            rep.fail("M3_NO_FRONTMATTER", f"{md} 无 frontmatter")
            continue

        # 目录与命名
        parts = md.split("/")
        if len(parts) != 5 or parts[0] != "by_topic":
            rep.fail("P1_DEPTH", f"{md} 层级不符 by_topic/{topic}/{year}/{doc_type}/")
            continue
        topic, year, dt, fname = parts[1], parts[2], parts[3], parts[4][:-3]
        if topic != fm.get("topic"):
            rep.fail("P2_TOPIC_DIR", f"{md} 目录 {topic} ≠ frontmatter {fm.get('topic')}")
        if dt != fm.get("doc_type"):
            rep.fail("P3_DOCTYPE_DIR", f"{md} 目录 {dt} ≠ frontmatter {fm.get('doc_type')}")
        date = str(fm.get("date") or "")
        if year != C.year_of(date):
            rep.fail("P4_YEAR_DIR", f"{md} 年份目录 {year} ≠ date {date}")
        m = NAME_RE.match(fname)
        if not m:
            rep.fail("P5_NAME_FORMAT", f"{md} 文件名不符合模板")
        else:
            if m.group("date") != date:
                rep.fail("P6_NAME_DATE", f"{fname} 日期 ≠ frontmatter {date}")
            if m.group("subject") != C.sanitize_component(str(fm.get("subject") or "")):
                rep.fail("P7_NAME_SUBJECT", f"{fname} 主体 ≠ frontmatter {fm.get('subject')}")

        # 字段
        if fm.get("topic") not in (tax.get("topics") or {}):
            rep.fail("F1_TOPIC_CLOSED", f"{md} topic 不在封闭集: {fm.get('topic')}")
        if fm.get("date_source") not in {"doc_text", "filename", "doc_meta", "fs_mtime", "unknown"}:
            rep.fail("F2_DATE_SOURCE", f"{md} date_source 非法: {fm.get('date_source')}")
        if fm.get("date") == "unknown" and fm.get("date_source") != "unknown":
            rep.fail("F3_DATE_PAIR", f"{md} date/date_source 不一致")
        kf = fm.get("key_facts") or []
        # key_facts 为空的合法情形：
        #   DOC/NOTE —— 技术文档与笔记本就没有融资数据
        #   非 ok 抽取状态 —— 正文读不出来，自然没有事实，强行要求会逼出臆造
        status = str(fm.get("extraction_status") or "ok")
        if not kf and fm.get("doc_type") not in ("DOC", "NOTE", "SHEET") and status == "ok":
            rep.fail("F4_KEY_FACTS", f"{md} key_facts 为空（extraction_status=ok）")
        for line in kf:
            if ": " not in line:
                rep.fail("F5_KEY_FACTS_FORMAT", f"{md} key_facts 条目不合法: {line}")
                break

        # 主体三处可 grep
        subj = str(fm.get("subject") or "")
        if subj and subj != "unknown":
            tags = " ".join(map(str, fm.get("tags") or []))
            if subj not in fname:
                rep.fail("G1_SUBJECT_FILENAME", f"{fname} 不含主体 {subj}")
            if subj not in tags:
                rep.fail("G2_SUBJECT_TAGS", f"{md} tags 不含主体 {subj}")
            if subj not in text.split("\n---", 1)[0]:
                rep.fail("G3_SUBJECT_FM", f"{md} frontmatter 无 subject")

        # 产物质量：结构完整 / 空白规整 / 正文未被清洗改动
        _check_product(text, md, fm, rep)

        # 索引一致性（双向可查）
        checked[0] += 1

        if fm.get("source_path") != sp:
            rep.fail("I1_BACKLINK", f"{md} 的 source_path {fm.get('source_path')} ≠ 索引 {sp}")
        if not (C.ROOT / sp).exists() and fm.get("source_available") is True:
            rep.fail("I2_SOURCE_MISSING", f"{sp} 不存在但 source_available=true")

    # 产物总数 vs 目录实况
    actual = set(p.relative_to(C.OUT).as_posix() for p in (C.OUT / "by_topic").rglob("*.md"))
    indexed = {r["md_path"] for r in rows if r.get("md_path")}
    orphan_files = actual - indexed
    if orphan_files:
        rep.warn("I3_UNINDEXED_FILES", f"{len(orphan_files)} 份产物不在索引: "
                 + ", ".join(sorted(orphan_files)[:3]))
    missing_files = indexed - actual
    if missing_files:
        rep.fail("I4_INDEX_DRIFT", f"{len(missing_files)} 条索引指向不存在的产物")

    rep.ok("A0_COVERAGE", f"逐文件校验通过 {checked[0]}/{len(rows)} 份")

    # 索引自身不得进入检索结果
    bad = [p for p in (C.OUT).rglob("*.md") if "_index" in p.relative_to(C.OUT).parts]
    if bad:
        rep.fail("I5_INDEX_NOT_MD", f"_index 下存在 .md，会被 glob 命中: {bad[0]}")


def grep_probe(rows: list[dict], rep: Report, keys: list[str]) -> None:
    for key in keys:
        hits = []
        for r in rows:
            md = r.get("md_path")
            if not md:
                continue
            p = C.OUT / md
            if p.exists() and key in io.open(p, encoding="utf-8").read():
                hits.append(md)
        if hits:
            rep.ok("G4_GREP", f'grep "{key}" 命中 {len(hits)} 份')
        else:
            rep.warn("G4_GREP", f'grep "{key}" 无命中')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = C.read_index()
    rep = Report()
    if not rows:
        print("索引为空，先运行 sync.py --rebuild")
        return 1
    tax = C.load_yaml("taxonomy.yaml")
    check(rows, rep, tax)
    grep_probe(rows, rep, SAMPLE_GREP)

    if args.json:
        print(json.dumps([{"level": a, "code": b, "msg": c} for a, b, c in rep.items],
                         ensure_ascii=False, indent=2))
    else:
        print(rep.render())
    if args.strict and rep.failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

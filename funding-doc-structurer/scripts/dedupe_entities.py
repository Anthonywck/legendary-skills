# -*- coding: utf-8 -*-
"""主体归一 + 重复识别 + 关联互链。

三件事，全部可复现，不依赖人工记忆：

1. 主体归一：把「深圳烯钻科技」「烯钻科技」「Shenzhen Xienzuan」归到同一个 entity_key，
   规则见 common.subject_key / overrides.yaml 的 subject_alias。
2. 疑似重复：同一 entity_key 下，正文归一化 sha1 相同 → duplicate_of；
   不同但相似度 ≥ SIM_THRESHOLD → duplicate_of + 置信度标注，一律交人工确认，不删不并。
3. 关联互链：同一 entity_key 下的其它文档写入 related_docs（相对路径）。

产物内两种引用字段统一用「产物相对路径」，与 `md_path` 同基准：
    related_docs —— 同主体其它产物
    duplicate_of —— 疑似重复的主产物
索引 `files_index.csv` 里的 `duplicate_of` 存 `source_path`（索引按源文件组织）。

用法：
    python dedupe_entities.py           # 扫描索引，回写 related_docs / duplicate_of
"""

from __future__ import annotations

import argparse
import difflib
import io
import re
import sys
from collections import defaultdict
from pathlib import Path

import common as C
from maintenance import _body_of  # noqa: F401  统一实现

SIM_THRESHOLD = 0.92
CHUNK = 20000


def entity_key(subject: str, overrides: dict) -> str:
    alias = (overrides.get("subject_alias") or {})
    if subject in alias:
        subject = alias[subject]
    return C.subject_key(subject)


def _source_hash(row: dict) -> str:
    """正文归一化哈希，取自索引的 text_sha1 列（抽取阶段对源文件正文写入）。

    不能用 source_sha1（二进制哈希）：真实数据里「同文重命名」的文件二进制不同、
    正文完全相同，二进制哈希会把它们判成两份不同文档。
    """
    return (row.get("text_sha1") or "").strip()


def pair_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a[:CHUNK], b[:CHUNK]).quick_ratio()


def analyze(rows: list[dict], texts: dict[str, str], overrides: dict) -> dict:
    """返回 {entity_key: {primary, members:[{row, sim, dup_of}]}}"""
    raw_keys = [entity_key(r.get("subject") or "unknown", overrides) for r in rows]
    cores = {k: C.subject_core(r.get("subject") or "") for k, r in zip(raw_keys, rows)}
    merged = C.merge_entity_keys(sorted(set(raw_keys)), cores) if len(set(raw_keys)) > 1 else \
        {k: k for k in set(raw_keys)}

    groups: dict[str, list[dict]] = defaultdict(list)
    for r, raw in zip(rows, raw_keys):
        groups[merged.get(raw, raw)].append(r)

    report: dict = {}
    for key, members in groups.items():
        members.sort(key=lambda r: (r.get("date") or "9999", r.get("source_path") or ""))
        primary = members[0]
        # 哈希优先取索引里的 text_sha1（由抽取阶段写入、对源文件正文取哈希），
        # 取不到才回落到「按需读源文件」。顺序很重要：读正文很贵，能不做就不做。
        p_hash = _source_hash(primary)
        p_text = "" if p_hash else texts.get(primary["source_path"], "")
        annotated = []
        for r in members:
            h = _source_hash(r)
            sim = None
            dup_of = ""
            reason = ""
            if r is not primary:
                if h and p_hash and h == p_hash:
                    sim, dup_of, reason = 1.0, primary["source_path"], "源文件归一化正文哈希相同"
                else:
                    # 哈希不同（或缺失）才需要正文相似度；这一步才会真的去读源文件
                    t = texts.get(r["source_path"], "")
                    if not p_text:
                        p_text = texts.get(primary["source_path"], "")
                    if t and p_text:
                        s = pair_similarity(p_text, t)
                        sim = round(s, 4)
                        if s >= SIM_THRESHOLD:
                            dup_of = primary["source_path"]
                            reason = f"正文相似度 {s:.3f} ≥ {SIM_THRESHOLD}"
            annotated.append({"row": r, "sim": sim, "duplicate_of": dup_of, "reason": reason})
        report[key] = {"primary": primary, "members": annotated}
    return report


def apply(report: dict, out_dir: Path) -> int:
    """把 duplicate_of / related_docs / entity_key 回写到各产物 .md 的固定锚点处。

    锚点是正文前的 `<!-- dedupe:begin -->` 块；sync.py 写文件时会预置该锚点，
    因此这里只做「替换块内内容」，不猜测插入位置，保证幂等。
    """
    changed = 0
    for key, grp in report.items():
        paths = [m["row"]["md_path"] for m in grp["members"] if m["row"].get("md_path")]
        for m in grp["members"]:
            row = m["row"]
            md_path = row.get("md_path")
            if not md_path:
                continue
            target = out_dir / md_path
            if not target.exists():
                continue
            rel_related = [p for p in paths if p != md_path]
            # 产物内部的引用统一用「产物相对路径」，与 related_docs 同基准。
            # 索引里仍存 source_path（索引是按源文件组织的），两者各司其职。
            dup_md = ""
            if m["duplicate_of"]:
                dup_row = next((x["row"] for x in grp["members"]
                                if x["row"].get("source_path") == m["duplicate_of"]), None)
                dup_md = (dup_row or {}).get("md_path", "")
            new_block = _block(key=key, dup_of=dup_md, related=rel_related,
                               note=m["reason"])
            wrote = _rewrite(target, new_block)
            wrote = _rewrite_frontmatter(target, related=rel_related, dup_of=dup_md) or wrote
            if wrote:
                changed += 1
            row["duplicate_of"] = m["duplicate_of"]
    return changed


# ---------------------------------------------------------------------------
# frontmatter 同步
# ---------------------------------------------------------------------------

_FM_RELATED = re.compile(r"^related_docs:(?:\s*\[\])?\s*$(\n  - .*$)*", re.M)
_FM_DUP = re.compile(r"^duplicate_of:.*$", re.M)


def _fm_list(key: str, values: list[str]) -> str:
    if not values:
        return f"{key}: []"
    return f"{key}:\n" + "\n".join(f"  - {v}" for v in sorted(values))


def _rewrite_frontmatter(target: Path, *, related: list[str], dup_of: str) -> bool:
    """把 related_docs / duplicate_of 写回 frontmatter。

    这两个字段由 dedupe 阶段算出，但产物是抽取阶段先写好的，所以必须回填——
    否则 frontmatter 里永远是空值，下游只能去正文的 dedupe 块里找。
    """
    text = io.open(target, encoding="utf-8").read()
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    head, rest = text[:end], text[end:]
    new_head = _FM_RELATED.sub(lambda _m: _fm_list("related_docs", related), head, count=1)
    new_head = _FM_DUP.sub(lambda _m: f"duplicate_of: {dup_of or 'null'}", new_head, count=1)
    if new_head == head:
        return False
    io.open(target, "w", encoding="utf-8", newline="\n").write(new_head + rest)
    return True


_BLOCK_BEGIN = "<!-- dedupe:begin -->"
_BLOCK_END = "<!-- dedupe:end -->"
EMPTY_BLOCK = f"{_BLOCK_BEGIN}\n{_BLOCK_END}"


def _block(key: str, dup_of: str, related: list[str], note: str) -> str:
    lines = [_BLOCK_BEGIN, "```yaml"]
    lines.append(f"entity_key: {key}")
    lines.append(f"duplicate_of: {dup_of if dup_of else 'null'}")
    if dup_of and note:
        lines.append(f"duplicate_note: {note}")
    if related:
        lines.append("related_docs:")
        for p in sorted(related):
            lines.append(f"  - {p}")
    else:
        lines.append("related_docs: []")
    lines.append("```")
    lines.append(_BLOCK_END)
    return "\n".join(lines)


def _rewrite(md_file: Path, block: str) -> bool:
    text = io.open(md_file, encoding="utf-8").read()
    if _BLOCK_BEGIN not in text or _BLOCK_END not in text:
        return False  # 无锚点 → 不是本 Skill 产物，跳过而非猜测插入
    new = re.sub(re.escape(_BLOCK_BEGIN) + r".*?" + re.escape(_BLOCK_END),
                 lambda _m: block, text, count=1, flags=re.S)
    if new != text:
        io.open(md_file, "w", encoding="utf-8", newline="\n").write(new)
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="主体归一与重复识别")
    ap.add_argument("--out", default=str(C.OUT))
    args = ap.parse_args()
    rows = C.read_index()
    if not rows:
        print("索引为空，先运行 sync.py --rebuild")
        return 1
    texts = {}
    for r in rows:
        md = Path(args.out) / r["md_path"] if r.get("md_path") else None
        if md and md.exists():
            texts[r["source_path"]] = _body_of(md)
    rep = analyze(rows, texts, C.load_overrides())
    n = apply(rep, Path(args.out))
    C.write_index(rows)
    print(f"实体组 {len(rep)} 个，更新产物 {n} 份")
    for key, grp in rep.items():
        if len(grp["members"]) > 1:
            print(f"  [{key}] {len(grp['members'])} 份文档")
            for m in grp["members"]:
                tag = f" ≒ {m['duplicate_of']}" if m["duplicate_of"] else ""
                print(f"    - {m['row']['source_path']}{tag}")
    return 0

# -*- coding: utf-8 -*-
"""同步后置维护：去重互链、孤儿回收、陈旧清理、报告输出。

这些操作都作用于「已经写入磁盘的产物树」，与单文件抽取无关，
因此单独成模块，便于在重建之后单独重跑。
"""

from __future__ import annotations

import io
import re
import shutil
from pathlib import Path

import common as C


def _body_of(md: Path) -> str:
    """读产物正文（去掉 frontmatter），用于重复识别的文本比对。"""
    text = io.open(md, encoding="utf-8").read()
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:]
    return text


def _postprocess(rows: list[dict]) -> None:
    """主体归一 + 重复识别 + 关联互链。失败不影响主流程。

    正文比对**只读源文件**，不读产物：产物里除了正文还有 dedupe 块与元数据头，
    每次重写都会让「正文」变化分毫，相似度随之抖动（0.994 / 0.995 来回跳），
    产出的 duplicate_note 就不是幂等的了。
    """
    try:
        from dedupe_entities import analyze, apply
        texts = LazyTexts(set(r.get("source_path") or "" for r in rows))
        report = analyze(rows, texts, C.load_overrides())
        apply(report, C.OUT)
    except Exception as exc:  # noqa: BLE001
        C.log_error(f"dedupe 阶段异常 {type(exc).__name__}: {exc}")


class LazyTexts(dict):
    """按需取正文：只有「哈希不同、需要算相似度」时才真的去读源文件。

    同一实体下的文档通常只有 1–3 份，实际读取次数极少；
    这样 dedupe 阶段不会退化成「把所有源文件再解析一遍」。
    """

    def __init__(self, paths: set[str]):
        super().__init__()
        self._paths = paths
        self._cache: dict[str, str] = {}

    def get(self, key, default=""):  # noqa: D401
        if key in self:
            return self[key]
        if key not in self._paths:
            return default
        if key not in self._cache:
            src = C.ROOT / key
            text = ""
            if src.exists():
                try:
                    from extract import extract
                    res = extract(src)
                    text = res.text if res.status == "ok" else ""
                except Exception:  # noqa: BLE001
                    text = ""
            self._cache[key] = text
        return self._cache[key] or default


def _retain_orphans(old_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    """把「源已失联但产物仍在」的行并回索引。

    --rebuild 不依赖历史索引，会丢掉 missing 的痕迹；但产物 .md 依约束必须保留，
    否则索引与目录脱节、`--prune` 也永远找不到它们。因此以「产物文件里的
    source_path」为线索把孤儿行找回，重标 missing/orphaned。
    读取的是产物自身，不是历史 CSV —— 重建仍是从目录推导，不依赖缓存。
    """
    known = {r["source_path"] for r in new_rows}
    found: list[dict] = []
    root = C.OUT / "by_topic"
    if not root.is_dir():
        return found
    old_by_sp = {r["source_path"]: r for r in old_rows}
    for p in sorted(root.rglob("*.md")):
        try:
            text = io.open(p, encoding="utf-8").read(3000)
        except OSError:
            continue
        m = re.search(r"^source_path:\s*(.+)$", text, re.M)
        if not m:
            continue
        sp = m.group(1).strip().strip('"')
        if not sp or sp in known:
            continue
        known.add(sp)
        base = dict(old_by_sp.get(sp, {}))
        base.update({
            "source_path": sp,
            "source_root": re.search(r"^source_root:\s*(.+)$", text, re.M).group(1).strip()
            if re.search(r"^source_root:\s*(.+)$", text, re.M) else base.get("source_root", ""),
            "md_path": p.relative_to(C.OUT).as_posix(),
            "source_status": "missing",
            "md_status": "orphaned",
        })
        for key, pat in (("subject", r"^subject:\s*(.+)$"), ("topic", r"^topic:\s*(.+)$"),
                         ("doc_type", r"^doc_type:\s*(.+)$"), ("date", r"^date:\s*(.+)$"),
                         ("date_source", r"^date_source:\s*(.+)$")):
            mm = re.search(pat, text, re.M)
            if mm:
                base[key] = mm.group(1).strip().strip('"')
        found.append(base)
    return found


def _remove_stale(rows: list[dict]) -> int:
    """删除「在产物目录里但不在索引里」的 .md。

    只动 by_topic/**/*.md，且这些文件都带本 Skill 的 frontmatter 指纹才会删；
    避免误删用户手工放进去的其他 Markdown。
    """
    indexed = {r["md_path"] for r in rows if r.get("md_path")}
    removed = 0
    root = C.OUT / "by_topic"
    if not root.is_dir():
        return 0
    for p in root.rglob("*.md"):
        rel = p.relative_to(C.OUT).as_posix()
        if rel in indexed:
            continue
        try:
            head = io.open(p, encoding="utf-8").read(400)
        except OSError:
            continue
        if not head.startswith("---") or "source_path: datas/" not in io.open(
                p, encoding="utf-8").read(3000):
            continue
        p.unlink()
        removed += 1
        _prune_empty_dirs(p.parent)
    return removed


def _prune_empty_dirs(d: Path) -> None:
    while d != C.OUT and d.is_dir() and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


def _md_broken(row: dict) -> bool:
    md = row.get("md_path")
    return bool(md) and not (C.OUT / md).exists()


def _move_md(old_rel: str, new_rel: str, dry: bool) -> None:
    old, new = C.OUT / old_rel, C.OUT / new_rel
    if dry or not old.exists() or old == new:
        return
    new.parent.mkdir(parents=True, exist_ok=True)
    if new.exists():
        new.unlink()
    shutil.move(str(old), str(new))

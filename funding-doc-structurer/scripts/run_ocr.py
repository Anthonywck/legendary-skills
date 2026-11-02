# -*- coding: utf-8 -*-
"""阶段二：对已登记的 needs_ocr 文件批量补 OCR。

两阶段设计的原因：OCR 单页约 4 秒，扫描件动辄 20–30 页。
若在全量抽取时同步做 OCR，一次全量会被少数扫描件拖成数十分钟。
拆开后：
  阶段一（默认）  快速跑完全量，扫描件只标 needs_ocr —— 目录结构与其余内容立刻可用
  阶段二（本脚本）单独挑出 needs_ocr 的文件补 OCR，可断点续跑、可分多次

用法：
    python run_ocr.py --dry-run        # 列出待 OCR 清单与预估耗时
    python run_ocr.py                  # 全部补 OCR
    python run_ocr.py --limit 3        # 只处理前 3 份
    python run_ocr.py --max-pages 30   # 单份最多 OCR 30 页
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import common as C


def pending() -> list[dict]:
    rows = C.read_index()
    return [r for r in rows
            if r.get("md_status") == "degraded:needs_ocr"
            and r.get("source_status") != "missing"
            and r.get("source_path")]


def estimate(rows: list[dict]) -> tuple[int, float]:
    """按页数粗估 OCR 耗时（每页约 4 秒）。"""
    import pymupdf

    pages = 0
    for r in rows:
        p = C.ROOT / r["source_path"]
        if not p.exists():
            continue
        if p.suffix.lower() == ".pdf":
            try:
                with pymupdf.open(str(p)) as d:
                    pages += d.page_count
            except Exception:  # noqa: BLE001
                pages += 20
        else:
            pages += 1
    return pages, pages * 4.0


def run(rows: list[dict], max_pages: int) -> tuple[int, int]:
    # 让 extract 在本进程内走 OCR 分支。
    # 开关在 ocr_enabled() 里于调用时读取，无需 reload 模块——
    # reload 会让 parsers/extract 之间的函数引用错位，反而引发假故障。
    os.environ["FDS_OCR"] = "1"
    os.environ["FDS_OCR_MAX_PAGES"] = str(max_pages)

    import extract as E

    from emit import row_of, write_md
    from build_frontmatter import build_record

    tax = C.load_yaml("taxonomy.yaml")
    last_run = C.today()
    ok = fail = 0
    for r in rows:
        src = C.ROOT / r["source_path"]
        t0 = time.time()
        try:
            res = E.extract(src)
        except Exception as exc:  # noqa: BLE001
            C.log_error(f"{r['source_path']}: OCR 阶段异常 {type(exc).__name__}: {exc}")
            fail += 1
            print(f"  [失败] {Path(r['source_path']).name}: {exc}")
            continue
        if res.status != "ok":
            print(f"  [仍不可用] {Path(r['source_path']).name}: {res.status}")
            fail += 1
            continue
        rec = build_record(src=src, source_root=r.get("source_root", ""), res=res, tax=tax,
                           last_run=last_run)
        write_md(rec, res, r["md_path"], last_run, dry=False)
        new = row_of({"source_root": r.get("source_root", ""), "source_path": r["source_path"],
                      "size": int(r.get("source_size") or 0), "mtime": r.get("source_mtime", "")},
                     rec, res, r["md_path"], r.get("source_sha1", ""), last_run)
        # row_of 会把 duplicate_of 重置为空；补 OCR 不应抹掉已算出的去重结论
        new["duplicate_of"] = r.get("duplicate_of", "")
        r.update(new)
        ok += 1
        print(f"  [完成] {Path(r['source_path']).name}  {time.time()-t0:.0f}s")
    if ok:
        current = C.read_index()
        merged = _merged(current, rows) or current
        C.write_index(merged)
        # OCR 改变正文 → 正文哈希与相似度都可能变，必须重算去重与互链
        try:
            from maintenance import _postprocess
            _postprocess(merged)
            C.write_index(merged)
        except Exception as exc:  # noqa: BLE001
            C.log_error(f"OCR 后置去重失败: {type(exc).__name__}: {exc}")
    return ok, fail


def _merged(current: list[dict], updated: list[dict]) -> list[dict]:
    by_path = {r["source_path"]: r for r in updated}
    for i, r in enumerate(current):
        if r["source_path"] in by_path:
            current[i] = by_path[r["source_path"]]
    return current


def main() -> int:
    ap = argparse.ArgumentParser(description="对 needs_ocr 文件批量补 OCR")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-pages", type=int, default=60, help="单份最多 OCR 页数（默认 60）")
    ap.add_argument("--only", default=None, help="只处理某个来源目录")
    args = ap.parse_args()

    rows = pending()
    if args.only:
        rows = [r for r in rows if r.get("source_root") == args.only]
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        print("没有待 OCR 的文件（needs_ocr = 0）")
        return 0

    pages, secs = estimate(rows)
    print(f"待 OCR {len(rows)} 份，约 {pages} 页，预估 {secs/60:.0f} 分钟"
          f"（单页约 4 秒；可用 --limit 分批）")
    for r in rows:
        print(f"  - {r['source_path']}")
    if args.dry_run:
        return 0

    try:
        ans = input("\n开始 OCR？[y/N] ").strip().lower()
    except EOFError:
        ans = "y"
    if ans not in ("y", "yes"):
        print("已取消")
        return 1

    t0 = time.time()
    ok, fail = run(rows, args.max_pages)
    print(f"\nOCR 完成：成功 {ok}，失败 {fail}，耗时 {(time.time()-t0)/60:.1f} 分钟")
    print("建议随后运行 validate_output.py 复查一致性")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

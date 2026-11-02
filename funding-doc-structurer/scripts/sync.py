# -*- coding: utf-8 -*-
"""索引与增量同步：--rebuild / --sync / --prune。

索引 datas-md/_index/files_index.csv 是可重建的派生缓存，不是权威源。
任何时刻删除索引，--rebuild 都能从 datas 与 datas-md 重新推导出一致的结果。

用法：
    python sync.py --rebuild                 # 全量：重扫源目录，重建索引并补齐产物
    python sync.py --sync                    # 增量：只处理新增/变更/改名/失联
    python sync.py --prune                   # 列出孤儿产物，确认后清理
    python sync.py --rebuild --dry-run       # 只报告，不写盘
    python sync.py --rebuild --limit 5       # 样本试跑
    python sync.py --sync --only 商业计划书   # 限定来源目录（datas 下的一级子目录）
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
from pathlib import Path

import common as C
from emit import WARN_MISSING, PathAllocator, mark_missing, process, render_md, row_of, write_md
from maintenance import (_md_broken, _move_md, _postprocess, _remove_stale,
                         _retain_orphans)
import report as R

# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------
#
# 源目录不写死：datas/ 下的每个一级子目录都是一个「来源根」。
# source_root 这个字段因此变成「文件所在的一级目录名」，既保留可回溯性，
# 又让同一份 Skill 能用于 `datas/商业计划书`、`datas/AICC加密模型服务方案`
# 或任何用户自己划的目录，不需要改代码。
#
# 需要排除的目录（如临时目录、备份）写在 _index/overrides.yaml 的 exclude_roots。

IGNORED_SUFFIX = {".zip", ".rar", ".7z"}      # 压缩包显式不处理


def source_roots(exclude: list[str] | None = None) -> list[str]:
    exclude = set(exclude or [])
    if not C.DATAS.is_dir():
        return []
    return sorted(
        d.name for d in C.DATAS.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name not in exclude
    )


def scan_sources(only: str | None = None, picks: list[str] | None = None,
                 exclude: list[str] | None = None) -> list[dict]:
    out: list[dict] = []
    for root_name in source_roots(exclude):
        if only and root_name != only:
            continue
        root = C.DATAS / root_name
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() in IGNORED_SUFFIX:
                continue
            if picks and not any(k in p.name for k in picks):
                continue
            st = p.stat()
            out.append({
                "source_root": root_name,
                "source_path": C.rel_posix(p),
                "abs": p,
                "name": p.name,
                "size": st.st_size,
                "mtime": C.file_mtime_iso(p),
            })
    return out



# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _needs_reextract(prior: dict, mode: str, rules_changed: bool = False) -> bool:
    """在源未变更的前提下，判断是否仍应重新抽取。

    `--rebuild` 的语义是「重建索引」，不等于「把每份正文都重新解析一遍」。
    对已经 ok 的产物重解析毫无收益，代价却很高——尤其是经过阶段二 OCR 的扫描件：
    阶段一默认不开 OCR，强制重抽会把 20 分钟的 OCR 成果打回 needs_ocr。
    因此：ok 的产物在源未变时一律跳过；只有降级/失败态才值得重试一次。

    唯一的例外是**判定规则本身变了**（改了 taxonomy.yaml 的赛道词表或 doc_type 规则）。
    那时旧产物的落位与元数据已经过时，必须重抽，否则改配置等于没改。
    """
    if rules_changed:
        return True
    status = (prior.get("md_status") or "").lower()
    if status == "ok":
        return False
    if status.startswith("orphaned"):
        return False          # 源回来了 → 由调用方改回 ok，无需重抽
    return True               # degraded / error / stale 都重试一次


def _rules_fingerprint() -> str:
    """判定规则的指纹：taxonomy.yaml 的内容哈希。

    只需覆盖「决定落位与字段值」的配置；formats.yaml 改动解析器，
    与已有产物是否过时无关，不纳入。
    """
    path = C.SKILL / "assets" / "taxonomy.yaml"
    try:
        return C.sha1_file(path)[:16]
    except OSError:
        return ""


RULES_MARKER = C.INDEX_DIR / ".rules_fingerprint"


REQUIRED_MODULES = {"pymupdf": "PDF", "pptx": "PPTX"}


def _check_required() -> str:
    """必需解析依赖缺失时中止。

    缺依赖不会让流程失败，而是把所有文件判成 unsupported 并**照常写盘**，
    用空正文覆盖已有的好产物。因此这里必须硬性中止，不能降级继续。
    """
    missing = []
    for mod, label in REQUIRED_MODULES.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(f"{mod}（{label}）")
    if not missing:
        return ""
    return (
        "缺少必需依赖: " + "、".join(missing) + "\n"
        "继续执行会把全部文件判成 unsupported 并覆盖已有产物，已中止。\n"
        "请用项目内虚拟环境执行，例如：\n"
        "  .venv-doc/Scripts/python.exe .claude/skills/funding-doc-structurer/scripts/sync.py --rebuild\n"
        "并先运行 check_env.py 确认环境。"
    )


def run(mode: str, *, dry: bool, limit: int | None, only: str | None,
        picks: list[str] | None = None, force: bool = False) -> int:
    err = _check_required()
    if err:
        print(err)
        return 2
    C.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    tax = C.load_yaml("taxonomy.yaml")
    last_run = C.today()

    # --rebuild 与 --sync 共用同一份「上一次的索引」，区别只在失联判定：
    #   --sync 凭它找出源已删除的行
    #   --rebuild 不据此推断任何「缺失」，但仍用它判断某份产物是否已 ok、可以跳过
    # 这样重建不会白跑 OCR，也不会把「索引里没有」误当成「源已删除」。
    old_rows = C.read_index()

    # 规则变更检测：taxonomy.yaml 变了，已有产物的落位/字段可能全部过时
    fingerprint = _rules_fingerprint()
    prev_fp = ""
    if RULES_MARKER.exists():
        try:
            prev_fp = io.open(RULES_MARKER, encoding="utf-8").read().strip()
        except OSError:
            prev_fp = ""
    rules_changed = bool(prev_fp) and bool(fingerprint) and prev_fp != fingerprint
    if rules_changed or force:
        if force:
            print("已指定 --force-render，本轮重新渲染全部产物")
        else:
            print("检测到判定规则变更（taxonomy.yaml），本轮将重新抽取全部文件")

    by_path = {r["source_path"]: r for r in old_rows}
    by_sha: dict[str, dict] = {}
    by_sha_dup: set[str] = set()
    for r in old_rows:
        h = r.get("source_sha1", "")
        if h in by_sha:
            by_sha_dup.add(h)
        by_sha[h] = r
    for h in by_sha_dup:
        by_sha.pop(h, None)  # 哈希重复时不做改名匹配，避免错配

    exclude = C.load_overrides().get("exclude_roots") or []
    sources = scan_sources(only, picks, exclude)
    if limit:
        sources = sources[:limit]

    taken = {r["md_path"]: r["source_path"] for r in old_rows if r.get("md_path")}
    alloc = PathAllocator(taken)

    new_rows: list[dict] = []
    seen_paths: set[str] = set()
    stats = {"processed": 0, "skipped": 0, "renamed": 0, "new": 0, "failed": 0}

    for src in sources:
        try:
            sha1 = C.sha1_file(src["abs"])
            prior = by_path.get(src["source_path"])
            renamed_from = ""
            if prior and prior.get("source_sha1") == sha1 and prior.get("source_size") == str(src["size"]) \
                    and not _md_broken(prior) and not force \
                    and not _needs_reextract(prior, mode, rules_changed):
                # 未变更，沿用
                row = dict(prior)
                row["source_mtime"] = src["mtime"]
                row["last_run"] = last_run
                row["source_status"] = "active"
                if row.get("md_status", "").startswith("orphaned"):
                    row["md_status"] = "ok"
                if _md_broken(row):
                    row["md_status"] = "stale"
                new_rows.append(row)
                seen_paths.add(src["source_path"])
                stats["skipped"] += 1
                continue

            if not prior:
                twin = by_sha.get(sha1)
                if twin and twin["source_path"] not in seen_paths:
                    renamed_from = twin["source_path"]
                    stats["renamed"] += 1
                    # 改名是原地更新同一行，不是新建行：把旧行的产物归属让给新路径
                    if twin.get("md_path"):
                        alloc.taken.pop(twin["md_path"], None)

            rec, res = process(src, tax, last_run)
            if rec is None:
                C.log_error(str(res))
                stats["failed"] += 1
                if prior:
                    row = dict(prior)
                    row["md_status"] = "error"
                    row["last_run"] = last_run
                    if _md_broken(row):
                        row["md_path"] = ""
                    new_rows.append(row)
                    seen_paths.add(src["source_path"])
                else:
                    new_rows.append({
                        "source_root": src["source_root"], "source_path": src["source_path"],
                        "source_size": str(src["size"]), "source_mtime": src["mtime"],
                        "source_sha1": sha1, "md_path": "", "source_status": "active",
                        "md_status": "error", "text_sha1": "", "last_run": last_run,
                    })
                    seen_paths.add(src["source_path"])
                continue

            md_path = alloc.assign(rec["md_path"], src["source_path"], sha1)
            rec["md_path"] = md_path
            row = row_of(src, rec, res, md_path, sha1, last_run)
            if renamed_from:
                row["source_status"] = "renamed"
                row["renamed_from"] = renamed_from

            # 旧路径残留：先移动再写，避免「新写一份 + 旧文件还在」造成两份内容。
            # 若规则变更导致落位从 A 变到 B，B 会被 write_md 写成新内容，
            # 而 A 里的旧内容必须一起消失，否则同一份源文件会对应两份产物。
            if prior and prior.get("md_path") and prior["md_path"] != md_path:
                _move_md(prior["md_path"], md_path, dry)
            write_md(rec, res, md_path, last_run, dry)
            if renamed_from:
                old = by_path.get(renamed_from)
                if old and old.get("md_path") and old["md_path"] != md_path:
                    _move_md(old["md_path"], md_path, dry)

            new_rows.append(row)
            seen_paths.add(src["source_path"])
            if renamed_from:
                seen_paths.add(renamed_from)   # 改名：旧路径已由新行接管，不能再生出 missing 行
            stats["processed"] += 1
            if not prior and not renamed_from:
                stats["new"] += 1
        except Exception as exc:  # noqa: BLE001
            C.log_error(f"{src['source_path']}: 未捕获异常 {type(exc).__name__}: {exc}")
            stats["failed"] += 1
            # NameError 只可能来自代码缺陷（漏 import、拼错变量），不可能来自数据。
            # 继续跑只会把每个文件都标成失败并掩盖根因，因此立即中止整批。
            # AttributeError/TypeError 也可能由畸形数据触发，仍按单点失败处理。
            if isinstance(exc, NameError):
                raise SystemExit(
                    f"检测到代码缺陷（{exc}），已中止批次。"
                    f"详见 {C.rel_posix(C.ERROR_LOG)}"
                ) from exc
            continue

    # 失联：索引中存在、本次扫描不到
    # 只有「真正全量」才判失联。--limit / --pick 会让本轮只看到一部分文件，
    # 此时把没扫到的旧行一律判成 missing 是误报（且会写坏产物里的 source_available）。
    full_scan = not limit and not picks
    if not full_scan:
        # 部分试跑：未被扫描到的旧行原样保留，状态不动
        seen_now = seen_paths | {r["source_path"] for r in new_rows}
        for r in old_rows:
            if r["source_path"] not in seen_now:
                new_rows.append(dict(r))
    elif only:
        for r in old_rows:          # 限定来源目录时，其它目录的行原样保留
            if r.get("source_root") != only:
                new_rows.append(dict(r))
    if full_scan:
        still_seen = {r["source_path"] for r in new_rows}
        for r in old_rows:
            sp = r["source_path"]
            if sp in seen_paths or sp in still_seen:
                continue
            if only and r.get("source_root") != only:
                continue
            row = dict(r)
            mark_missing(row, last_run, dry)
            new_rows.append(row)

    # 孤儿回收只在全量时做：部分试跑下「没被引用」不等于「源已删除」
    if full_scan:
        new_rows.extend(_retain_orphans(old_rows, new_rows))

    if dry:
        R.emit(new_rows, stats, dry=True)
        return 0

    # 全量重建后，索引不再引用的产物即为陈旧产物（主体/赛道/日期变更导致路径迁移）。
    # 只在真正的全量场景清理；带 limit/pick 的样本试跑不删任何文件。
    if mode == "rebuild" and full_scan:
        stats["stale_removed"] = _remove_stale(new_rows)

    C.write_index(new_rows)
    _postprocess(new_rows)
    C.write_index(new_rows)
    if fingerprint and not dry:
        try:
            io.open(RULES_MARKER, "w", encoding="utf-8").write(fingerprint)
        except OSError as exc:
            C.log_error(f"规则指纹写入失败: {exc}")
    C.write_view(new_rows, "subject", C.INDEX_DIR / "by_subject.csv")
    C.write_view(new_rows, "date", C.INDEX_DIR / "by_date.csv")
    rep = R.emit(new_rows, stats, dry=False)
    # 退出码：有异常失败返回 1，只有降级（可接受）仍返回 0，便于 CI 区分
    return 1 if stats.get("failed") else 0


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def prune(dry: bool = False, yes: bool = False) -> int:
    rows = C.read_index()
    orphans = [r for r in rows if r.get("md_status") == "orphaned" and r.get("md_path")]
    existing = [(r, C.OUT / r["md_path"]) for r in orphans if (C.OUT / r["md_path"]).exists()]
    if not existing:
        print("无待清理的孤儿产物")
        return 0
    print(f"以下 {len(existing)} 份产物的源文件已失联，将被删除：")
    for r, p in existing:
        print(f"  - {r['md_path']}   ← 源: {r['source_path']}")
    if dry:
        return 0
    if not yes:
        try:
            ans = input("确认删除? 输入 yes 继续: ").strip().lower()
        except EOFError:
            print("非交互环境，需加 --yes 才会执行删除")
            return 1
        if ans != "yes":
            print("已取消")
            return 1
    keep = []
    for r, p in existing:
        p.unlink()
        r["md_status"] = "pruned"
    remaining = [r for r in rows if r.get("md_status") != "pruned"]
    C.write_index(remaining)
    print(f"已删除 {len(existing)} 份产物，索引同步更新")
    return 0


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="索引与增量同步")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--rebuild", action="store_true", help="全量重建索引与产物")
    g.add_argument("--sync", action="store_true", help="增量同步")
    g.add_argument("--prune", action="store_true", help="清理孤儿产物")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 个源文件（样本试跑）")
    ap.add_argument("--only", default=None, metavar="DIR",
                    help=f"只处理某个来源目录（可选: {', '.join(source_roots()) or 'datas 下暂无子目录'}）")
    ap.add_argument("--pick", action="append", default=None, metavar="SUBSTR",
                    help="样本试跑：只处理文件名含该子串的源文件，可重复")
    ap.add_argument("--force-render", action="store_true",
                    help="重新渲染全部产物（改写模板/清洗规则后使用；不会重跑 OCR）")
    ap.add_argument("--yes", action="store_true", help="prune 时跳过确认")
    args = ap.parse_args()

    if args.prune:
        return prune(dry=args.dry_run, yes=args.yes)
    if args.limit and args.limit <= 0:
        print("--limit 必须为正整数")
        return 2
    return run("rebuild" if args.rebuild else "sync", dry=args.dry_run,
               limit=args.limit, only=args.only, picks=args.pick,
               force=args.force_render)


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""端到端自检：在临时沙箱里跑「重建 → 改名 → 源删除 → 再重建 → 清理」。

沙箱由 FDS_ROOT 指向，绝不触碰真实 datas。所有断言失败都会列出来并以非零码退出。

用法：
    python selftest.py
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SAMPLES = {
    # 沙箱文件名 → 真实源文件（相对项目根）
    "A.pptx": "datas/商业计划书/【半导体设备】鹏城半导体 -高端半导体外延设备的国产化项目商业计划书.pptx",
    "B.pdf": "datas/商业计划书/【半导体】森国科SiC -碳化硅项目商业计划书.pdf",
    "C.pdf": "datas/行业报告/半导体检测行业报告：集成电路国产化加速，第三方检测发展空间广阔-230722（28页）.pdf",
    # 新增格式覆盖：docx / md / png（均来自 AICC 目录，只读复制）
    "D.docx": "datas/AICC加密模型服务方案/内网Claude Cli离线安装与接入AICC加密计算服务.docx",
    "E.md": "datas/AICC加密模型服务方案/内网Opencode离线安装与接入AICC加密计算服务.md",
    "F.png": "datas/AICC加密模型服务方案/ScreenShot_2026-10-30_165925_042.png",
}

results: list[tuple[bool, str]] = []


def check(cond: bool, msg: str) -> None:
    results.append((bool(cond), msg))


def run(root: Path, *args: str) -> str:
    env = dict(os.environ, FDS_ROOT=str(root), PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPTS / "sync.py"), *args],
                       capture_output=True, text=True, env=env, encoding="utf-8")
    return (p.stdout or "") + (p.stderr or "")


def retry(fn, tries: int = 15, delay: float = 0.2):
    """Windows 上杀毒/搜索索引会短暂持有新建文件句柄，重命名与删除需容忍瞬时占用。"""
    last = None
    for _ in range(tries):
        try:
            return fn()
        except PermissionError as exc:
            last = exc
            time.sleep(delay)
    raise last


def load(root: Path) -> list[dict]:
    path = root / "datas-md" / "_index" / "files_index.csv"
    if not path.exists():
        return []
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


# 新增格式的合成样本：不依赖真实数据，避免测试与具体文件耦合
SYNTHETIC = {
    "G.txt": ("utf-8", "\n".join(["纯文本测试", ""] + ["半导体行业景气度回升，国产替代加速。"] * 3) + "\n"),
    "H.csv": ("utf-8-sig", "\n".join([
        "公司,轮次,估值", "森国科,D轮,10.2亿元", "中锗科技,A轮,5亿元", ""])),
    "I.tsv": ("utf-8", "\n".join(["赛道\t企业", "半导体\t森国科", ""])),
}


def build_sandbox(base: Path) -> Path:
    root = base / "sandbox"
    for sub in ("商业计划书", "行业报告", "AICC加密模型服务方案"):
        (root / "datas" / sub).mkdir(parents=True)
    project = next(p for p in SCRIPTS.parents if (p / "datas").is_dir())
    for dst, src in SAMPLES.items():
        sub = src.split("/")[1]
        shutil.copy2(project / src, root / "datas" / sub / dst)

    fmt_dir = root / "datas" / "格式测试"
    fmt_dir.mkdir(parents=True, exist_ok=True)
    for dst, (enc, body) in SYNTHETIC.items():
        io.open(fmt_dir / dst, "w", encoding=enc, newline="").write(body)
    # xlsx 用 openpyxl 现场生成：二进制文件不便以文本形式内嵌
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "融资汇总"
        ws.append(["公司", "轮次"])
        ws.append(["森国科", "D轮"])
        wb.save(fmt_dir / "J.xlsx")
    except ImportError:
        pass
    return root


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="fds-selftest-")
    try:
        root = build_sandbox(Path(tmp))

        # 1. 全量重建
        run(root, "--rebuild")
        rows = load(root)
        check(len(rows) >= 9, f"重建后索引应 ≥9 行，实际 {len(rows)}")
        check(all(r["source_status"] == "active" for r in rows), "重建后全部应为 active")
        md_A = next((r["md_path"] for r in rows if r["source_path"].endswith("A.pptx")), "")
        check(bool(md_A) and (root / "datas-md" / md_A).exists(), "PPTX 产物应已生成")

        # 1b. 每个产物都必须带 dedupe 锚点；同时 errors.log 不得因内部异常堆积
        for p in (root / "datas-md").rglob("*.md"):
            check("entity_key" in io.open(p, encoding="utf-8").read(),
                  f"{p.name} 缺少 dedupe 块（说明后置阶段静默失败）")
        err = root / "datas-md" / "_index" / "errors.log"
        if err.exists():
            body = io.open(err, encoding="utf-8").read()
            check("dedupe 阶段异常" not in body and "未捕获异常" not in body,
                  "errors.log 记录了内部异常，应视为失败")

        # 1b2. 新增格式必须真的抽出内容，而不是登记成 unsupported/empty
        fmt_ok = {}
        for r in rows:
            name = Path(r["source_path"]).name
            if name.startswith(("G.", "H.", "I.", "J.")):
                fmt_ok[name] = (r["md_status"], r["doc_type"])
        for n in ("G.txt", "H.csv", "I.tsv", "J.xlsx"):
            if n in fmt_ok:
                check(fmt_ok[n][0] == "ok", f"{n} 应抽取成功，实际 {fmt_ok[n][0]}")
        for n in ("H.csv", "I.tsv", "J.xlsx"):
            if n in fmt_ok:
                check(fmt_ok[n][1] == "SHEET", f"{n} 应归为 SHEET，实际 {fmt_ok[n][1]}")

        # 1c. 已 ok 的产物，重建时不得被重抽（否则阶段二 OCR 的成果会被抹掉）
        ok_before = {r["source_path"]: r["md_path"] for r in load(root)
                     if r["md_status"] == "ok"}
        run(root, "--rebuild")
        rows = load(root)
        after = {r["source_path"]: (r["md_status"], r["md_path"]) for r in rows}
        for sp, md in ok_before.items():
            check(after.get(sp) == ("ok", md), f"重建把已 ok 的产物打回降级态: {sp}")

        # 2. 幂等
        before = {r["source_path"]: r["md_path"] for r in rows}
        run(root, "--rebuild")
        after = {r["source_path"]: r["md_path"] for r in load(root)}
        check(before == after, "重复重建不应改变产物路径")

        # 3. 改名
        src_dir = root / "datas" / "商业计划书"
        retry(lambda: (src_dir / "A.pptx").rename(src_dir / "A-renamed.pptx"))
        run(root, "--sync")
        rows = load(root)
        renamed = [r for r in rows if r["source_status"] == "renamed"]
        check(len(renamed) == 1, f"改名后应有 1 行 renamed，实际 {len(renamed)}")
        check(len(rows) >= 9, f"改名不应减少行数，实际 {len(rows)}")
        if renamed:
            check(renamed[0]["renamed_from"].endswith("A.pptx"), "renamed_from 应记录旧路径")
            check(renamed[0]["md_path"] == md_A, "改名不应导致产物路径漂移")

        # 4. 源删除
        retry(lambda: (src_dir / "B.pdf").unlink())
        run(root, "--sync")
        rows = load(root)
        orphan = [r for r in rows if r["source_status"] == "missing"]
        check(len(orphan) == 1, f"删除源后应有 1 行 missing，实际 {len(orphan)}")
        if orphan:
            o = orphan[0]
            check(o["md_status"] == "orphaned", "missing 行的 md_status 应为 orphaned")
            md = root / "datas-md" / o["md_path"]
            check(md.exists(), "源删除后产物必须保留")
            if md.exists():
                text = io.open(md, encoding="utf-8").read()
                check("source_available: false" in text, "产物应标记 source_available: false")
                check("源文件已不存在" in text, "产物应带醒目提示")

        # 5. 重建后孤儿仍在索引中
        run(root, "--rebuild")
        rows = load(root)
        check(any(r["source_status"] == "missing" for r in rows),
              "--rebuild 不得静默丢失孤儿行")
        check(any((root / "datas-md" / r["md_path"]).exists()
                  for r in rows if r["source_status"] == "missing"),
              "--rebuild 后孤儿产物文件仍应存在")

        # 6. prune
        out = run(root, "--prune", "--yes")
        rows = load(root)
        check(not any(r["source_status"] == "missing" for r in rows),
              "--prune 后不应再有 missing 行")
        check("已删除" in out or "无待清理" in out, f"prune 输出异常: {out.strip()[:80]}")

        # 7. 原件只读
        check((src_dir / "A-renamed.pptx").exists(), "沙箱源文件应保持完好")
        check((root / "datas" / "行业报告" / "C.pdf").exists(), "未处理目录的源文件不应被动")

    finally:
        shutil.rmtree(tmp, onexc=lambda *_: None)   # 清理失败不影响结论

    ok = sum(1 for c, _ in results if c)
    for good, msg in results:
        print(("[PASS] " if good else "[FAIL] ") + msg)
    print(f"\n{ok}/{len(results)} 通过")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""环境探测 + 按需建 venv 安装依赖。

用法：
    python check_env.py            # 只探测，输出 JSON 报告
    python check_env.py --install  # 缺失则打印清单并建 venv 安装
    python check_env.py --ensure   # 非交互：直接安装缺失项（供 sync.py 内部调用）

探测顺序：当前解释器 → 项目内 .venv-doc → 项目内 .venv-structurer。
找到满足全部必需依赖的解释器即返回，不重复安装。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
PROJECT = SKILL.parents[2]

# 包 import 名 → pip 名
# 必需：缺了就跑不起来
REQUIRED = {"pymupdf": "pymupdf", "pptx": "python-pptx"}
# 强烈建议：缺了关键能力会降级（OCR / 旧版 Office），但流程仍可跑完
RECOMMENDED = {"rapidocr": "rapidocr", "olefile": "olefile", "openpyxl": "openpyxl"}
# 可选：缺了只影响单项体验
OPTIONAL = {"pymupdf4llm": "pymupdf4llm", "docx": "python-docx",
            "yaml": "pyyaml", "pypinyin": "pypinyin"}

VENV_CANDIDATES = [PROJECT / ".venv-doc", PROJECT / ".venv-structurer"]


def probe() -> dict:
    def has(mod: str) -> bool:
        try:
            return importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            return False

    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "required": {m: has(m) for m in REQUIRED},
        "recommended": {m: has(m) for m in RECOMMENDED},
        "optional": {m: has(m) for m in OPTIONAL},
    }


def missing(rep: dict) -> tuple[list[str], list[str]]:
    req = [REQUIRED[m] for m, ok in rep["required"].items() if not ok]
    opt = [OPTIONAL[m] for m, ok in rep["optional"].items() if not ok]
    recom = [RECOMMENDED[m] for m, ok in (rep.get("recommended") or {}).items() if not ok]
    return req, recom + opt


def ok(rep: dict) -> bool:
    return all(rep["required"].values())


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_in(executable: str, code: str) -> dict | None:
    """在指定解释器里执行 probe 代码，返回其 JSON。"""
    try:
        out = subprocess.run([executable, "-c", code], capture_output=True, text=True, timeout=120)
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except Exception:  # noqa: BLE001
        return None
    return None


_PROBE_CODE = f"""
import importlib.util, json, sys
def has(m):
    try: return importlib.util.find_spec(m) is not None
    except Exception: return False
print(json.dumps({{"python": sys.version.split()[0], "executable": sys.executable,
  "required": {{m: has(m) for m in {list(REQUIRED)!r}}},
  "recommended": {{m: has(m) for m in {list(RECOMMENDED)!r}}},
  "optional": {{m: has(m) for m in {list(OPTIONAL)!r}}}}}))
"""


def find_ready_interpreter() -> tuple[str, dict] | None:
    for venv in VENV_CANDIDATES:
        py = venv_python(venv)
        if py.exists():
            rep = run_in(str(py), _PROBE_CODE)
            if rep and ok(rep):
                return str(py), rep
    rep = probe()
    if ok(rep):
        return sys.executable, rep
    if not all(rep.get("required", {}).values()) and rep.get("required"):
        # 当前解释器不完整，但 .venv-doc 可能只缺可选包 —— 返回它以便补装
        for venv in VENV_CANDIDATES:
            py = venv_python(venv)
            if py.exists():
                sub = run_in(str(py), _PROBE_CODE)
                if sub:
                    return str(py), sub
    return None


def install(pkgs: list[str], python: str) -> bool:
    if not pkgs:
        return True
    print(f"[check_env] 将使用 {python} 安装: {', '.join(pkgs)}")
    cmd = [python, "-m", "pip", "install", "--disable-pip-version-check", *pkgs]
    res = subprocess.run(cmd)
    return res.returncode == 0


def make_venv() -> str:
    venv = PROJECT / ".venv-structurer"
    py = venv_python(venv)
    if not py.exists():
        print(f"[check_env] 创建独立 venv: {venv}")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False)
    return str(py)


def ensure(auto: bool = False) -> str:
    """返回可用的 python 解释器路径。缺失且 auto=True 时自动安装。"""
    found = find_ready_interpreter()
    if found:
        return found[0]
    rep = probe()
    req, opt = missing(rep)
    target = sys.executable
    if req and not all(rep["required"].values()):
        cand = [venv_python(v) for v in VENV_CANDIDATES if venv_python(v).exists()]
        target = str(cand[0]) if cand else None
        if target is None:
            if not auto:
                _print_plan(req, opt, new_venv=True)
                raise SystemExit("缺少必需依赖，请运行: python check_env.py --install")
            target = make_venv()
    pkgs = req + opt
    if not pkgs:
        return target or sys.executable
    if not auto:
        _print_plan(req, opt, new_venv=False)
        raise SystemExit("缺少依赖，请运行: python check_env.py --install")
    if not install(pkgs, target):
        raise SystemExit(f"依赖安装失败，请手动执行: {target} -m pip install {' '.join(pkgs)}")
    return target


def _print_plan(req: list[str], opt: list[str], new_venv: bool) -> None:
    print("=" * 64)
    print("缺少以下依赖：")
    if req:
        print(f"  必需: {', '.join(req)}")
    if opt:
        print(f"  可选: {', '.join(opt)}  （缺失将降级：{_degrade(opt)}）")
    print(f"安装位置: {'新建 ' + str(PROJECT / '.venv-structurer') if new_venv else '现有 venv'}")
    print("不会修改系统 Python。确认后执行: python check_env.py --install")
    print("=" * 64)


def _degrade(opt: list[str]) -> str:
    notes = {
        "rapidocr": "扫描件与图片无法 OCR，只能标记 needs_ocr",
        "olefile": ".doc / .ppt 将登记为 unsupported",
        "openpyxl": ".xlsx 将登记为 unsupported",
        "pymupdf4llm": "正文退化为纯文本，保留标题层级能力丧失",
        "python-docx": ".docx 将登记为 unsupported",
        "pyyaml": "回退内置默认配置表",
        "pypinyin": "aliases_pinyin 写 null",
    }
    return "；".join(notes.get(o, o) for o in opt) or "无"


def main() -> int:
    ap = argparse.ArgumentParser(description="探测/准备运行环境")
    ap.add_argument("--install", action="store_true", help="打印清单并安装")
    ap.add_argument("--ensure", action="store_true", help="静默确保（自动安装）")
    args = ap.parse_args()

    if args.install:
        rep = probe()
        req, opt = missing(rep)
        all_pkgs = req + opt
        if not all_pkgs:
            print(json.dumps(probe(), ensure_ascii=False, indent=2))
            return 0
        _print_plan(req, opt, new_venv=bool(req and not all(rep["required"].values())))
        ans = input("继续安装? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("已取消")
            return 1
        target = sys.executable
        if req and not all(rep["required"].values()):
            cands = [venv_python(v) for v in VENV_CANDIDATES if venv_python(v).exists()]
            target = str(cands[0]) if cands else make_venv()
        return 0 if install(all_pkgs, target) else 1

    if args.ensure:
        print(ensure(auto=True))
        return 0

    print(json.dumps(probe(), ensure_ascii=False, indent=2))
    ready = find_ready_interpreter()
    if ready:
        print(f"\n可用解释器: {ready[0]}")
        return 0
    print("\n无可用解释器，请运行: python check_env.py --install")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""高频完工检查器——每次任务完成后跑一次，**无输出 = 全部通过**。

设计原则：
1. --quiet 模式下，无输出 = 全部通过（不消耗 agent 注意力）
2. 每条 FAIL 自带修复指引（agent 不需要记忆"失败后做什么"）
3. CHECKS 列表是检查项的单一权威源——AGENTS.md 只引用本脚本，不枚举覆盖范围
4. 只检查"本次任务是否遗漏了必做项"（~5项），不属于深度审计；深度审计交给 audit.py

与 audit.py 的分工：
    check_all.py  → 高频完工检查（每次任务后跑，静默，~5 项）
    audit.py      → 深度定期审计（每 ~20 次任务或每月跑，详实输出，~15 项）

用法：
    python scripts/check_all.py            # 全量输出
    python scripts/check_all.py --quiet    # 静默模式（完工清单默认用这个）
    python scripts/check_all.py --small    # 小型项目模式（跳过记忆/STRUCTURE 检查）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def _has_file(rel: str) -> bool:
    return (ROOT / rel).is_file()


def _file_lines(rel: str) -> int:
    try:
        return len((ROOT / rel).read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _run(name: str, cmd: list[str]) -> tuple[bool, str]:
    """Run a subprocess check. Returns (ok, stdout+stderr)."""
    proc = subprocess.run(
        [sys.executable, *cmd],
        cwd=str(ROOT),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


# 检查项：每个条目为 (名称, 判定函数, 修复指引)
# 判定函数返回 (ok: bool, detail: str)
CHECKS: list[tuple[str, callable, str]] = []


def _check_sync():
    ok, detail = _run("同步", ["scripts/agent_links.py", "check"])
    return ok, detail

CHECKS.append(("同步", _check_sync, "按 AGENTS.md「同步声明」中的精确命令修复"))


def _check_changelog():
    if not _has_file("docs/CHANGELOG.md"):
        return False, "docs/CHANGELOG.md 不存在"
    ok, detail = _run("CHANGELOG", ["scripts/changelog.py", "titles", "--limit", "1"])
    if not ok or not detail.strip():
        return False, detail or "CHANGELOG 无条目——本次任务如有值得记录的内容，用 scripts/changelog.py add 追加"
    return True, detail

CHECKS.append(("CHANGELOG", _check_changelog,
              "python scripts/changelog.py add --title \"...\" --body \"...\""))


def _check_line_budget():
    lines = _file_lines("AGENTS.md")
    ok = lines <= 250
    detail = f"AGENTS.md: {lines} 行"
    return ok, detail

CHECKS.append(("行数", _check_line_budget,
              f"超过 250 行——AGENTS.md 中有内容该下沉到 docs/ 或删除"))


def _check_memory_touch():
    """检查记忆系统最近是否有写入（中型+项目）。"""
    mem_dir = ROOT / ".agents" / "memory"
    if not mem_dir.is_dir():
        return True, ""  # 小型项目，无记忆系统
    # 检查 MEMORY.md 最近修改时间
    mem_file = mem_dir / "MEMORY.md"
    if not mem_file.is_file():
        return False, ".agents/memory/MEMORY.md 不存在——中型+项目需要记忆系统"
    stat = mem_file.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    age_days = (datetime.now(timezone.utc) - mtime).days
    if age_days > 14:
        return False, f"MEMORY.md 上次更新 {age_days} 天前——本次如有值得沉淀的记忆，请更新"
    return True, f"MEMORY.md {age_days} 天前更新"

CHECKS.append(("记忆", _check_memory_touch,
              "本次对话如有值得沉淀的记忆 → 更新 .agents/memory/ 并同步 AGENTS '项目记忆' 摘要"))


def _check_dead_links():
    if not _has_file("scripts/audit.py"):
        return True, ""
    ok, detail = _run("死链", ["scripts/audit.py", "dead-links"])
    return ok, detail

CHECKS.append(("死链", _check_dead_links,
              "检查标 dead 的链接目标是否确实不存在——可能是路径拼写或文件被移动"))


def _check_release():
    if not _has_file("scripts/build_release.py"):
        return True, ""
    return _run("发行包", ["scripts/check_release.py"])

CHECKS.append(("发行包", _check_release,
              "python scripts/check_release.py（检查白名单、默认配置、wheel 与 ZIP 布局）"))


def _check_update():
    if not _has_file("voice2text/update.py"):
        return True, ""
    return _run("一键更新", ["scripts/check_update.py"])

CHECKS.append(("一键更新", _check_update,
              "python scripts/check_update.py（检查版本、固定资产、摘要与 ZIP 安全边界）"))


def main() -> int:
    ap = argparse.ArgumentParser(description="高频完工检查器——无输出即通过")
    ap.add_argument("--quiet", action="store_true",
                    help="静默模式：只在有失败时输出")
    ap.add_argument("--small", action="store_true",
                    help="小型项目模式（跳过记忆检查）")
    args = ap.parse_args()

    # 如果是小型项目，跳过记忆检查
    checks_to_run = CHECKS
    if args.small:
        checks_to_run = [c for c in CHECKS if c[0] != "记忆"]

    failed: list[tuple[str, str]] = []
    for name, fn, guide in checks_to_run:
        ok, detail = fn()
        if not ok:
            failed.append((name, guide))
        if not args.quiet or not ok:
            status = "OK" if ok else "FAIL"
            if not args.quiet:
                print(f"\n[{status}] {name}")
                if detail:
                    print("    " + "\n    ".join(detail.splitlines()))
            elif not ok:
                print(f"\n[{status}] {name}")
                if detail:
                    print("    " + "\n    ".join(detail.splitlines()))

    if not failed:
        if not args.quiet:
            print(f"\n[PASS] 全部 {len(checks_to_run)} 项通过")
        return 0

    print(f"\n{'=' * 50}")
    print(f"共 {len(failed)} 项未通过，修复后重跑：")
    for name, guide in failed:
        print(f"  [{name}] → {guide}")
    print(f"{'=' * 50}")
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

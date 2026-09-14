"""maintain.py — 文档体系自动化维护管线（init-agent-docs，中型及以上项目）。

每次维护执行：
1. 重建 .agents/memory/MEMORY.md 的索引标记段
   （agent 只负责记忆的沉淀与检索；索引是纯派生信息，由本脚本机械维护。
    索引覆盖两类经验载体：.agents/memory/ 记忆条目 + docs/problems/bugfix/ 文档——
    后者是经验检索统一入口的一部分，bugfix 目录不存在时自动跳过）
2. 运行 audit.py check（死链 / 结构完整性 / 依赖漂移 / 记忆健康）
3. 运行 agent_links.py check（AGENTS / CLAUDE / GEMINI 同步一致性）
4. 记忆活性统计（30 天未更新预警，统计范围含 bugfix 文档）
5. 审计触发器（距上次审计裁决超过 30 天则 WARN 提醒；机械化的是"该审计了"，
   不是"文档是否陈旧"——治理文档正确性是事件驱动的，mtime 对比只会产生假警报）
6. 近期上下文摘要（git log + CHANGELOG 标题树，辅助 agent 快速恢复脉络）

用法：
    python scripts/maintain.py                 # 完整维护：重建索引 + 全部检查 + 报告
    python scripts/maintain.py --check         # 只读校验（不修改文件），异常时退出码非 0
    python scripts/maintain.py --memory-index  # 仅重建 MEMORY.md 索引标记段

无第三方依赖。小型项目（无 .agents/memory/ 目录）自动跳过记忆相关步骤。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Convention: this script lives at <project_root>/scripts/maintain.py.
ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = ROOT / ".agents" / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
BUGFIX_DIR = ROOT / "docs" / "problems" / "bugfix"
# 索引段中 bugfix 条目的链接前缀：相对 .agents/memory/MEMORY.md 所在目录解析
# （audit.py 死链检查按链接所在文件自身目录解析相对路径）
BUGFIX_LINK_PREFIX = "../../docs/problems/bugfix"

INDEX_START = "<!-- memory-index:start -->"
INDEX_END = "<!-- memory-index:end -->"
STALE_DAYS = 30
AUDIT_CHECKLIST = ROOT / "docs" / "audit-checklist.md"
AUDIT_STALE_DAYS = 30
MAX_TITLE_LEN = 60
GIT_LOG_LIMIT = 10


def _is_git_repo() -> bool:
    """Detect whether ROOT is inside a Git repository without calling git."""
    return (ROOT / ".git").exists() or any(
        (ancestor / ".git").exists()
        for ancestor in ROOT.parents
        if ancestor != ancestor.parent  # stop at filesystem root
    )

_REBUILT_LINE_RE = re.compile(r"^> 最近重建：.*\n?", re.MULTILINE)


# ---------------------------------------------------------------------------
# memory index
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _memory_files() -> list[Path]:
    if not MEMORY_DIR.is_dir():
        return []
    return sorted(
        p for p in MEMORY_DIR.rglob("*.md")
        if p.name != "MEMORY.md" and "__pycache__" not in p.parts
    )


def _entry_title(path: Path) -> str:
    """First ATX heading, else first non-empty line, else filename stem.

    跳过开头的 YAML frontmatter 块（--- ... ---），否则 frontmatter 文档
    的标题回退会取到 "---" 分隔线本身。
    """
    try:
        lines = _read(path).splitlines()
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    lines = lines[i + 1:]
                    break
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            m = re.match(r"^#+\s*(.+)$", stripped)
            title = (m.group(1) if m else stripped).strip()
            return title[:MAX_TITLE_LEN]
    except OSError:
        pass
    return path.stem


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# bugfix index (docs/problems/bugfix/)
# ---------------------------------------------------------------------------

def _bugfix_files() -> list[Path]:
    """Bugfix 文档清单；`_` 开头的文件（如 _template.md）是模板，不入索引。"""
    if not BUGFIX_DIR.is_dir():
        return []
    return sorted(
        p for p in BUGFIX_DIR.glob("*.md")
        if not p.name.startswith("_") and "__pycache__" not in p.parts
    )


def _frontmatter_value(text: str, key: str) -> str | None:
    """从文件开头的 YAML frontmatter 提取标量字段（零依赖，只认 `key: value` 行）。"""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    # 只认同行标量；空值返回 None（\s 会吞换行导致串读到下一行）
    m = re.search(rf"^{re.escape(key)}:[ \t]*(.*?)[ \t]*$", text[3:end], re.MULTILINE)
    if not m or not m.group(1):
        return None
    return m.group(1).strip("\"'")


def _bugfix_meta(path: Path) -> dict[str, str]:
    """提取索引行所需字段；frontmatter 缺失时回退到标题启发式。"""
    meta: dict[str, str] = {}
    try:
        text = _read(path)
    except OSError:
        return {"title": path.stem}
    for key in ("title", "status", "severity", "liveness", "updated_at", "created_at"):
        value = _frontmatter_value(text, key)
        if value:
            meta[key] = value
    meta.setdefault("title", _entry_title(path))
    return meta


def build_index_section() -> str:
    """Render the content that belongs between the index markers."""
    files = _memory_files()
    bugfix = _bugfix_files()
    lines = [
        "> 本段由 `python scripts/maintain.py` 自动重建，禁止手工编辑。",
        f"> 最近重建：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    if not files and not bugfix:
        lines.append("（暂无记忆条目）")
        return "\n".join(lines).rstrip()

    groups: dict[str, list[Path]] = {}
    for p in files:
        rel = p.relative_to(MEMORY_DIR)
        group = rel.parts[0] if len(rel.parts) > 1 else "未分类"
        groups.setdefault(group, []).append(p)

    for group in sorted(groups):
        lines.append(f"### {group}")
        entries = sorted(groups[group], key=lambda p: p.stat().st_mtime, reverse=True)
        for p in entries:
            rel = str(p.relative_to(MEMORY_DIR)).replace("\\", "/")
            line = (
                f"- [{p.name}]({rel}) — {_entry_title(p)} · 更新于 {_fmt_date(p.stat().st_mtime)}"
            )
            # 活性标记：有 frontmatter liveness 时追加；无 frontmatter 的旧记忆文件不追加（向后兼容）
            try:
                liveness = _frontmatter_value(_read(p), "liveness")
            except OSError:
                liveness = None
            if liveness:
                line += f" · {liveness}"
            lines.append(line)
        lines.append("")

    if bugfix:
        lines.append("### bugfix（docs/problems/bugfix/）")
        entries = sorted(bugfix, key=lambda p: p.stat().st_mtime, reverse=True)
        for p in entries:
            meta = _bugfix_meta(p)
            flags = " · ".join(
                meta[k] for k in ("status", "severity", "liveness") if meta.get(k)
            )
            date = meta.get("updated_at") or meta.get("created_at") or _fmt_date(p.stat().st_mtime)
            line = f"- [{meta['title'][:MAX_TITLE_LEN]}]({BUGFIX_LINK_PREFIX}/{p.name})"
            if flags:
                line += f" — {flags}"
            line += f" · 更新于 {date}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip()


def _normalize(text: str) -> str:
    """Strip the volatile rebuild timestamp so content comparison is stable."""
    return _REBUILT_LINE_RE.sub("", text)


def _splice_index(text: str, section: str) -> str | None:
    """Return updated MEMORY.md text, or None if markers are absent."""
    start = text.find(INDEX_START)
    end = text.find(INDEX_END)
    if start == -1 or end == -1 or end < start:
        return None
    end += len(INDEX_END)
    return text[:start] + INDEX_START + "\n" + section + "\n" + INDEX_END + text[end:]


def rebuild_memory_index(*, check_only: bool) -> tuple[str, str]:
    """Rebuild the MEMORY.md index marker section.

    Returns (status, detail); status ∈
    ok / rebuilt / stale / missing / no-markers / skip.
    """
    if not MEMORY_DIR.is_dir():
        return "skip", "no .agents/memory/ directory (small project)"
    if not MEMORY_INDEX.is_file():
        return "missing", ".agents/memory/MEMORY.md not found"
    current = _read(MEMORY_INDEX)
    updated = _splice_index(current, build_index_section())
    if updated is None:
        return "no-markers", f"MEMORY.md missing {INDEX_START} / {INDEX_END} markers"
    if _normalize(updated) == _normalize(current):
        return "ok", "memory index up to date"
    if check_only:
        return "stale", "memory index out of date — run: python scripts/maintain.py --memory-index"
    MEMORY_INDEX.write_text(updated, encoding="utf-8", newline="\n")
    return "rebuilt", "memory index rebuilt"


# ---------------------------------------------------------------------------
# memory staleness
# ---------------------------------------------------------------------------

def _memory_last_update_ts(files: list[Path]) -> float:
    """Last memory-update timestamp.

    git 不保留 mtime（fresh clone / checkout 会把 mtime 刷成当前时间），
    因此优先取 git 最后提交时间；非 git 环境回退到文件 mtime。
    """
    if _is_git_repo():
        try:
            proc = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "--",
                 ".agents/memory/", "docs/problems/bugfix/"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return float(proc.stdout.strip())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    pool = files + _bugfix_files()
    if not pool:
        return 0.0
    return max(p.stat().st_mtime for p in pool)


def memory_staleness() -> tuple[str, str]:
    """Returns (status, detail); status ∈ ok / stale / empty / skip."""
    if not MEMORY_DIR.is_dir():
        return "skip", "no .agents/memory/ directory (small project)"
    files = _memory_files()
    bugfix = _bugfix_files()
    if not files and not bugfix:
        return "empty", "no memory entries yet — 目录存在但从未沉淀记忆"
    age = datetime.now() - datetime.fromtimestamp(_memory_last_update_ts(files))
    total = len(files) + len(bugfix)
    time_source = "文件时间" if not _is_git_repo() else "git"
    if age > timedelta(days=STALE_DAYS):
        return (
            "stale",
            f"memory untouched for {age.days} days (> {STALE_DAYS}) — "
            "沉淀新记忆或考虑裁剪记忆系统",
        )
    return "ok", f"newest memory update {age.days}d ago ({total} entries, 含 {len(bugfix)} bugfix, {time_source})"


def audit_recency() -> tuple[str, str]:
    """审计触发器：距上次审计裁决超过阈值则提醒（WARN，不阻塞）。

    机械化的是"该做审计了"这个提醒，不是"文档是否陈旧"——治理文档的
    正确性是事件驱动的（环境变了才需要改），mtime 对比会产生假警报并
    诱发凑数编辑（Goodhart）。状态唯一来源是 audit-checklist.md 末尾
    「审计记录」段的日期：裁决过就追加记录，"已判断 = 已销警"。

    Returns (status, detail); status ∈ ok / warn / skip.
    """
    if not AUDIT_CHECKLIST.is_file():
        return "skip", "no docs/audit-checklist.md"
    text = _read(AUDIT_CHECKLIST)
    marker = "## 审计记录"
    section = text[text.find(marker):] if marker in text else text
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", section)
    if not dates:
        return (
            "warn",
            "审计记录段无任何日期——从未记录审计，请按 docs/audit-checklist.md 执行首次裁决",
        )
    last = max(datetime.strptime(d, "%Y-%m-%d") for d in dates)
    age = (datetime.now() - last).days
    if age > AUDIT_STALE_DAYS:
        return (
            "warn",
            f"距上次审计 {age} 天（> {AUDIT_STALE_DAYS}）——请按 docs/audit-checklist.md "
            "逐项裁决：过时就更新/删除，仍准确则只需在审计记录追加当日条目",
        )
    return "ok", f"last audit {age}d ago ({last.strftime('%Y-%m-%d')})"


# ---------------------------------------------------------------------------
# delegated checks (audit.py / agent_links.py)
# ---------------------------------------------------------------------------

def _run_script(rel: str, *args: str) -> tuple[int, str] | None:
    """Run a sibling script; None means the script is absent."""
    script = ROOT / rel
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 2, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


# ---------------------------------------------------------------------------
# recent-context digest
# ---------------------------------------------------------------------------

def _git_recent(limit: int = GIT_LOG_LIMIT) -> list[str]:
    if not _is_git_repo():
        return []
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", f"-{limit}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _changelog_recent() -> str | None:
    result = _run_script("scripts/changelog.py", "recent", "--days", "30")
    if result is None:
        return None
    rc, out = result
    return out if rc == 0 and out else None


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

_GLYPHS = {
    "ok": "OK",
    "rebuilt": "REBUILD",
    "stale": "STALE",
    "missing": "MISS",
    "no-markers": "NOMARK",
    "empty": "EMPTY",
    "skip": "SKIP",
    "fail": "FAIL",
    "warn": "WARN",
}


def _line(status: str, detail: str) -> str:
    return f"[{_GLYPHS.get(status, status.upper()):<8}] {detail}"


def run_full(*, check_only: bool) -> int:
    failures = 0
    print("== maintain.py 文档体系维护 ==")
    if check_only:
        print("（只读校验模式，不修改任何文件）")

    idx_status, idx_detail = rebuild_memory_index(check_only=check_only)
    print(_line(idx_status, f"memory index: {idx_detail}"))
    if idx_status in ("missing", "no-markers") or (check_only and idx_status == "stale"):
        failures += 1

    audit = _run_script("scripts/audit.py", "check")
    if audit is None:
        print(_line("skip", "audit.py not found"))
    else:
        rc, out = audit
        print(_line("ok" if rc == 0 else "fail", f"audit.py check (exit {rc})"))
        if out and rc != 0:
            for line in out.splitlines():
                print(f"           {line}")
        if rc != 0:
            failures += 1

    sync = _run_script("scripts/agent_links.py", "check")
    if sync is None:
        print(_line("skip", "agent_links.py not found"))
    else:
        rc, out = sync
        print(_line("ok" if rc == 0 else "fail", f"agent_links.py check (exit {rc})"))
        if out and rc != 0:
            for line in out.splitlines():
                print(f"           {line}")
        if rc != 0:
            failures += 1

    mem_status, mem_detail = memory_staleness()
    glyph_status = {"stale": "warn"}.get(mem_status, mem_status)
    print(_line(glyph_status, f"memory activity: {mem_detail}"))

    rec_status, rec_detail = audit_recency()
    print(_line(rec_status, f"audit recency: {rec_detail}"))

    if not check_only:
        git_lines = _git_recent()
        if git_lines:
            print("\n近期 git 提交：")
            for line in git_lines:
                print(f"  {line}")
        changelog = _changelog_recent()
        if changelog:
            print("\n近期 CHANGELOG：")
            for line in changelog.splitlines():
                print(f"  {line}")

    print()
    if failures:
        print(f"维护完成：{failures} 项需要处理")
        return 1
    print("维护完成：无异常")
    return 0


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="init-agent-docs 文档体系自动化维护管线"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只读校验：不修改文件，索引过期或检查失败时退出码非 0",
    )
    parser.add_argument(
        "--memory-index",
        action="store_true",
        help="仅重建 MEMORY.md 索引标记段",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.memory_index:
        status, detail = rebuild_memory_index(check_only=False)
        print(_line(status, f"memory index: {detail}"))
        return 0 if status in ("ok", "rebuilt", "skip") else 1
    return run_full(check_only=args.check)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main(sys.argv[1:]))

"""audit.py — 文档一致性机械检查 (token-light, read-only).

Checks that init-agent-docs initialized files have not rotted:
dead links, STRUCTURE index completeness, tech-stack drift between docs
and manifests, birth-record presence, AGENTS.md line budget, sync health.

All subcommands are read-only — this tool never modifies files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Convention: this script lives at <project_root>/scripts/audit.py.
ROOT = Path(__file__).resolve().parents[1]

MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
FENCED_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`[^`]+`")
HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")


def _strip_noise(text: str) -> str:
    """Remove fenced code blocks, inline code, and HTML comments."""
    text = FENCED_BLOCK_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("", text)
    return text

# Root-level instruction files always checked.
_ROOT_DOC_FILES = [
    "AGENTS.md",
    "docs/STRUCTURE.md",
]

# Dynamic discovery: all .md files under docs/ (excluding plans/ and __pycache__).
def _discover_doc_files() -> list[str]:
    """Discover all markdown files to check for dead links."""
    files = list(_ROOT_DOC_FILES)
    # Root-level README files (README.md, README-tools.md, etc.)
    for f in sorted(ROOT.glob("README*.md")):
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        if rel not in files:
            files.append(rel)
    # scripts/ README files
    scripts_dir = ROOT / "scripts"
    if scripts_dir.is_dir():
        for f in sorted(scripts_dir.glob("README*.md")):
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            if rel not in files:
                files.append(rel)
    docs_dir = ROOT / "docs"
    if docs_dir.is_dir():
        for f in sorted(docs_dir.rglob("*.md")):
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            # Include plan files (active + completed) for dead link checking.
            files.append(rel)
    return files

MANIFEST_GLOBS = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements*.txt",
    "setup.py",
    "setup.cfg",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "composer.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
]

# DRIFT_PATTERNS is a fixed heuristic, not a complete taxonomy. This is exactly the
# kind of 硬编码先验 that philosophy #8 warns against — but as a pragmatic starting
# seed it catches common drift without the complexity of a dynamic resolver. Projects
# should extend or replace these patterns for their specific stack. The --json output
# leaves interpretation to the agent, not the dictionary.
DRIFT_PATTERNS: dict[str, list[str]] = {
    "SQLite":            ["sqlite", "aiosqlite", "better-sqlite3", "sql.js"],
    "PostgreSQL":        ["postgres", "postgresql", "psycopg2", "psycopg", "pg", "pg-promise"],
    "MySQL":             ["mysql", "mariadb", "pymysql", "mysql2"],
    "MongoDB":           ["mongo", "mongodb", "mongoose", "pymongo"],
    "Redis":             ["redis", "ioredis", "aioredis"],
    "RabbitMQ":          ["rabbitmq", "amqp", "pika"],
    "Kafka":             ["kafka", "kafkajs", "confluent-kafka"],
    "Docker":            ["docker", "docker-compose", "dockerfile"],
    "Kubernetes":        ["kubernetes", "k8s", "kubectl", "helm"],
    "Elasticsearch":     ["elasticsearch", "elastic"],
    "GraphQL":           ["graphql", "apollo", "gql", "relay"],
    "gRPC":              ["grpc", "protobuf", "proto"],
    "WebSocket":         ["websocket", "ws", "socket.io", "sockjs"],
    "Celery":            ["celery"],
    "RQ":                ["rq", "django-rq"],
    "Nginx":             ["nginx"],
    "Caddy":             ["caddy"],
    "S3":                ["s3", "boto3", "minio", "aws-sdk"],
    "JWT":               ["jwt", "pyjwt", "jsonwebtoken", "jose"],
    "OAuth":             ["oauth", "oauth2", "oidc", "openid"],
    "Sentry":            ["sentry"],
    "Prometheus":        ["prometheus", "prom-client"],
    "Grafana":           ["grafana"],
    "Terraform":         ["terraform", "opentofu"],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return _read(path).splitlines()


def _exists(rel: str) -> bool:
    # 索引目标可以是目录（如 problems/bugfix/、plans/ 目录行）
    return (ROOT / rel).exists()


def _resolve(target: str, source_dir: Path) -> Path:
    """Resolve a markdown link target relative to the source file's directory.

    Per CommonMark spec, all paths are relative to the containing file except
    those starting with '/'. Absolute paths (/) are resolved against ROOT.
    """
    if target.startswith("/"):
        return (ROOT / target.lstrip("/")).resolve()
    return (source_dir / target).resolve()


def _find_manifests() -> list[Path]:
    found: list[Path] = []
    for g in MANIFEST_GLOBS:
        found.extend(ROOT.glob(g))
    return sorted(set(found))


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL
)


# Blockquote metadata pattern: lines starting with "> key : value" in the first 5 lines.
# Supports both ASCII colon (:) and full-width colon (：).
_BLOCKQUOTE_META_RE = re.compile(r"^>\s*(\S[^:：]+?)\s*[:：]\s*(.+)$")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse frontmatter from a plan file.

    Tries two formats in order:
    1. YAML frontmatter between --- delimiters (preferred, see plan.md.tpl).
    2. Blockquote metadata lines ("> key: value") within first 10 lines (legacy
       format from init-agent-docs < 2026-07-29).

    Returns a plain dict with lowercase keys. This is intentionally NOT a full
    YAML parser — it handles the subset used in plan files: key: value pairs.
    Multi-line values and YAML lists are NOT supported.
    """
    fm: dict[str, Any] = {}

    # Try format 1: YAML frontmatter (--- delimiters)
    m = _FRONTMATTER_RE.match(text)
    if m:
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            key, _, val = stripped.partition(":")
            # Strip inline YAML comments (e.g., "# in_progress | done | cancelled")
            clean_val = val.strip().split(" #", 1)[0].rstrip()
            k = key.strip().lower()
            # Normalize status values (Chinese → canonical, legacy aliases → canonical)
            if k == "status":
                clean_val = _normalize_status(clean_val)
            fm[k] = clean_val
        # If frontmatter has status, return now. Otherwise fall through so
        # blockquote metadata can supply the missing status field.
        if "status" in fm:
            return fm

    # Try format 2: blockquote metadata within first 10 lines (legacy).
    # 10 lines covers both standalone blockquote (lines 1-4) and the case
    # where YAML frontmatter pushes content down (lines 4-7).
    # Merges into fm — does not overwrite existing keys from format 1.
    _KEY_MAP_CN: dict[str, str] = {
        "状态": "status",
        "创建时间": "created_at",
        "模式": "mode",
        "协调人": "coordinator",
    }
    for line in text.splitlines()[:10]:
        bm = _BLOCKQUOTE_META_RE.match(line)
        if bm:
            raw_key, val = bm.group(1).strip(), bm.group(2).strip()
            mapped = _KEY_MAP_CN.get(raw_key)
            if not mapped:
                continue
            if mapped in fm:
                continue  # format 1 already has this key, don't overwrite
            if mapped == "status":
                fm["status"] = _normalize_status(val)
            else:
                fm[mapped] = val

    return fm


_STATUS_MAP: dict[str, str] = {
    "进行中": "in_progress",
    "已完成": "done",
    "已取消": "cancelled",
    # Legacy English aliases
    "completed": "done",
    "proposed": "in_progress",
}


def _normalize_status(val: str) -> str:
    """Normalize Chinese status values to machine-readable keys."""
    return _STATUS_MAP.get(val, val)


# ---------------------------------------------------------------------------
# link extraction
# ---------------------------------------------------------------------------

def _extract_file_links(text: str) -> list[tuple[str, str, int]]:
    """Return (target_path, display_text, line_number) for every local file link.

    Strips code blocks, inline code, and HTML comments before extraction to
    avoid false positives from example links and commented-out references.
    Line numbers are preserved relative to the original text.
    """
    clean = _strip_noise(text)
    links: list[tuple[str, str, int]] = []
    for lineno, line in enumerate(clean.splitlines(), 1):
        for m in MARKDOWN_LINK_RE.finditer(line):
            target = m.group(2).strip()
            if target.startswith(("http://", "https://", "#")):
                continue
            links.append((target, m.group(1).strip(), lineno))
    return links


# ---------------------------------------------------------------------------
# dead-links
# ---------------------------------------------------------------------------

def _check_dead_links() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for doc_rel in _discover_doc_files():
        path = ROOT / doc_rel
        if not path.is_file():
            continue
        source_dir = path.parent
        for target, _label, lineno in _extract_file_links(_read(path)):
            resolved = _resolve(target, source_dir)
            # 目录不算死链（docs/plans/、docs/problems/bugfix/ 等目录链接）
            exists = resolved.exists()
            results.append({
                "kind": "dead_link",
                "status": "ok" if exists else "dead",
                "source": doc_rel,
                "line": lineno,
                "target": target,
            })
    return results


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------

def _structure_table_links() -> list[tuple[str, str, int]]:
    """Parse docs/STRUCTURE.md index table: return (rel_path, label, lineno)."""
    path = ROOT / "docs" / "STRUCTURE.md"
    if not path.is_file():
        return []
    entries: list[tuple[str, str, int]] = []
    in_table = False
    for lineno, line in enumerate(_lines(path), 1):
        stripped = line.strip()
        if stripped.startswith("|") and "---" not in stripped.replace(" ", ""):
            if not in_table:
                in_table = True
                continue
            for m in MARKDOWN_LINK_RE.finditer(line):
                target = m.group(2).strip()
                if target.startswith(("http://", "https://", "#")):
                    continue
                entries.append((target, m.group(1).strip(), lineno))
        elif in_table and not stripped.startswith("|"):
            in_table = False
    return entries


def _check_structure() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    if not _exists("docs/STRUCTURE.md"):
        return results

    index_entries = _structure_table_links()
    # 索引表目标相对于 docs/（STRUCTURE.md 所在目录）；
    # 孤儿判定统一换算为仓库根相对路径再比较。
    indexed_paths = {"docs/" + e[0] for e in index_entries}

    # Check each indexed target exists.
    for target, _label, lineno in index_entries:
        if not _exists("docs/" + target):
            results.append({
                "kind": "structure",
                "status": "missing",
                "source": "docs/STRUCTURE.md",
                "line": lineno,
                "target": target,
            })
        else:
            results.append({
                "kind": "structure",
                "status": "ok",
                "source": "docs/STRUCTURE.md",
                "line": lineno,
                "target": target,
            })

    # Check for orphan files in docs/ not in index.
    docs_dir = ROOT / "docs"
    if docs_dir.is_dir():
        for f in sorted(docs_dir.rglob("*.md")):
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            if rel in indexed_paths:
                continue
            # Skip STRUCTURE.md itself — 索引表不登记自身。
            if rel == "docs/STRUCTURE.md":
                continue
            # Skip plan files — they are transient by design.
            if rel.startswith("docs/plans/"):
                continue
            # Skip audit-checklist itself.
            if rel == "docs/audit-checklist.md":
                continue
            # Skip bugfix docs — 逐篇索引由 maintain.py 派生到 MEMORY.md 索引段，
            # 与 plans/ 同理不逐篇登记进 STRUCTURE.md。
            if rel.startswith("docs/problems/bugfix/"):
                continue
            results.append({
                "kind": "structure",
                "status": "orphan",
                "source": "docs/STRUCTURE.md",
                "line": 0,
                "target": rel,
            })

    return results


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------

def _drift_check() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    manifests = _find_manifests()
    if not manifests:
        return results

    manifest_text = ""
    for m in manifests:
        try:
            manifest_text += " " + _read(m).lower()
        except Exception:
            continue

    doc_text = ""
    for doc_rel in ["docs/overview.md", "docs/deployment.md"]:
        p = ROOT / doc_rel
        if p.is_file():
            doc_text += " " + _read(p).lower()

    # Doc mentions → check manifest.
    for tech, keywords in DRIFT_PATTERNS.items():
        in_docs = tech.lower() in doc_text or any(kw in doc_text for kw in keywords)
        if not in_docs:
            continue
        in_manifest = any(kw in manifest_text for kw in keywords)
        if not in_manifest:
            results.append({
                "kind": "drift",
                "status": "drift",
                "tech": tech,
                "detail": f'Docs mention "{tech}" but no matching dependency found in manifests',
            })
        else:
            results.append({
                "kind": "drift",
                "status": "ok",
                "tech": tech,
                "detail": f'"{tech}" found in both docs and manifests',
            })

    # Manifest has → doc silent.
    for tech, keywords in DRIFT_PATTERNS.items():
        in_manifest = any(kw in manifest_text for kw in keywords)
        if not in_manifest:
            continue
        in_docs = tech.lower() in doc_text or any(kw in doc_text for kw in keywords)
        if not in_docs:
            results.append({
                "kind": "drift",
                "status": "undocumented",
                "tech": tech,
                "detail": f'Manifest has "{keywords[0]}" but docs never mention "{tech}"',
            })

    return results


# ---------------------------------------------------------------------------
# misc checks
# ---------------------------------------------------------------------------

def _check_birth_record() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    # Two valid locations depending on project size:
    # - Small: docs/initialization.md
    # - Medium/Large: docs/plans/completed/initialization.md
    small_path = "docs/initialization.md"
    medium_path = "docs/plans/completed/initialization.md"
    found = False
    for candidate in [small_path, medium_path]:
        if _exists(candidate):
            text = _read(ROOT / candidate)
            fm = _parse_frontmatter(text)
            size_val = fm.get("size", "")
            # Small birth records belong in docs/, not in plans/completed/.
            # Medium/Large birth records belong in plans/completed/.
            if candidate == medium_path and size_val == "small":
                results.append({
                    "kind": "birth_record",
                    "status": "invalid",
                    "path": candidate,
                    "detail": "small birth record in plans/completed/ (should be docs/initialization.md)",
                })
            elif candidate == small_path and size_val in ("medium", "large"):
                results.append({
                    "kind": "birth_record",
                    "status": "invalid",
                    "path": candidate,
                    "detail": f"{size_val} birth record in docs/ (should be {medium_path})",
                })
            else:
                results.append({
                    "kind": "birth_record",
                    "status": "found",
                    "path": candidate,
                })
            found = True
            break
    if not found:
        results.append({
            "kind": "birth_record",
            "status": "missing",
            "path": "docs/plans/completed/initialization.md or docs/initialization.md",
        })
    return results


def _check_line_budget() -> list[dict[str, Any]]:
    p = ROOT / "AGENTS.md"
    if not p.is_file():
        return [{"kind": "line_budget", "status": "missing", "lines": 0, "words": 0}]
    text = _read(p)
    line_count = len(text.splitlines())
    word_count = len(text.split())
    lines_ok = line_count <= 250
    words_ok = word_count <= 400
    if lines_ok and words_ok:
        status = "ok"
    else:
        status = "warn"
    return [{"kind": "line_budget", "status": status, "lines": line_count, "words": word_count}]


def _check_sync() -> list[dict[str, Any]]:
    script = ROOT / "scripts" / "agent_links.py"
    if not script.is_file():
        return [{"kind": "sync", "status": "skip", "detail": "agent_links.py not found"}]
    try:
        result = subprocess.run(
            [sys.executable, str(script), "check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [{"kind": "sync", "status": "error", "detail": str(exc)}]
    status = "ok" if result.returncode == 0 else "broken"
    return [{"kind": "sync", "status": status, "detail": result.stdout.strip() or result.stderr.strip()}]


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------

def _check_memory() -> list[dict[str, Any]]:
    """Check .agents/memory/ structure health.

    Small projects (no .agents/memory/ dir) are not an error — they skip.
    For projects with the directory, we verify:
    - MEMORY.md exists and is non-empty
    - AGENTS.md contains the pointer and inline section
    - Links in MEMORY.md resolve to existing files
    """
    results: list[dict[str, Any]] = []
    memory_dir = ROOT / ".agents" / "memory"

    # Small projects: memory dir absence is OK
    if not memory_dir.is_dir():
        results.append({
            "kind": "memory",
            "status": "skip",
            "detail": "No .agents/memory/ directory (small project or not enabled)",
        })
        return results

    # Check MEMORY.md exists
    mem_index = memory_dir / "MEMORY.md"
    if not mem_index.is_file():
        results.append({
            "kind": "memory",
            "status": "missing",
            "detail": ".agents/memory/MEMORY.md missing",
        })
        return results

    # Check MEMORY.md is not empty
    if mem_index.stat().st_size == 0:
        results.append({
            "kind": "memory",
            "status": "empty",
            "detail": ".agents/memory/MEMORY.md is empty",
        })

    # Check AGENTS.md contains memory pointer and inline section
    agents_md = ROOT / "AGENTS.md"
    if agents_md.is_file():
        content = _read(agents_md)
        if ".agents/memory/MEMORY.md" not in content:
            results.append({
                "kind": "memory",
                "status": "unlinked",
                "detail": "AGENTS.md missing pointer to .agents/memory/MEMORY.md",
            })
        if "## 项目记忆" not in content:
            results.append({
                "kind": "memory",
                "status": "unlinked",
                "detail": "AGENTS.md missing inline memory section",
            })

    # Check referenced memory files exist
    for target, _label, lineno in _extract_file_links(_read(mem_index)):
        resolved = _resolve(target, mem_index.parent)
        if not resolved.is_file():
            results.append({
                "kind": "memory",
                "status": "dead_link",
                "source": ".agents/memory/MEMORY.md",
                "line": lineno,
                "target": target,
            })

    if not results:
        results.append({
            "kind": "memory",
            "status": "ok",
            "detail": ".agents/memory/ structure healthy",
        })

    return results


# ---------------------------------------------------------------------------
# plans — check for stale plans in docs/plans/active/
# ---------------------------------------------------------------------------

_STALE_DAYS = 30  # plans older than this without modification are candidates


def _check_plans() -> list[dict[str, Any]]:
    """Check docs/plans/active/ and docs/plans/completed/ for misplaced or stale plans.

    Flags:
    - STALE (status=stale): plan in active/ with done/completed/cancelled status
      or legacy blockquote metadata format — should be moved or reformatted.
    - MISPLACED (status=misplaced): plan in completed/ with in_progress status
      — should be in active/.
    - LINGER (status=linger): plan is older than _STALE_DAYS without
      recent modification — possible candidate for archival review.
    """
    results: list[dict[str, Any]] = []
    plans_root = ROOT / "docs" / "plans"
    if not plans_root.is_dir():
        return results

    now = datetime.now(timezone.utc).timestamp()

    # Statuses valid in each directory.
    _DIR_VALID: dict[str, set[str]] = {
        "active": {"in_progress"},
        "completed": {"done", "cancelled"},
    }

    for folder in ("active", "completed"):
        folder_path = plans_root / folder
        if not folder_path.is_dir():
            continue
        valid_statuses = _DIR_VALID[folder]

        for f in sorted(folder_path.glob("*.md")):
            if f.name == ".gitkeep":
                continue
            rel = str(f.relative_to(ROOT)).replace("\\", "/")
            text = _read(f)
            fm = _parse_frontmatter(text)
            status_val = fm.get("status", "")

            # Check 1: status not valid for this directory → misplaced or stale
            if status_val and status_val not in valid_statuses:
                target_dir = "completed/" if status_val in ("done", "cancelled") else "active/"
                kind = "stale" if folder == "active" else "misplaced"
                results.append({
                    "kind": "plans",
                    "status": kind,
                    "file": rel,
                    "detail": f'Frontmatter status="{status_val}" in {folder}/'
                              f' — move to docs/plans/{target_dir}',
                })
                continue

            # Check 2: legacy blockquote metadata format in active/ → stale
            if folder == "active" and not _FRONTMATTER_RE.match(text):
                if any(_BLOCKQUOTE_META_RE.match(line) for line in text.splitlines()[:10]):
                    results.append({
                        "kind": "plans",
                        "status": "stale",
                        "file": rel,
                        "detail": "Legacy blockquote metadata format — migrate to YAML frontmatter",
                    })
                    continue

            # Check 3: file older than _STALE_DAYS → linger warning
            try:
                mtime = f.stat().st_mtime
                age_days = (now - mtime) / 86400
            except OSError:
                age_days = 0.0

            if age_days > _STALE_DAYS:
                results.append({
                    "kind": "plans",
                    "status": "linger",
                    "file": rel,
                    "detail": f'File not modified in {int(age_days)} days'
                              f' (threshold: {_STALE_DAYS}d)'
                              f' — review and either archive or update frontmatter status',
                })
                continue

            # All clear
            results.append({
                "kind": "plans",
                "status": "ok",
                "file": rel,
                "detail": "",
            })

    return results


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------

def _run_all() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    results.extend(_check_dead_links())
    results.extend(_check_structure())
    results.extend(_drift_check())
    results.extend(_check_birth_record())
    results.extend(_check_line_budget())
    results.extend(_check_sync())
    results.extend(_check_memory())
    results.extend(_check_plans())
    return results


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

_STATUS_GLYPHS: dict[str, str] = {
    "ok":          "OK",
    "dead":        "DEAD",
    "missing":     "MISS",
    "orphan":      "ORPHAN",
    "drift":       "DRIFT",
    "undocumented":"UNDOC",
    "warn":        "WARN",
    "found":       "FOUND",
    "broken":      "BROKEN",
    "error":       "ERROR",
    "skip":        "SKIP",
    "empty":       "EMPTY",
    "unlinked":    "UNLINK",
    "stale":       "STALE",
    "linger":      "LINGER",
    "misplaced":   "MISPLACED",
    "invalid":     "INVALID",
}


def _format_text(results: list[dict[str, Any]], verbose: bool = False) -> str:
    lines_out: list[str] = []
    for r in results:
        if not verbose and r["status"] in ("ok", "found"):
            continue
        glyph = _STATUS_GLYPHS.get(r["status"], r["status"].upper())
        kind = r["kind"]

        if kind == "dead_link":
            lines_out.append(
                f"[{glyph:<6}] {r['source']}:{r['line']} -> {r['target']}"
            )
        elif kind == "structure":
            if r["status"] == "orphan":
                lines_out.append(
                    f"[{glyph:<6}] docs/STRUCTURE.md — not in index: {r['target']}"
                )
            elif r["status"] == "missing":
                lines_out.append(
                    f"[{glyph:<6}] docs/STRUCTURE.md:{r['line']} -> {r['target']} (file missing)"
                )
        elif kind == "drift":
            lines_out.append(f"[{glyph:<6}] {r['detail']}")
        elif kind == "birth_record":
            if r["status"] == "missing":
                lines_out.append(f"[{glyph:<6}] Birth record missing: {r['path']}")
            else:
                lines_out.append(f"[{glyph:<6}] Birth record: {r['path']}")
        elif kind == "line_budget":
            if r["status"] == "missing":
                lines_out.append("[MISS  ] AGENTS.md not found")
            elif r["status"] == "warn":
                lines_out.append(
                    f"[WARN   ] AGENTS.md: {r['lines']} lines / {r['words']} words (limit 250/400)"
                )
            else:
                lines_out.append(
                    f"[OK    ] AGENTS.md: {r['lines']} lines / {r['words']} words (limit 250/400)"
                )
        elif kind == "sync":
            if r["status"] == "broken":
                lines_out.append(f"[BROKEN ] AGENTS.md/CLAUDE.md/GEMINI.md out of sync")
            elif r["status"] == "error":
                lines_out.append(f"[ERROR  ] sync check failed: {r['detail']}")
            elif r["status"] == "skip":
                lines_out.append("[SKIP   ] sync check (agent_links.py unavailable)")
        elif kind == "memory":
            if r["status"] == "skip":
                lines_out.append("[SKIP   ] memory (no .agents/memory/ directory)")
            elif r["status"] == "ok":
                if verbose:
                    lines_out.append("[OK    ] memory structure healthy")
            elif r["status"] == "dead_link":
                lines_out.append(
                    f"[DEAD   ] {r['source']}:{r['line']} -> {r['target']}"
                )
            else:
                lines_out.append(f"[{glyph:<6}] memory: {r['detail']}")
        elif kind == "plans":
            if r["status"] == "stale":
                lines_out.append(f"[STALE  ] {r['file']}: {r['detail']}")
            elif r["status"] == "misplaced":
                lines_out.append(f"[MISPL  ] {r['file']}: {r['detail']}")
            elif r["status"] == "linger":
                lines_out.append(f"[LINGER ] {r['file']}: {r['detail']}")
            elif r["status"] == "ok" and verbose:
                lines_out.append(f"[OK    ] {r['file']}")
    return "\n".join(lines_out)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _cmd_check(args: argparse.Namespace) -> None:
    results = _run_all()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_text(results, verbose=args.verbose))

    has_issues = any(r["status"] not in ("ok", "found", "skip") for r in results)
    if has_issues:
        raise SystemExit(1)


def _cmd_dead_links(args: argparse.Namespace) -> None:
    results = _check_dead_links()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_text(results, verbose=args.verbose))
    if any(r["status"] != "ok" for r in results):
        raise SystemExit(1)


def _cmd_structure(args: argparse.Namespace) -> None:
    results = _check_structure()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_text(results, verbose=args.verbose))
    if any(r["status"] != "ok" for r in results):
        raise SystemExit(1)


def _cmd_drift(args: argparse.Namespace) -> None:
    results = _drift_check()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_text(results, verbose=args.verbose))
    if any(r["status"] not in ("ok",) for r in results):
        raise SystemExit(1)


def _cmd_plans(args: argparse.Namespace) -> None:
    results = _check_plans()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_text(results, verbose=args.verbose))
    has_issues = any(r["status"] not in ("ok",) for r in results)
    if has_issues:
        raise SystemExit(1)


def _cmd_memory(args: argparse.Namespace) -> None:
    results = _check_memory()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_text(results, verbose=args.verbose))
    if any(r["status"] not in ("ok", "skip") for r in results):
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="init-agent-docs document consistency mechanical checks"
    )
    sub = parser.add_subparsers(dest="command")

    p_check = sub.add_parser("check", help="Run all checks")
    p_check.add_argument("--json", action="store_true", help="Output JSON")
    p_check.add_argument("--verbose", action="store_true", help="Show OK entries")
    p_check.set_defaults(func=_cmd_check)

    p_dead = sub.add_parser("dead-links", help="Dead link check only")
    p_dead.add_argument("--json", action="store_true", help="Output JSON")
    p_dead.add_argument("--verbose", action="store_true", help="Show OK entries")
    p_dead.set_defaults(func=_cmd_dead_links)

    p_struct = sub.add_parser("structure", help="STRUCTURE index check only")
    p_struct.add_argument("--json", action="store_true", help="Output JSON")
    p_struct.add_argument("--verbose", action="store_true", help="Show OK entries")
    p_struct.set_defaults(func=_cmd_structure)

    p_drift = sub.add_parser("drift", help="Dependency drift check only")
    p_drift.add_argument("--json", action="store_true", help="Output JSON")
    p_drift.add_argument("--verbose", action="store_true", help="Show OK entries")
    p_drift.set_defaults(func=_cmd_drift)

    p_mem = sub.add_parser("memory", help="Memory structure check only")
    p_mem.add_argument("--json", action="store_true", help="Output JSON")
    p_mem.add_argument("--verbose", action="store_true", help="Show OK entries")
    p_mem.set_defaults(func=_cmd_memory)

    p_plans = sub.add_parser("plans", help="Check for stale/unarchived plans only")
    p_plans.add_argument("--json", action="store_true", help="Output JSON")
    p_plans.add_argument("--verbose", action="store_true", help="Show OK entries")
    p_plans.set_defaults(func=_cmd_plans)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)
    args.func(args)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    main(sys.argv[1:])

"""在无 Git 的分发包中，以随包基线生成反馈 Markdown 和统一源码 diff。"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "source-baseline.zip"
MAX_SOURCE_BYTES = 2 * 1024 * 1024


def _version() -> str:
    source = (ROOT / "voice2text" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)', source, re.MULTILINE)
    return match.group(1) if match else "unknown"


def _safe_source(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or ".." in parts or path.startswith("/") or "\\" in path or ":" in path:
        return False
    if path in {"AGENTS.md", "requirements.txt", "run_gui.pyw"}:
        return True
    if len(parts) == 1 and path.endswith(".bat"):
        return True
    if len(parts) == 2 and parts[0] == "voice2text" and path.endswith(".py"):
        return True
    if len(parts) == 2 and parts[0] == "scripts" and path.endswith((".py", ".ps1")):
        return True
    return False


def _source_paths(baseline: zipfile.ZipFile) -> set[str]:
    paths = set(baseline.namelist())
    if not paths or any(not _safe_source(path) for path in paths):
        raise ValueError("发行源码基线包含无效路径")
    for folder in ("voice2text", "scripts"):
        for file in (ROOT / folder).glob("*.py"):
            paths.add(file.relative_to(ROOT).as_posix())
    return paths


def _unified(path: str, before: bytes, after: bytes) -> str:
    old = before.decode("utf-8").splitlines()
    new = after.decode("utf-8").splitlines()
    fromfile = f"a/{path}" if before else "/dev/null"
    tofile = f"b/{path}" if after else "/dev/null"
    lines = list(difflib.unified_diff(old, new, fromfile=fromfile, tofile=tofile, lineterm=""))
    return f"diff --git a/{path} b/{path}\n" + "\n".join(lines) + "\n" if lines else ""


def export(output_dir: Path, summary: str = "", steps: str = "", expected: str = "",
           actual: str = "", validation: str = "") -> tuple[Path, Path]:
    if not BASELINE.is_file():
        raise FileNotFoundError("缺少 source-baseline.zip；请从完整分发包解压后重试")
    changes = []
    patches = []
    with zipfile.ZipFile(BASELINE) as baseline:
        if baseline.testzip() is not None:
            raise ValueError("发行源码基线损坏")
        baseline_names = set(baseline.namelist())
        for rel in sorted(_source_paths(baseline)):
            before = baseline.read(rel) if rel in baseline_names else b""
            path = ROOT / rel
            after = path.read_bytes() if path.is_file() else b""
            if len(before) > MAX_SOURCE_BYTES or len(after) > MAX_SOURCE_BYTES:
                raise ValueError(f"源码文件异常大，未导出：{rel}")
            if before != after:
                changes.append(rel)
                patches.append(_unified(rel, before, after))
    output_dir.mkdir(parents=True, exist_ok=False)
    diff_path = output_dir / "修复.diff"
    report_path = output_dir / "反馈.md"
    diff_path.write_text("".join(patches), encoding="utf-8")
    baseline_digest = hashlib.sha256(BASELINE.read_bytes()).hexdigest()
    field = lambda value: value.strip() or "[待填写]"
    report = (
        "# voice2text 分发端反馈\n\n"
        f"- 版本：v{_version()}\n"
        f"- 系统：Windows {platform.release()}（{platform.machine()}）\n"
        f"- Python：{sys.version.split()[0]}\n"
        f"- 源码基线 SHA-256：`{baseline_digest}`\n\n"
        f"## 问题概述\n\n{field(summary)}\n\n"
        f"## 复现步骤\n\n{field(steps)}\n\n"
        f"## 期望结果\n\n{field(expected)}\n\n"
        f"## 实际结果\n\n{field(actual)}\n\n"
        f"## 修复后验证\n\n{field(validation)}\n\n"
        "## 关键运行输出\n\n[只粘贴相关片段；发送前删除个人信息和听写内容]\n\n"
        "## 修改文件\n\n"
        + ("".join(f"- `{path}`\n" for path in changes) if changes else "（无源码修改）\n")
        + "\n补丁见同目录 `修复.diff`。发送前请人工检查两份文件。\n"
    )
    report_path.write_text(report, encoding="utf-8")
    return report_path, diff_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--summary", default="")
    parser.add_argument("--steps", default="")
    parser.add_argument("--expected", default="")
    parser.add_argument("--actual", default="")
    parser.add_argument("--validation", default="")
    args = parser.parse_args()
    output_dir = args.output_dir or ROOT / "feedback" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    report, diff = export(output_dir, args.summary, args.steps, args.expected,
                          args.actual, args.validation)
    print(report)
    print(diff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

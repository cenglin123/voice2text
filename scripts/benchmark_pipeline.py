"""离线听写链路基线：不采集麦克风、不向用户窗口注入按键。

默认跑 30 轮 partial 刷新和 10 轮真实本地校对，输出单个 JSON 报告。用
--no-proofread 可只测轻量路径；--source-root 可比较临时 worktree 的实现。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {
    "short_chinese": "今天下午三点开会请提醒我准备资料",
    "long_chinese": "最近连续使用语音输入时发现文字更新有时不够稳定希望能够保持实时显示并在停止后自动添加合适的标点符号",
}
PARTIALS = (
    "识别文字",
    "识别文字是不是实时",
    "识别文本是不是实时",
    "识别文本是不是实时的",
    "识别文本是不是实时的呢",
)


def _p95(values: list[int]) -> float | None:
    if len(values) < 20:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))] / 1_000_000


def _summary(values: list[int]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "median_ms": round(median(values) / 1_000_000, 3),
        "p95_ms": None if _p95(values) is None else round(_p95(values) or 0, 3),
        "max_ms": round(max(values) / 1_000_000, 3),
    }


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _revision(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip()
    except Exception:
        return None


def _worktree_state(root: Path) -> dict[str, str | bool | None]:
    try:
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True, encoding="utf-8"
        )
    except Exception:
        dirty = ""
    return {"head": _revision(root), "dirty": bool(dirty), "porcelain": dirty or None}


def _measure_partial(source_root: Path, repeats: int) -> dict:
    from voice2text import keysender
    from voice2text.input import TextInserter

    destination = Mock()
    destination.restore.return_value = True
    destination.focused.return_value = True
    screen = [""]
    inserted = [0]
    removed = [0]

    def send_text(value, guard):
        guard()
        screen[0] += value
        inserted[0] += len(value)

    def send_backspaces(count, guard):
        guard()
        screen[0] = screen[0][:-count] if count else screen[0]
        removed[0] += count

    durations: list[int] = []
    with patch.object(keysender, "send_text", side_effect=send_text), \
         patch.object(keysender, "send_backspaces", side_effect=send_backspaces):
        for _ in range(repeats):
            screen[0] = ""
            inserter = TextInserter()
            inserter.begin_session(destination)
            for partial in PARTIALS:
                started = perf_counter_ns()
                assert inserter.replace_current(partial)
                durations.append(perf_counter_ns() - started)
            assert screen[0] == PARTIALS[-1]
    return {
        "timing": _summary(durations),
        "repeats": repeats,
        "events": len(durations),
        "inserted_chars": inserted[0],
        "backspaced_chars": removed[0],
        "final_text_matches": True,
    }


def _measure_proofread(cfg, runs: int) -> dict:
    from voice2text.proofread import Proofreader

    started = perf_counter_ns()
    proofreader = Proofreader(cfg)
    load_ns = perf_counter_ns() - started
    reports = {}
    for name, text in SAMPLES.items():
        values: list[int] = []
        internal_punctuation = 0
        terminal_punctuation = 0
        for _ in range(runs):
            started = perf_counter_ns()
            result = proofreader.proofread(text)
            values.append(perf_counter_ns() - started)
            if result:
                internal_punctuation += int(any(mark in result[:-1] for mark in "，、；：！？,.?!"))
                terminal_punctuation += int(result.endswith(("。", "！", "？", ".", "!", "?")))
        reports[name] = {
            "timing": _summary(values),
            "internal_punctuation_results": internal_punctuation,
            "terminal_punctuation_results": terminal_punctuation,
        }
    return {
        "model_load_ms": round(load_ns / 1_000_000, 3),
        "runs_per_sample": runs,
        "samples": reports,
        "model_sha256": _sha256(cfg.llm_model_path),
        "n_threads": min(8, __import__("os").cpu_count() or 4),
    }


def _measure_recorder() -> dict:
    try:
        from voice2text.performance import PerformanceRecorder
    except ModuleNotFoundError:
        return {"available": False}

    recorder = PerformanceRecorder()
    values = []
    for _ in range(1000):
        started = perf_counter_ns()
        recorder.record("micro", 100)
        values.append(perf_counter_ns() - started)
    return {"available": True, "timing": _summary(values)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--partial-repeats", type=int, default=30)
    parser.add_argument("--proofread-runs", type=int, default=10)
    parser.add_argument(
        "--model-path", type=Path,
        help="校对模型路径；比较 worktree 时指定当前已安装模型的绝对路径。",
    )
    parser.add_argument("--no-proofread", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise SystemExit(f"source root not found: {source_root}")
    sys.path.insert(0, str(source_root))
    from voice2text.config import load_config

    cfg = load_config(source_root / "config.json")
    if args.model_path:
        cfg.llm_model_path = args.model_path.resolve()
    report = {
        "schema": "voice2text.performance.v1",
        "clock": "perf_counter_ns",
        "source_root": str(source_root),
        "worktree": _worktree_state(source_root),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "llama_cpp": _version("llama-cpp-python"),
            "sherpa_onnx": _version("sherpa-onnx"),
            "endpoint_pause_seconds": cfg.endpoint_pause_seconds,
        },
        "partial": _measure_partial(source_root, args.partial_repeats),
        "recorder_overhead": _measure_recorder(),
    }
    if not args.no_proofread:
        report["proofread"] = _measure_proofread(cfg, args.proofread_runs)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()

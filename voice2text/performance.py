"""会话内低开销性能采样：只记录耗时与结果码，不保留语音或文本。"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from statistics import median
from time import perf_counter_ns
from typing import Iterator


class PerformanceRecorder:
    """线程安全依赖 GIL 的有界事件环；热路径不做 I/O。"""

    def __init__(self, capacity: int = 4096) -> None:
        self._events: deque[tuple[str, int, str]] = deque(maxlen=capacity)
        self._dropped = 0
        self._capacity = capacity

    def reset(self) -> None:
        self._events.clear()
        self._dropped = 0

    def record(self, stage: str, elapsed_ns: int, result: str = "ok") -> None:
        if len(self._events) == self._capacity:
            self._dropped += 1
        self._events.append((stage, max(0, elapsed_ns), result))

    @contextmanager
    def measure(self, stage: str, result: str = "ok") -> Iterator[None]:
        started = perf_counter_ns()
        try:
            yield
        finally:
            self.record(stage, perf_counter_ns() - started, result)

    def summary(self) -> dict[str, dict[str, float | int | dict[str, int]]]:
        grouped: dict[str, list[int]] = {}
        results: dict[str, dict[str, int]] = {}
        # deque 的 append 在热路径不加锁；汇总取瞬时快照，避免 worker 收尾时迭代失效。
        for stage, elapsed, result in tuple(self._events):
            grouped.setdefault(stage, []).append(elapsed)
            stage_results = results.setdefault(stage, {})
            stage_results[result] = stage_results.get(result, 0) + 1
        report: dict[str, dict[str, float | int | dict[str, int]]] = {}
        for stage, values in grouped.items():
            values.sort()
            count = len(values)
            p95_index = min(count - 1, round((count - 1) * 0.95))
            report[stage] = {
                "count": count,
                "median_ms": round(median(values) / 1_000_000, 3),
                "p95_ms": round(values[p95_index] / 1_000_000, 3) if count >= 20 else -1.0,
                "max_ms": round(values[-1] / 1_000_000, 3),
                "results": results[stage],
            }
        return report

    def format_summary(self) -> str:
        rows = []
        for stage, values in self.summary().items():
            p95 = "n/a" if values["p95_ms"] == -1 else f"{values['p95_ms']:.1f}ms"
            results = ",".join(f"{key}={count}" for key, count in values["results"].items())
            rows.append(
                f"{stage}: n={values['count']} med={values['median_ms']:.1f}ms "
                f"p95={p95} max={values['max_ms']:.1f}ms [{results}]"
            )
        suffix = f"；环形缓冲覆盖 {self._dropped} 条" if self._dropped else ""
        return " | ".join(rows) + suffix

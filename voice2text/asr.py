"""sherpa-onnx 流式识别。

关键语义（docs/overview.md「流式 partial 为什么整句刷新」）：
- get_result() 返回当前句的累计假设文本，解码中尾部会自我修正——消费方必须整句替换
- endpoint（rule2 停顿阈值）触发后当前句锁定、reset 开始新句；Alt+V 停止时
  input_finished() 后做最终解码，尾句照常产出（见计划阶段 4 停止语义）
"""

from __future__ import annotations

import queue
import threading
from time import perf_counter_ns

import numpy as np
import sherpa_onnx

from voice2text.config import AppConfig


class StreamingASR:
    """流式识别器：线程安全由使用方保证（一个会话一个 stream，单线程驱动）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._sample_rate = cfg.sample_rate
        self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(cfg.asr_file("tokens.txt")),
            encoder=str(cfg.asr_file("encoder-epoch-99-avg-1.onnx")),
            decoder=str(cfg.asr_file("decoder-epoch-99-avg-1.onnx")),
            joiner=str(cfg.asr_file("joiner-epoch-99-avg-1.onnx")),
            num_threads=2,
            sample_rate=cfg.sample_rate,
            feature_dim=80,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=cfg.endpoint_pause_seconds,
            rule3_min_utterance_length=20.0,
        )

    @property
    def recognizer(self) -> sherpa_onnx.OnlineRecognizer:
        return self._recognizer

    def decode(self, stream: sherpa_onnx.OnlineStream) -> str:
        """推进解码到无新帧可解，返回当前句累计文本。"""
        while self._recognizer.is_ready(stream):
            self._recognizer.decode_stream(stream)
        return self._recognizer.get_result(stream) or ""


class ASRSessionWorker(threading.Thread):
    """一次听写会话的识别线程。

    消费 MicrophoneCapture.queue（None 为流结束哨兵），驱动两个回调：
    - on_partial(text)：当前句累计假设更新（仅在文本变化时回调）
    - on_sentence(text)：endpoint 锁句 / 流结束时产出定稿句子
    回调在本线程执行；上屏等 UI 操作在回调内完成，需要 COM 的调用方自行初始化。
    """

    def __init__(
        self,
        asr: StreamingASR,
        audio_queue: "queue.Queue[np.ndarray | None]",
        sample_rate: int,
        on_partial,
        on_sentence,
        punctuator=None,
        metrics=None,
    ) -> None:
        super().__init__(daemon=True, name="asr-worker")
        self._asr = asr
        self._queue = audio_queue
        self._sample_rate = sample_rate
        self._on_partial = on_partial
        self._on_sentence = on_sentence
        self._punctuator = punctuator
        self._metrics = metrics
        self._last_partial = ""
        self.error: str | None = None  # 识别线程致命异常（上屏 IO 失败等），主循环据此善后

    def run(self) -> None:
        # 回调链会走到 uiautomation（COM）——工作线程必须各自初始化 COM
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:  # noqa: BLE001 —— pywin32 不可用时上屏检测自动退化为默认放行
            pass
        try:
            self._run_loop()
        except Exception as exc:  # noqa: BLE001 —— daemon 线程异常不能静默死亡（会话假活）
            self.error = f"识别线程异常退出：{exc}"

    def _run_loop(self) -> None:
        stream = self._asr.recognizer.create_stream()
        while True:
            wait_started = perf_counter_ns()
            try:
                chunk = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue  # 无新音频时轻轮询（保留未来取消会话的扩展点）
            if self._metrics is not None:
                self._metrics.record("audio_queue_wait", perf_counter_ns() - wait_started)
            if chunk is None:
                break
            stream.accept_waveform(self._sample_rate, chunk)
            decode_started = perf_counter_ns()
            text = self._asr.decode(stream)
            if self._metrics is not None:
                self._metrics.record("asr_decode", perf_counter_ns() - decode_started)
            if text and text != self._last_partial:
                self._last_partial = text
                self._on_partial(text)
            if self._asr.recognizer.is_endpoint(stream):
                self._finish_sentence(stream)
        # 流结束（Alt+V 停止）：尾句最终解码后产出
        stream.input_finished()
        decode_started = perf_counter_ns()
        final = self._asr.decode(stream)
        if self._metrics is not None:
            self._metrics.record("asr_final_decode", perf_counter_ns() - decode_started)
        if final:
            self._deliver_sentence(final)

    def _finish_sentence(self, stream: sherpa_onnx.OnlineStream) -> None:
        decode_started = perf_counter_ns()
        text = self._asr.decode(stream)
        if self._metrics is not None:
            self._metrics.record("asr_endpoint_decode", perf_counter_ns() - decode_started)
        if text:
            self._deliver_sentence(text)
        self._asr.recognizer.reset(stream)
        self._last_partial = ""

    def _deliver_sentence(self, text: str) -> None:
        """先同步 ASR 原文，再以只加标点的版本锁句。"""
        self._on_partial(text)
        self._on_sentence(self._restore_punctuation(text))

    def _restore_punctuation(self, text: str) -> str:
        if self._punctuator is None:
            return text
        started = perf_counter_ns()
        result, outcome = self._punctuator.restore(text)
        if self._metrics is not None:
            self._metrics.record("punctuation_restore", perf_counter_ns() - started, outcome)
        return result

"""麦克风采集：优先 16kHz 单声道直采；设备不支持时以设备默认采样率打开再重采样到 16kHz。

识别模型吃 16kHz；蓝牙免提等设备可能只支持 8kHz/48kHz，直采 16k 会失败——
这正是回退路径存在的原因（对齐 sherpa-onnx 官方麦克风示例的做法）。
输出 float32 单声道 PCM 块到队列；停止时放入 None 哨兵标记流的结束。
"""

from __future__ import annotations

import queue
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from voice2text.config import PROJECT_ROOT

TARGET_RATE = 16000
_BLOCK_SIZE = 4000  # 约 0.25s @16kHz，识别粒度够细且回调开销小
WATCHDOG_SECONDS = 3.0  # 会话中超过此时长无回调视为设备无响应/断开
DEBUG_CAPTURE_PATH = (PROJECT_ROOT / "debug_capture.wav").absolute()


class CaptureError(RuntimeError):
    """采集失败（设备缺失/被占用/打开失败），message 面向用户可读。"""


def list_input_devices() -> list[tuple[int, str, float]]:
    """可用输入设备列表 [(索引, 名称, 默认采样率)]，用于错误提示。"""
    devices: list[tuple[int, str, float]] = []
    for idx, dev in enumerate(sd.query_devices()):  # type: ignore[union-attr]
        if dev["max_input_channels"] > 0:
            devices.append((idx, str(dev["name"]), float(dev["default_samplerate"])))
    return devices


def _resample(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """线性插值重采样。分块处理会在块边界损失一点连续性，对语音识别可接受。"""
    if src_rate == dst_rate:
        return x
    n_out = int(round(len(x) * dst_rate / src_rate))
    src_pos = np.arange(len(x), dtype=np.float64)
    dst_pos = np.linspace(0.0, len(x) - 1.0, n_out)
    return np.interp(dst_pos, src_pos, x.astype(np.float64)).astype(np.float32)


class MicrophoneCapture:
    """一次 start/stop 周期代表一段听写会话。线程安全：回调线程写入，消费线程读取。"""

    def __init__(self, target_rate: int = TARGET_RATE, debug_dump_wav: bool = False) -> None:
        self._target_rate = target_rate
        self._debug_dump_wav = debug_dump_wav
        self._stream: sd.InputStream | None = None
        self._actual_rate = target_rate
        self._lock = threading.Lock()
        self._debug_chunks: list[np.ndarray] = []
        self._error: str | None = None
        self._last_audio = 0.0
        self.queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self.cleanup_debug_dump()  # 清除上次异常退出可能留下的麦克风音频

    @property
    def error(self) -> str | None:
        return self._error

    def seconds_since_audio(self) -> float:
        """距上次回调的秒数。会话进行中该值持续增长即为设备无响应（如中途拔出）。"""
        return time.monotonic() - self._last_audio

    def cleanup_debug_dump(self) -> None:
        """删除落盘调试音频；失败时记录错误，避免退出流程崩溃。"""
        try:
            DEBUG_CAPTURE_PATH.unlink(missing_ok=True)
        except OSError as exc:
            self._error = self._error or f"清理调试录音失败：{exc}"

    def start(self) -> None:
        """开始采集。设备打不开时抛 CaptureError（信息含可用设备列表）。"""
        self._error = None
        self._debug_chunks = []
        self._last_audio = time.monotonic()
        self.queue = queue.Queue()
        self._stream, self._actual_rate = self._open_stream()
        self._stream.start()

    def _open_stream(self) -> tuple[sd.InputStream, int]:
        # 注意：_actual_rate 必须在创建流之前赋值——探测（start/stop 试开）期间回调
        # 就可能触发；探测期音频进入会话队列是可接受的（本来就是会话的一部分）。
        self._actual_rate = self._target_rate
        try:
            stream = sd.InputStream(
                samplerate=self._target_rate,
                channels=1,
                dtype="float32",
                blocksize=_BLOCK_SIZE,
                callback=self._on_audio,
            )
            stream.start()
            stream.stop()
            return stream, self._target_rate
        except Exception:
            # 设备不支持目标采样率：以设备默认采样率打开，回调里重采样
            try:
                dev_rate = float(sd.query_devices(kind="input")["default_samplerate"])  # type: ignore[index]
                rate = int(dev_rate) if dev_rate > 0 else 48000
                self._actual_rate = rate
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    blocksize=int(_BLOCK_SIZE * rate / self._target_rate),
                    callback=self._on_audio,
                )
                stream.start()
                stream.stop()
                return stream, rate
            except Exception as exc:
                devices = "\n".join(f"  [{i}] {name} ({rate0:.0f}Hz)" for i, name, rate0 in list_input_devices())
                raise CaptureError(
                    f"无法打开麦克风（{exc}）。请检查麦克风是否连接、是否被其他程序独占。可用输入设备：\n{devices or '  （无）'}"
                ) from exc

    def _on_audio(self, indata: np.ndarray, frames: int, time_info: object, status: object) -> None:
        try:
            self._last_audio = time.monotonic()
            mono = indata[:, 0]
            if self._actual_rate != self._target_rate:
                mono = _resample(mono, self._actual_rate, self._target_rate)
            else:
                mono = mono.copy()  # 回调缓冲区仅在回调返回前有效，必须拷贝
            if self._debug_dump_wav:
                with self._lock:
                    self._debug_chunks.append(mono.copy())
            self.queue.put(mono)
        except Exception as exc:  # noqa: BLE001 —— 回调里不能抛异常，记录后由主循环善后
            self._error = f"采集过程出错：{exc}"

    def stop(self) -> Path | None:
        """停止采集。开了调试开关时把整段音频写成 wav 并返回路径，否则返回 None。

        设备已被移除时 stop/close 可能抛 PortAudio 错误——吞掉并记录，
        保证哨兵一定入队、调用方不崩溃。
        """
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception as exc:  # noqa: BLE001
                self._error = self._error or f"停止采集时出错：{exc}"
            try:
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                self._error = self._error or f"关闭采集时出错：{exc}"
            finally:
                self._stream = None
                self.queue.put(None)  # 流结束哨兵
        if not self._debug_dump_wav:
            return None
        with self._lock:
            chunks = list(self._debug_chunks)
            self._debug_chunks = []
        if not chunks:
            return None
        audio = np.concatenate(chunks)
        path = DEBUG_CAPTURE_PATH
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._target_rate)
            wf.writeframes((np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
        return path

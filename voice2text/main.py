"""程序入口：常驻进程，Alt+V 切换听写采集。

阶段 2 范围：热键开关 + 麦克风采集（调试 wav 可验证）。阶段 3 在此挂接流式识别与上屏，
阶段 4 挂接停顿校对。消费不到的音频块在主循环里丢弃，防止队列无限增长。
"""

from __future__ import annotations

import queue
import sys

from voice2text import __version__
from voice2text.capture import WATCHDOG_SECONDS, CaptureError, MicrophoneCapture
from voice2text.config import AppConfig, load_config
from voice2text.hotkey import HotkeyListener

ASR_REQUIRED_FILES = (
    "encoder-epoch-99-avg-1.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.onnx",
    "tokens.txt",
)


def check_models(cfg: AppConfig) -> bool:
    """检查识别与校对模型文件是否就位（安装脚本跑完即应通过）。"""
    ok = True
    for name in ASR_REQUIRED_FILES:
        if not cfg.asr_file(name).is_file():
            print(f"  [缺失] ASR 模型文件: {cfg.asr_file(name)}")
            ok = False
    if not cfg.llm_model_path.is_file():
        print(f"  [缺失] 校对模型文件: {cfg.llm_model_path}")
        ok = False
    return ok


class DictationApp:
    """听写主循环：等待热键切换信号，管理采集会话的生命周期。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._capture = MicrophoneCapture(
            target_rate=cfg.sample_rate, debug_dump_wav=cfg.debug_dump_wav
        )
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self) -> None:
        if self._active:
            self._stop_session()
        else:
            self._start_session()

    def _start_session(self) -> None:
        try:
            self._capture.start()
        except CaptureError as exc:
            print(f"[听写未开始] {exc}")
            return
        self._active = True
        print(f"[听写中] 再按 {self._cfg.hotkey} 停止")

    def _stop_session(self) -> None:
        wav_path = self._capture.stop()
        self._active = False
        msg = "[已停止] 待命中"
        if wav_path is not None:
            msg += f"（调试录音: {wav_path}）"
        print(msg)

    def _drain(self) -> None:
        """阶段 2 无识别消费者：丢弃已采集音频，只保留错误信息。阶段 3 改为喂给识别线程。"""
        while True:
            try:
                chunk = self._capture.queue.get_nowait()
            except queue.Empty:
                return
            if chunk is None:
                return

    def _check_watchdog(self) -> None:
        """会话中设备无响应（如中途拔出麦克风）的看门狗：超过阈值无回调即报错停会话。"""
        if self._active and self._capture.seconds_since_audio() > WATCHDOG_SECONDS:
            print("[听写中断] 麦克风无响应，可能已断开。请检查设备后重新开始。")
            self._stop_session()

    def run(self) -> int:
        try:
            hotkey = HotkeyListener(self._cfg.hotkey)
        except Exception as exc:  # noqa: BLE001 —— keyboard 库初始化失败的兜底提示
            print(f"[错误] 全局热键初始化失败：{exc}")
            return 1
        print(f"常驻运行中：{self._cfg.hotkey} 开始/停止听写，Ctrl+C 退出")
        try:
            hotkey.self_check(timeout=10.0)
            while True:
                if hotkey.wait_toggle(0.2):
                    hotkey.clear_toggle()
                    self.toggle()
                if self._active:
                    self._drain()
                    if self._capture.error:  # 采集中途拔麦克风等
                        print(f"[听写中断] {self._capture.error}")
                        self._stop_session()
                    else:
                        self._check_watchdog()
        except KeyboardInterrupt:
            print("\n退出")
        finally:
            if self._active:
                self._stop_session()
            hotkey.shutdown()
        return 0


def main() -> int:
    cfg = load_config()
    print(f"voice2text v{__version__}")
    print(f"  热键: {cfg.hotkey} | 采样率: {cfg.sample_rate}Hz | 停顿阈值: {cfg.endpoint_pause_seconds}s")
    print(f"  二次校对: {'开' if cfg.proofread_enabled else '关'} | 超时: {cfg.proofread_timeout_seconds}s")
    if not check_models(cfg):
        print("  模型未就绪：请先运行 install.bat")
        return 1
    return DictationApp(cfg).run()


if __name__ == "__main__":
    sys.exit(main())

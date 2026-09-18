"""程序入口：常驻进程，Alt+V 切换听写。

阶段 3 范围：热键开关 + 采集 + sherpa-onnx 流式识别 + 光标处整句刷新上屏 + endpoint 锁句。
阶段 4 在锁句回调处挂接二次校对。
"""

from __future__ import annotations

import sys
import time

from voice2text import __version__
from voice2text.asr import ASRSessionWorker, StreamingASR
from voice2text.capture import WATCHDOG_SECONDS, CaptureError, MicrophoneCapture
from voice2text.config import AppConfig, load_config
from voice2text.hotkey import HotkeyListener
from voice2text.input import TextInserter
from voice2text.proofread import Proofreader, chunk_sentences

ASR_REQUIRED_FILES = (
    "encoder-epoch-99-avg-1.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.onnx",
    "tokens.txt",
)


def check_models(cfg: AppConfig) -> bool:
    """检查模型文件是否就位（安装脚本跑完即应通过）。"""
    ok = True
    for name in ASR_REQUIRED_FILES:
        if not cfg.asr_file(name).is_file():
            print(f"  [缺失] ASR 模型文件: {cfg.asr_file(name)}")
            ok = False
    if cfg.proofread_enabled and not cfg.llm_model_path.is_file():
        print(f"  [缺失] 校对模型文件: {cfg.llm_model_path}")
        ok = False
    return ok


class DictationApp:
    """听写主循环：热键信号 → 会话生命周期（采集/识别/上屏）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._capture = MicrophoneCapture(
            target_rate=cfg.sample_rate, debug_dump_wav=cfg.debug_dump_wav
        )
        self._inserter = TextInserter(cfg.non_editable_process_blacklist)
        self._asr: StreamingASR | None = None  # 懒加载（首次会话时，加载约 1 秒）
        self._proofreader: Proofreader | None = None  # 懒加载（首次会话时，加载约 1-2 秒）
        self._worker: ASRSessionWorker | None = None
        self._active = False
        self._session_gen = 0  # 会话代数：旧 worker 的迟到回调不得写新会话的屏
        self._locked_sentences: list[str] = []  # 锁定句文本（校对的分段依据）

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self) -> None:
        if self._active:
            self._stop_session()
        else:
            self._start_session()

    def _start_session(self) -> None:
        # 识别器先于采集就位：模型加载失败时不必回滚已启动的采集/剪贴板状态
        if self._asr is None:
            print("  （首次会话：加载识别模型…）")
            try:
                self._asr = StreamingASR(self._cfg)
            except Exception as exc:  # noqa: BLE001 —— 模型缺失/损坏给用户可读提示
                print(f"[听写未开始] 识别模型加载失败：{exc}")
                return
        if self._cfg.proofread_enabled and self._proofreader is None:
            print("  （首次会话：加载校对模型…）")
            try:
                self._proofreader = Proofreader(self._cfg)
            except Exception as exc:  # noqa: BLE001
                print(f"[警告] 校对模型加载失败，二次校对已停用：{exc}")
                self._cfg.proofread_enabled = False
        try:
            self._capture.start()
        except CaptureError as exc:
            print(f"[听写未开始] {exc}")
            return
        self._session_gen += 1
        gen = self._session_gen
        self._inserter.begin_session()
        self._locked_sentences = []
        self._worker = ASRSessionWorker(
            asr=self._asr,
            audio_queue=self._capture.queue,
            sample_rate=self._cfg.sample_rate,
            on_partial=lambda text: self._on_partial(gen, text),
            on_sentence=lambda text: self._on_sentence(gen, text),
        )
        self._worker.start()
        self._active = True
        print(f"[听写中] 再按 {self._cfg.hotkey} 停止")

    def _stop_session(self) -> None:
        # 顺序关键：尾句要经历"最终识别 → 上屏 → 锁句"，统一校对在锁句完成后进行。
        # 迟到回调的防护由会话代数（gen 比对）承担。
        self._capture.stop()  # 放入 None 哨兵 → 识别线程完成尾句后自行退出
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            if self._worker.is_alive():
                print("[警告] 识别线程未在预期内结束（其迟到回调会被会话代数拦截）")
            self._worker = None
        self._finalize_proofread()  # 用户决策：停止后才统一校对（听写期间不改文字）
        time.sleep(0.3)  # 等 App 异步消化最后一次 Ctrl+V，再恢复用户剪贴板（否则粘贴读到旧剪贴板）
        self._inserter.end_session()  # 关写入闸门 + 恢复用户剪贴板
        self._active = False
        print("[已停止] 待命中")

    def _finalize_proofread(self) -> None:
        """停止后统一校对：按锁定句分块校对、逐块替换（块序号随替换收缩平移）。"""
        if not self._cfg.proofread_enabled or self._proofreader is None:
            return
        sentences = self._locked_sentences
        if not sentences:
            return
        print(f"[校对中] {len(sentences)} 句…")
        chunks = chunk_sentences(sentences)
        shift = 0  # 每块 k 句替换为 1 条记账，后续块索引左移 k-1
        optimized = 0
        for start, end, text in chunks:
            t0 = time.monotonic()
            corrected = self._proofreader.proofread(text)
            if corrected is None or time.monotonic() - t0 > self._cfg.proofread_timeout_seconds:
                continue  # 失败/超时保留原文
            if self._inserter.replace_committed_range(start - shift, end - shift, corrected):
                optimized += 1
                shift += end - start
        print(f"[校对完成] {optimized}/{len(chunks)} 块已优化")

    # ---- 识别线程回调（在识别线程中执行；gen 过滤旧会话的迟到回调）----

    def _on_partial(self, gen: int, text: str) -> None:
        if gen != self._session_gen:
            return
        self._inserter.replace_current(text)

    def _on_sentence(self, gen: int, text: str) -> None:
        if gen != self._session_gen:
            return
        self._inserter.replace_current(text)  # 确保屏幕上是最终文本（partial 可能滞后）
        committed = self._inserter.commit_current()
        if committed:  # 脱管句屏幕上没有文本，不进句列表
            self._locked_sentences.append(committed)

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
                    worker_error = self._worker.error if self._worker else None
                    if self._capture.error:  # 采集中途拔麦克风等
                        print(f"[听写中断] {self._capture.error}")
                        self._stop_session()
                    elif worker_error:  # 识别/上屏线程致命异常
                        print(f"[听写中断] {worker_error}")
                        self._stop_session()
                    elif self._inserter.aborted:  # 粘贴冲突停写：提示一次并停会话
                        print("[听写中断] 剪贴板持续被占用，上屏已暂停。重新按热键开始可恢复。")
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

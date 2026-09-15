"""程序入口：常驻进程，Alt+V 切换听写。

阶段 3 范围：热键开关 + 采集 + sherpa-onnx 流式识别 + 光标处整句刷新上屏 + endpoint 锁句。
阶段 4 在锁句回调处挂接二次校对。
"""

from __future__ import annotations

import sys

from voice2text import __version__
from voice2text.asr import ASRSessionWorker, StreamingASR
from voice2text.capture import WATCHDOG_SECONDS, CaptureError, MicrophoneCapture
from voice2text.config import AppConfig, load_config
from voice2text.hotkey import HotkeyListener
from voice2text.input import TextInserter
from voice2text.proofread import Proofreader, ProofreadWorker

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
        self._pr_worker: ProofreadWorker | None = None
        self._active = False
        self._session_gen = 0  # 会话代数：旧 worker 的迟到回调不得写新会话的屏
        self._locked_sentences: list[str] = []  # 原始锁句文本（校对前的 ASR 输出）

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
        # 校对线程先于识别线程就位：消除首句锁句时 pr_worker 尚为 None 的微窗口
        if self._cfg.proofread_enabled:
            self._pr_worker = ProofreadWorker(
                proofreader=self._proofreader,
                timeout=self._cfg.proofread_timeout_seconds,
                on_result=lambda i, orig, fixed: self._on_proofread(gen, i, orig, fixed),
            )
        self._worker = ASRSessionWorker(
            asr=self._asr,
            audio_queue=self._capture.queue,
            sample_rate=self._cfg.sample_rate,
            on_partial=lambda text: self._on_partial(gen, text),
            on_sentence=lambda text: self._on_sentence(gen, text),
        )
        if self._pr_worker is not None:
            self._pr_worker.start()
        self._worker.start()
        self._active = True
        print(f"[听写中] 再按 {self._cfg.hotkey} 停止")

    def _stop_session(self) -> None:
        # 顺序关键：尾句要经历"最终识别 → 上屏 → 校对替换"全程，剪贴板闸门必须最后关。
        # 迟到回调的防护由会话代数（gen 比对）承担，不依赖闸门先关。
        self._capture.stop()  # 放入 None 哨兵 → 识别线程完成尾句后自行退出
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            if self._worker.is_alive():
                print("[警告] 识别线程未在预期内结束（其迟到回调会被会话代数拦截）")
            self._worker = None
        if self._pr_worker is not None:
            # 尾句校对：处理完已提交句子后退出；join 预算 = 每句超时 ×2（上限 30s）
            self._pr_worker.finish()
            self._pr_worker.join(timeout=min(30.0, self._cfg.proofread_timeout_seconds * 2))
            if self._pr_worker.is_alive():
                print("[警告] 校对线程未在预期内结束（残留线程会先排空旧队列，其迟到回调被会话代数拦截）")
            self._pr_worker = None
        self._inserter.end_session()  # 关写入闸门 + 恢复用户剪贴板
        self._active = False
        print(f"[已停止] 本轮共 {len(self._locked_sentences)} 句")

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
        if not committed:  # 脱管句屏幕上没有文本，不进句列表/校对队列
            return
        index = len(self._locked_sentences)
        self._locked_sentences.append(committed)
        if self._pr_worker is not None:
            self._pr_worker.submit(index, committed)

    # ---- 校对线程回调（在校对线程中执行；gen 过滤 + 迟到结果丢弃）----

    def _on_proofread(self, gen: int, index: int, original: str, corrected: str | None) -> None:
        if gen != self._session_gen or corrected is None:
            return
        self._inserter.replace_committed(index, corrected)

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
                    pr_error = self._pr_worker.error if self._pr_worker else None
                    if self._capture.error:  # 采集中途拔麦克风等
                        print(f"[听写中断] {self._capture.error}")
                        self._stop_session()
                    elif worker_error:  # 识别/上屏线程致命异常
                        print(f"[听写中断] {worker_error}")
                        self._stop_session()
                    elif pr_error:  # 校对线程致命异常：降级继续听写，不影响上屏
                        print(f"[警告] 校对已停止：{pr_error}")
                        self._pr_worker = None
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

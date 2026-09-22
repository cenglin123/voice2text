"""程序入口：常驻进程 = 托盘 + 悬浮窗 GUI + 热键/听写引擎。

线程模型（Windows 上 tkinter 主循环必须在主线程）：
- 主线程：tkinter mainloop（悬浮窗 + 设置窗），每 30ms tick() 轮询
- pystray 托盘：daemon 线程 run()，动作经 cmd_queue 投递主线程
- keyboard 热键：自有线程回调，只 set Event
- 识别：ASR worker 线程；停止时的统一校对在后台线程（结果经 ui_queue 回 UI）

听写流程（用户决策）：Alt+V 开始 → 流式上屏（听写期间屏幕文字只增不改）→
Alt+V 停止 → 后台统一校对（分块）→ 替换为整洁文本。
"""

from __future__ import annotations

import os
import queue
import json
import sys
import threading
import time
import types
from pathlib import Path
from time import perf_counter_ns

import winsound

from voice2text import __version__
from voice2text.asr import ASRSessionWorker, StreamingASR
from voice2text.capture import WATCHDOG_SECONDS, CaptureError, MicrophoneCapture
from voice2text.config import AppConfig, PROJECT_ROOT, load_config
from voice2text.hotkey import HotkeyListener
from voice2text.input import TextInserter
from voice2text.proofread import Proofreader, chunk_sentences
from voice2text.performance import PerformanceRecorder
from voice2text.punctuation import PunctuationRestorer

ASR_REQUIRED_FILES = (
    "encoder-epoch-99-avg-1.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.onnx",
    "tokens.txt",
)
UI_POLL_MS = 30


def resolve_help_document(project_root: Path = PROJECT_ROOT) -> Path:
    """返回当前运行形态中实际存在的帮助文档。"""
    for name in ("安装说明.txt", "README.md"):
        path = project_root / name
        if path.is_file():
            return path
    raise FileNotFoundError("未找到安装说明.txt 或 README.md")


def check_models(cfg: AppConfig) -> tuple[bool, str]:
    """检查模型文件。识别模型缺失=致命；校对模型缺失=降级警告（运行期同样会降级）。"""
    missing_asr = [name for name in ASR_REQUIRED_FILES if not cfg.asr_file(name).is_file()]
    for name in missing_asr:
        print(f"  [缺失] ASR 模型文件: {cfg.asr_file(name)}")
    llm_missing = cfg.proofread_enabled and not cfg.llm_model_path.is_file()
    punctuation_missing = (
        cfg.punctuation_enabled and not cfg.punctuation_model_path.is_file()
    )
    if llm_missing:
        print(f"  [警告] 校对模型缺失（{cfg.llm_model_path}），二次校对将停用")
    if punctuation_missing:
        print(f"  [警告] 标点模型缺失（{cfg.punctuation_model_path}），停顿标点将停用")
    detail = "；".join(
        [f"识别模型缺失: {n}" for n in missing_asr]
        + ([f"校对模型缺失: {cfg.llm_model_path.name}（可继续使用，无二次校对）"] if llm_missing else [])
        + ([f"标点模型缺失: {cfg.punctuation_model_path.name}（可继续使用，无停顿标点）"] if punctuation_missing else [])
    )
    return (len(missing_asr) == 0), detail


class DictationApp:
    """听写引擎：由 UI 主线程的 tick() 驱动；耗时操作全部在后台线程。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._capture = MicrophoneCapture(
            target_rate=cfg.sample_rate, debug_dump_wav=cfg.debug_dump_wav
        )
        self._metrics = PerformanceRecorder()
        self._inserter = TextInserter(
            cfg.non_editable_process_blacklist, use_clipboard=cfg.input_clipboard,
            metrics=self._metrics,
        )
        self._asr: StreamingASR | None = None
        self._proofreader: Proofreader | None = None
        self._punctuator: PunctuationRestorer | None = None
        self._worker: ASRSessionWorker | None = None
        self._session_gen = 0  # 会话代数：旧 worker 的迟到回调不得写新会话的屏
        self._input_session = 0  # TextInserter 会话代数：迟到校对不得写入新会话
        self._cancelled_sessions: set[int] = set()
        self._locked_sentences: list[str] = []
        self.hotkey: HotkeyListener | None = None
        self.cmd_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.ui_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()  # ("state", s) 给 UI
        self.widget_visible = True  # 托盘动态文案用（UI 侧维护）
        self._active = False
        self._busy = False  # 启动/停止进行中，忽略新的切换请求
        self.apply_settings_scale: tuple[float, float, float] | None = None  # 缩放、透明度、长宽比
        self.apply_settings_font_scale: float | None = None
        self._models_ready = threading.Event()  # 预加载完成（成功与否都置位）
        self._closing = False
        self._session_thread: threading.Thread | None = None
        self._activity_guard = None

    @property
    def active(self) -> bool:
        return self._active

    @property
    def font_scale(self) -> float:
        return float(getattr(self._cfg, "font_scale", 1.0))

    def push_state(self, state: str) -> None:
        self.ui_queue.put(("state", state))

    # ---- 启动 / 停止（后台线程执行）----

    def preload_models(self) -> None:
        """启动即后台加载识别/校对模型（悬浮窗显示"加载中"，首次听写零等待）。"""
        def _load() -> None:
            try:
                self._asr = StreamingASR(self._cfg)
                print("  （后台加载识别模型完成）")
                if self._cfg.punctuation_enabled:
                    try:
                        self._punctuator = PunctuationRestorer(self._cfg)
                        print("  （后台加载标点模型完成）")
                    except Exception as exc:  # noqa: BLE001
                        print(f"[警告] 标点模型加载失败，停顿标点已停用：{exc}")
                        self._cfg.punctuation_enabled = False
                if self._cfg.proofread_enabled:
                    try:
                        self._proofreader = Proofreader(self._cfg)
                        print("  （后台加载校对模型完成）")
                    except Exception as exc:  # noqa: BLE001
                        print(f"[警告] 校对模型加载失败，二次校对已停用：{exc}")
                        self._cfg.proofread_enabled = False
            except Exception as exc:  # noqa: BLE001
                print(f"[警告] 识别模型预加载失败（{exc}），将在首次听写时重试")
            finally:
                self._models_ready.set()
                self.push_state("idle")

        self.push_state("loading")
        threading.Thread(target=_load, daemon=True).start()

    def request_toggle(self) -> None:
        """开始时同步捕获目标，焦点锁定持续到尾句与校对全部结束。"""
        if self._busy or self._closing:
            return
        if not self._models_ready.is_set():
            print("[提示] 模型加载中，请稍候再试")
            return
        self._busy = True
        if self._active:
            self.push_state("proofreading")
            token = self._input_session
            self._session_thread = threading.Thread(
                target=lambda: self._finish_toggle(token), daemon=True
            )
        else:
            try:
                from voice2text.activity import InputActivityGuard
                target = self._inserter.capture_target()
                if self._activity_guard is not None:
                    self._activity_guard.close()
                self._activity_guard = InputActivityGuard(self._inserter, self._cfg.hotkey)
                self._input_session = self._inserter.begin_session(target)
                print(f"[目标锁定] {target.process}，听写至校对完成前保持原窗口焦点")
                from voice2text.diagnostics import trace
                trace("target_capture", snapshot=target.diagnostic_snapshot())
                self.push_state("loading")
            except Exception as exc:
                self._busy = False
                print(f"[听写未开始] {exc}")
                self.push_state("error")
                return
            self._session_thread = threading.Thread(target=self._start_toggle, daemon=True)
        self._session_thread.start()

    def _start_toggle(self) -> None:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            self._start_session()
            self.push_state("listening" if self._active else "idle")
        except Exception as exc:
            print(f"[听写未开始] {exc}")
            self._capture.stop()
            self.push_state("error")
        finally:
            if not self._active:
                self._inserter.end_session()
            self._busy = False
            pythoncom.CoUninitialize()

    def _finish_toggle(self, token: int) -> None:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            self._stop_session(token)
            if self._input_session == token:
                self.push_state("error" if self._inserter.aborted else "idle")
        except Exception as exc:
            print(f"[停止异常] {exc}")
            self.push_state("error")
        finally:
            self._inserter.end_session(token)
            if self._input_session == token:
                self._active = False
                self._busy = False
            self._cancelled_sessions.discard(token)
            pythoncom.CoUninitialize()

    def _start_session(self) -> None:
        if self._closing:
            return
        if not self._inserter.guard_focus():
            raise RuntimeError(
                self._inserter.abort_reason or "目标输入位置在启动录音前发生变化"
            )
        if self._asr is None:
            print("  （首次会话：加载识别模型…）")
            try:
                self._asr = StreamingASR(self._cfg)
            except Exception as exc:  # noqa: BLE001
                print(f"[听写未开始] 识别模型加载失败：{exc}")
                return
        if self._cfg.proofread_enabled and self._proofreader is None:
            print("  （首次会话：加载校对模型…）")
            try:
                self._proofreader = Proofreader(self._cfg)
            except Exception as exc:  # noqa: BLE001
                print(f"[警告] 校对模型加载失败，二次校对已停用：{exc}")
                self._cfg.proofread_enabled = False
        if self._cfg.punctuation_enabled and self._punctuator is None:
            try:
                self._punctuator = PunctuationRestorer(self._cfg)
            except Exception as exc:  # noqa: BLE001
                print(f"[警告] 标点模型加载失败，停顿标点已停用：{exc}")
                self._cfg.punctuation_enabled = False
        try:
            self._capture.start()
        except CaptureError as exc:
            print(f"[听写未开始] {exc}")
            return
        self._session_gen += 1
        gen = self._session_gen
        if self._closing or self._inserter.aborted:
            self._capture.stop()
            return
        self._locked_sentences = []
        self._metrics.reset()
        self._worker = ASRSessionWorker(
            asr=self._asr,
            audio_queue=self._capture.queue,
            sample_rate=self._cfg.sample_rate,
            on_partial=lambda text: self._on_partial(gen, text),
            on_sentence=lambda text: self._on_sentence(gen, text),
            punctuator=self._punctuator,
            metrics=self._metrics,
        )
        self._worker.start()
        self._active = True
        self._cue("start")
        print(f"[听写中] 再按 {self._cfg.hotkey} 停止")

    def _stop_session(self, token: int) -> None:
        self._capture.stop()  # None 哨兵 → 识别线程完成尾句后退出
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            if self._worker.is_alive():
                print("[警告] 识别线程未在预期内结束（其迟到回调会被会话代数拦截）")
                self._inserter.abort("识别线程停止超时，保留已上屏内容")
            self._worker = None
        self._session_gen += 1  # 正常尾句已排空，此后拦截迟到回调
        self._finalize_proofread(token)
        if token not in self._cancelled_sessions:
            self._inserter.end_session(token)
            if self._input_session == token:
                self._active = False
                self._cue("stop")
                print("[已停止] 待命中")
        if self._input_session == token and token not in self._cancelled_sessions:
            summary = self._metrics.format_summary()
            if summary:
                print(f"[性能] {summary}")

    def _finalize_proofread(self, token: int) -> None:
        """停止后统一校对：按锁定句分块校对、逐块替换（块序号随替换收缩平移）。"""
        if not self._cfg.proofread_enabled or self._proofreader is None:
            return
        sentences = self._locked_sentences
        if not sentences:
            return
        print(f"[校对中] {len(sentences)} 句…")
        chunks = chunk_sentences(sentences)
        shift = 0
        optimized = 0
        unchanged = 0
        failed = 0
        outcomes = {
            "cleanup_success": 0,
            "punctuation_model_success": 0,
            "terminal_fallback": 0,
            "model_none": 0,
            "replacement_failed": 0,
            "cancelled": 0,
        }
        def cancellation_reason() -> str:
            if self._closing:
                return "程序退出"
            if token != self._input_session:
                return "会话已更换"
            if token in self._cancelled_sessions:
                return "超过校对等待上限"
            if self._inserter.aborted:
                return self._inserter.abort_reason or "输入保护关闭写入"
            return ""

        for index, (start, end, text) in enumerate(chunks, 1):
            reason = cancellation_reason()
            if reason:
                print(f"[校对取消] 会话 {token} 第 {index} 块，推理前：{reason}")
                outcomes["cancelled"] += len(chunks) - index + 1
                break
            t0 = time.monotonic()
            proofread_started = perf_counter_ns()
            timer = threading.Timer(
                self._cfg.proofread_hard_timeout_seconds,
                self._cancel_stalled_proofread,
                args=(token, index),
            )
            timer.daemon = True
            timer.start()
            try:
                if callable(getattr(type(self._proofreader), "proofread_with_outcome", None)):
                    corrected, outcome = self._proofreader.proofread_with_outcome(text)
                else:
                    corrected = self._proofreader.proofread(text)
                    outcome = getattr(self._proofreader, "last_outcome", "model_returned")
            finally:
                timer.cancel()
            reason = cancellation_reason()
            duration = perf_counter_ns() - proofread_started
            if token == self._input_session:
                self._metrics.record("proofread_generate", duration, "cancelled" if reason else outcome)
            if reason:
                print(f"[校对取消] 会话 {token} 第 {index} 块，推理后 {duration / 1e9:.2f}s：{reason}；模型结果={outcome}")
                outcomes["cancelled"] += len(chunks) - index + 1
                break
            elapsed = time.monotonic() - t0
            if corrected is None:
                failed += 1
                outcomes["model_none"] += 1
                print(f"[校对跳过] 第 {index} 块未返回可靠结果")
                continue
            if outcome in outcomes:
                outcomes[outcome] += 1
            if elapsed > self._cfg.proofread_timeout_seconds:
                # 旧逻辑在等待已经结束后丢弃正确结果，既没有缩短等待又导致校对失效。
                print(f"[校对较慢] 第 {index} 块用时 {elapsed:.1f}s，结果仍会应用")
            changed = corrected.strip() != text.strip()
            replacement_started = perf_counter_ns()
            replaced = self._inserter.replace_committed_range(
                start - shift, end - shift, corrected, expected_generation=token
            )
            self._metrics.record("proofread_replace", perf_counter_ns() - replacement_started,
                                 "ok" if replaced else "failed")
            if replaced:
                optimized += int(changed)
                unchanged += int(not changed)
                shift += end - start
            else:
                failed += 1
                outcomes["replacement_failed"] += 1
                print(f"[校对替换失败] 第 {index} 块未能安全恢复原输入位置")
        detail = f"，{unchanged} 块无需修改" if unchanged else ""
        failure = f"，{failed} 块未应用" if failed else ""
        model_detail = "，".join(
            f"{name}={count}" for name, count in outcomes.items() if count
        )
        suffix = f"（{model_detail}）" if model_detail else ""
        print(f"[校对完成] {optimized}/{len(chunks)} 块已优化{detail}{failure}{suffix}")

    def _cancel_stalled_proofread(self, token: int, index: int) -> None:
        """校对硬超时只取消逻辑会话；迟到模型输出受 TextInserter 代数闸门拦截。"""
        if self._closing or token != self._input_session or token in self._cancelled_sessions:
            return
        self._cancelled_sessions.add(token)
        self._inserter.end_session(token)
        self._active = False
        self._busy = False
        self.push_state("error")
        print(f"[校对超时] 第 {index} 块超过 {self._cfg.proofread_hard_timeout_seconds:.0f}s，已释放输入焦点")

    def _cue(self, kind: str) -> None:
        if self._cfg.sound_cue:
            try:
                winsound.MessageBeep(winsound.MB_OK if kind == "start" else winsound.MB_ICONASTERISK)
            except Exception:  # noqa: BLE001 —— 声卡不可用不影响听写
                pass

    # ---- 识别线程回调 ----

    def _on_partial(self, gen: int, text: str) -> bool:
        if gen != self._session_gen:
            return False
        started = perf_counter_ns()
        written = self._inserter.replace_current(text)
        self._metrics.record("partial_write", perf_counter_ns() - started,
                             "ok" if written else "failed")
        return written

    def _on_sentence(self, gen: int, text: str) -> bool:
        if gen != self._session_gen:
            return False
        started = perf_counter_ns()
        committed = self._inserter.punctuate_and_commit_current(text)
        self._metrics.record("partial_write", perf_counter_ns() - started,
                             "ok" if committed else "failed")
        if committed:
            self._locked_sentences.append(committed)
            return True
        return False

    # ---- UI 主线程每帧调用 ----

    def tick(self) -> None:
        """轮询热键/托盘命令/错误条件。必须在主线程、非阻塞。"""
        if not self._active and not self._busy and self._activity_guard is not None:
            self._activity_guard.close()
            self._activity_guard = None
        if self.hotkey is not None and self.hotkey.wait_toggle(0):
            latency_ms = self.hotkey.clear_toggle()
            from voice2text.diagnostics import trace
            trace("hotkey_dispatch", latency_ms=round(latency_ms, 1))
            self.request_toggle()

        while True:
            try:
                cmd, _ = self.cmd_queue.get_nowait()
            except queue.Empty:
                break
            if cmd == "toggle":
                if self._busy:
                    print("[托盘] 忽略切换请求：上一轮启动/停止仍在进行")
                elif not self._models_ready.is_set():
                    print("[托盘] 忽略切换请求：模型仍在加载")
                else:
                    print("[托盘] 切换听写状态")
                    self.request_toggle()

        if self._active and not self._busy:
            if self._capture.error or self._inserter.aborted:
                reason = self._capture.error or self._inserter.abort_reason or "上屏失败，已停止输入"
                print(f"[听写中断] {reason}")
                self.push_state("proofreading")
                self._busy = True
                token = self._input_session
                threading.Thread(target=lambda: self._finish_toggle(token), daemon=True).start()
            elif self._capture.seconds_since_audio() > WATCHDOG_SECONDS:
                print("[听写中断] 麦克风无响应，可能已断开。请检查设备后重新开始。")
                self.push_state("proofreading")
                self._busy = True
                token = self._input_session
                threading.Thread(target=lambda: self._finish_toggle(token), daemon=True).start()

    def shutdown(self) -> None:
        """先关写入闸门，防止退出过程中的迟到识别/校对继续写入。"""
        self._closing = True
        self._inserter.end_session()
        from voice2text.model_download import model_download
        model_download.close()
        from voice2text.update import update_manager
        update_manager.close()
        if self._activity_guard is not None:
            self._activity_guard.close()
            self._activity_guard = None
        self._session_gen += 1
        self._capture.stop()
        self._capture.cleanup_debug_dump()
        if self.hotkey is not None:
            self.hotkey.shutdown()
        if self._worker is not None:
            self._worker.join(timeout=1.0)
        if self._session_thread is not None and self._session_thread is not threading.current_thread():
            self._session_thread.join(timeout=1.0)

    def apply_settings(self, cfg_dict: dict) -> dict:
        """设置窗口保存回调（主线程）：热键重注册；返回生效值供写盘。

        热键 rebind 失败时保留旧组合——调用方以返回值为准持久化，
        避免"磁盘是坏热键、运行中是旧热键"的分叉。
        """
        new_combo = str(cfg_dict.get("hotkey", ""))
        if self.hotkey is not None and new_combo and new_combo != self.hotkey.combo:
            try:
                self.hotkey.rebind(new_combo)
                print(f"[设置] 热键已更换为 {new_combo}")
            except Exception as exc:  # noqa: BLE001
                cfg_dict["hotkey"] = self.hotkey.combo  # rebind 失败回退旧值
                print(f"[设置] 热键更换失败（{exc}），保留 {self.hotkey.combo}")
        self._cfg.hotkey = str(cfg_dict.get("hotkey", self._cfg.hotkey))
        self._cfg.proofread_enabled = bool(cfg_dict.get("proofread_enabled", True))
        self._cfg.sound_cue = bool(cfg_dict.get("sound_cue", True))
        self._cfg.widget_scale = float(cfg_dict.get("widget_scale", 1.0))
        self._cfg.widget_aspect = float(cfg_dict.get("widget_aspect", 3.27))
        self._cfg.widget_opacity = float(cfg_dict.get("widget_opacity", 0.92))
        self._cfg.font_scale = max(0.85, min(1.35, float(cfg_dict.get("font_scale", 1.0))))
        self.apply_settings_scale = (self._cfg.widget_scale, self._cfg.widget_opacity, self._cfg.widget_aspect)
        self.apply_settings_font_scale = self._cfg.font_scale
        return dict(cfg_dict)


def _gui_main(output) -> int:
    cfg = load_config()
    print(f"voice2text v{__version__}  热键: {cfg.hotkey}")
    from voice2text.diagnostics import trace, fingerprint
    trace("build", fingerprint=fingerprint())
    ok, missing_detail = check_models(cfg)
    if not ok:
        message = f"模型未就绪：请先运行 install.bat\n{missing_detail}"
        print(f"  {message}")
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "voice2text", 0x10)
        except Exception:  # noqa: BLE001
            pass
        return 1
    if missing_detail:  # 仅校对模型缺失：降级继续
        if cfg.proofread_enabled and not cfg.llm_model_path.is_file():
            cfg.proofread_enabled = False
        if cfg.punctuation_enabled and not cfg.punctuation_model_path.is_file():
            cfg.punctuation_enabled = False
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, missing_detail, "voice2text", 0x30)
        except Exception:  # noqa: BLE001
            pass

    # 延迟导入：tkinter 仅在模型就绪后需要
    from voice2text.settings_window import SettingsWindow
    from voice2text.tray import build_tray, update_icon
    from voice2text.tray_menu import TrayMenu
    from voice2text.widget import DictationWidget
    from voice2text.desktop import DebugWindow

    app = DictationApp(cfg)
    try:
        app.hotkey = HotkeyListener(cfg.hotkey)
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 全局热键初始化失败：{exc}")
        return 1

    ui = types.SimpleNamespace(widget=None, settings=None, tray=None, tray_menu=None,
                               debug=None, visible=True)

    def widget_resized(scale: float, aspect: float) -> None:
        """悬浮窗拖拽结束后同步内存、设置窗和配置文件。"""
        cfg.widget_scale = round(scale, 2)
        cfg.widget_aspect = round(aspect, 2)
        if ui.settings is not None and ui.settings.root.winfo_exists():
            ui.settings.sync_appearance(cfg.widget_scale, cfg.widget_aspect)
        path = PROJECT_ROOT / "config.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            saved = {}
        saved.update({"widget_scale": cfg.widget_scale, "widget_aspect": cfg.widget_aspect})
        path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def hide_widget() -> None:
        ui.widget.hide()
        ui.visible = False
        app.widget_visible = False

    def show_widget() -> None:
        ui.widget.show()
        ui.visible = True
        app.widget_visible = True

    def quit_app() -> None:
        raise SystemExit

    ui.widget = DictationWidget(
        scale=cfg.widget_scale,
        aspect=cfg.widget_aspect,
        opacity=cfg.widget_opacity,
        on_toggle=app.request_toggle,
        on_settings=lambda: app.cmd_queue.put(("settings", None)),
        on_hide=hide_widget,
        on_quit=quit_app,
        on_resize=widget_resized,
    )

    def drain_cmds() -> None:
        while True:
            try:
                cmd, payload = app.cmd_queue.get_nowait()
            except queue.Empty:
                return
            if cmd == "toggle":
                print("[托盘] 收到切换命令")
                app.request_toggle()
            elif cmd == "tray_menu":
                ui.tray_menu.show(*payload)
            elif cmd == "toggle_widget":
                (hide_widget if ui.visible else show_widget)()
            elif cmd == "settings":
                if app._active or app._busy:
                    print("[提示] 请先停止听写并等待校对结束，再打开设置")
                    continue
                w = ui.settings
                if w is None or not w.root.winfo_exists():
                    cfg_dict = {
                        "hotkey": cfg.hotkey,
                        "widget_scale": cfg.widget_scale,
                        "widget_aspect": cfg.widget_aspect,
                        "widget_opacity": cfg.widget_opacity,
                        "proofread_enabled": cfg.proofread_enabled,
                        "sound_cue": cfg.sound_cue,
                        "font_scale": cfg.font_scale,
                    }
                    ui.settings = SettingsWindow(
                        cfg_dict, app.apply_settings, ui.widget.snapshot(),
                        on_debug=lambda: app.cmd_queue.put(("debug", None)),
                        on_update=lambda archive, version: app.cmd_queue.put(
                            ("apply_update", (archive, version))
                        ),
                    )
                else:
                    w.root.attributes("-topmost", True)
                    w.root.lift()
            elif cmd == "help":
                if app._active or app._busy:
                    print("[提示] 完成听写和校对后可打开帮助")
                    continue
                try:
                    os.startfile(str(resolve_help_document()))  # noqa: S606
                except OSError as exc:
                    print(f"[帮助] 无法打开使用帮助：{exc}")
            elif cmd == "debug":
                if app._active or app._busy:
                    print("[提示] 正在保持输入焦点，完成听写和校对后可查看运行输出")
                    continue
                if ui.debug is None or not ui.debug.root.winfo_exists():
                    ui.debug = DebugWindow(ui.widget.root, output)
                else:
                    ui.debug.show()
            elif cmd == "apply_update":
                if app._active or app._busy:
                    print("[更新] 请先等待听写和校对结束")
                    continue
                archive, version = payload
                from voice2text.update import launch_installer
                launch_installer(archive, version, os.getpid())
                print(f"[更新] v{version} 已验证，程序即将退出并安装")
                raise SystemExit
            elif cmd == "quit":
                raise SystemExit

    last_state = [None]
    last_visible = [None]

    def tick() -> None:
        ui.widget.pump(app.ui_queue)
        drain_cmds()
        app.tick()
        if app.apply_settings_scale:  # 设置保存后应用新外观（M1/M2：主线程 ui.widget）
            widget_scale, widget_opacity, widget_aspect = app.apply_settings_scale
            ui.widget.apply_appearance(widget_scale, widget_opacity, widget_aspect)
            app.apply_settings_scale = None
            try:
                ui.tray.title = f"voice2text 语音输入（{app.hotkey.combo}）"
                ui.tray.update_menu()
            except Exception:  # noqa: BLE001
                pass
        if app.apply_settings_font_scale is not None:
            ui.tray_menu.set_font_scale(app.apply_settings_font_scale)
            app.apply_settings_font_scale = None
        # 托盘与悬浮窗严格同源：状态或可见性变化 → 图标与菜单文案一起刷新
        if ui.widget.state != last_state[0] or ui.visible != last_visible[0]:
            state_changed = ui.widget.state != last_state[0]
            last_state[0] = ui.widget.state
            last_visible[0] = ui.visible
            if state_changed:
                try:
                    update_icon(ui.tray, ui.widget.state)
                except Exception:  # noqa: BLE001 —— 托盘异常不影响听写
                    pass
            try:
                ui.tray.update_menu()  # 动态文案（开始/停止、显示/隐藏）重估
            except Exception:  # noqa: BLE001
                pass

    def loop() -> None:
        try:
            tick()
        except SystemExit:
            try:
                app.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                ui.tray.stop()
            except Exception:  # noqa: BLE001
                pass
            ui.widget.root.destroy()
            return
        except Exception:  # noqa: BLE001
            import traceback

            traceback.print_exc()
        ui.widget.root.after(UI_POLL_MS, loop)

    ui.tray = build_tray(app.cmd_queue, app, hotkey=cfg.hotkey)
    ui.tray_menu = TrayMenu(ui.widget.root, app,
                            lambda command: app.cmd_queue.put((command, None)))
    # pystray 要求从主线程进入 detached 模式，再与 Tk mainloop 并行。
    ui.tray.run_detached()
    app.preload_models()  # 后台加载模型（悬浮窗"加载中"，完成后"待命中"）
    def keep_target() -> None:
        if not app._closing:
            app._inserter.guard_focus()
            ui.widget.root.after(40, keep_target)
    keep_target()
    loop()
    ui.widget.root.mainloop()
    return 0


def main(output=None) -> int:
    import pythoncom
    pythoncom.CoInitialize()
    from voice2text.desktop import SingleInstance, install_output
    if output is None:
        output = install_output()
    instance = SingleInstance()
    try:
        if instance.already_running:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "voice2text 已在运行，请查看右下角托盘。", "voice2text", 0x40)
            return 0
        return _gui_main(output)
    finally:
        instance.close()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())

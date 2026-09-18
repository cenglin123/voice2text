"""程序入口：常驻进程 = 托盘 + 悬浮窗 GUI + 热键/听写引擎。

线程模型（Windows 上 tkinter 主循环必须在主线程）：
- 主线程：tkinter mainloop（悬浮窗 + 设置窗），每 150ms tick() 轮询
- pystray 托盘：daemon 线程 run()，动作经 cmd_queue 投递主线程
- keyboard 热键：自有线程回调，只 set Event
- 识别：ASR worker 线程；停止时的统一校对在后台线程（结果经 ui_queue 回 UI）

听写流程（用户决策）：Alt+V 开始 → 流式上屏（听写期间屏幕文字只增不改）→
Alt+V 停止 → 后台统一校对（分块）→ 替换为整洁文本。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import types

import winsound

from voice2text import __version__
from voice2text.asr import ASRSessionWorker, StreamingASR
from voice2text.capture import WATCHDOG_SECONDS, CaptureError, MicrophoneCapture
from voice2text.config import AppConfig, PROJECT_ROOT, load_config
from voice2text.hotkey import HotkeyListener
from voice2text.input import TextInserter
from voice2text.proofread import Proofreader, chunk_sentences

ASR_REQUIRED_FILES = (
    "encoder-epoch-99-avg-1.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.onnx",
    "tokens.txt",
)


def check_models(cfg: AppConfig) -> tuple[bool, str]:
    """检查模型文件。识别模型缺失=致命；校对模型缺失=降级警告（运行期同样会降级）。"""
    missing_asr = [name for name in ASR_REQUIRED_FILES if not cfg.asr_file(name).is_file()]
    for name in missing_asr:
        print(f"  [缺失] ASR 模型文件: {cfg.asr_file(name)}")
    llm_missing = cfg.proofread_enabled and not cfg.llm_model_path.is_file()
    if llm_missing:
        print(f"  [警告] 校对模型缺失（{cfg.llm_model_path}），二次校对将停用")
    detail = "；".join(
        [f"识别模型缺失: {n}" for n in missing_asr]
        + ([f"校对模型缺失: {cfg.llm_model_path.name}（可继续使用，无二次校对）"] if llm_missing else [])
    )
    return (len(missing_asr) == 0), detail


class DictationApp:
    """听写引擎：由 UI 主线程的 tick() 驱动；耗时操作全部在后台线程。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._capture = MicrophoneCapture(
            target_rate=cfg.sample_rate, debug_dump_wav=cfg.debug_dump_wav
        )
        self._inserter = TextInserter(
            cfg.non_editable_process_blacklist, use_clipboard=cfg.input_clipboard
        )
        self._asr: StreamingASR | None = None
        self._proofreader: Proofreader | None = None
        self._worker: ASRSessionWorker | None = None
        self._session_gen = 0  # 会话代数：旧 worker 的迟到回调不得写新会话的屏
        self._locked_sentences: list[str] = []
        self.hotkey: HotkeyListener | None = None
        self.cmd_queue: "queue.Queue[tuple[str, None]]" = queue.Queue()
        self.ui_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()  # ("state", s) 给 UI
        self.widget_visible = True  # 托盘动态文案用（UI 侧维护）
        self._active = False
        self._busy = False  # 启动/停止进行中，忽略新的切换请求
        self.apply_settings_scale: tuple[float, float] | None = None  # 设置保存后待应用的外观
        self._models_ready = threading.Event()  # 预加载完成（成功与否都置位）

    @property
    def active(self) -> bool:
        return self._active

    def push_state(self, state: str) -> None:
        self.ui_queue.put(("state", state))

    # ---- 启动 / 停止（后台线程执行）----

    def preload_models(self) -> None:
        """启动即后台加载识别/校对模型（悬浮窗显示"加载中"，首次听写零等待）。"""
        def _load() -> None:
            try:
                self._asr = StreamingASR(self._cfg)
                print("  （后台加载识别模型完成）")
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
        """UI/热键请求切换。busy 或模型未就绪时忽略。"""
        if self._busy:
            return
        if not self._models_ready.is_set():
            print("[提示] 模型加载中，请稍候再试")
            return
        self._busy = True
        if self._active:
            self.push_state("proofreading")
            threading.Thread(target=self._finish_toggle, daemon=True).start()
        else:
            threading.Thread(target=self._start_toggle, daemon=True).start()

    def _start_toggle(self) -> None:
        try:
            self._start_session()
            self.push_state("listening" if self._active else "idle")
        finally:
            self._busy = False

    def _finish_toggle(self) -> None:
        try:
            self._stop_session()
            self.push_state("idle")
        finally:
            self._busy = False

    def _start_session(self) -> None:
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
        self._cue("start")
        print(f"[听写中] 再按 {self._cfg.hotkey} 停止")

    def _stop_session(self) -> None:
        self._session_gen += 1  # 拦截 join 超时后残留 worker 的迟到提交/替换
        self._capture.stop()  # None 哨兵 → 识别线程完成尾句后退出
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            if self._worker.is_alive():
                print("[警告] 识别线程未在预期内结束（其迟到回调会被会话代数拦截）")
            self._worker = None
        self._finalize_proofread()
        self._inserter.end_session()
        self._active = False
        self._cue("stop")
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
        shift = 0
        optimized = 0
        for start, end, text in chunks:
            t0 = time.monotonic()
            corrected = self._proofreader.proofread(text)
            if corrected is None or time.monotonic() - t0 > self._cfg.proofread_timeout_seconds:
                continue
            if self._inserter.replace_committed_range(start - shift, end - shift, corrected):
                optimized += 1
                shift += end - start
        print(f"[校对完成] {optimized}/{len(chunks)} 块已优化")

    def _cue(self, kind: str) -> None:
        if self._cfg.sound_cue:
            try:
                winsound.MessageBeep(winsound.MB_OK if kind == "start" else winsound.MB_ICONASTERISK)
            except Exception:  # noqa: BLE001 —— 声卡不可用不影响听写
                pass

    # ---- 识别线程回调 ----

    def _on_partial(self, gen: int, text: str) -> None:
        if gen != self._session_gen:
            return
        self._inserter.replace_current(text)

    def _on_sentence(self, gen: int, text: str) -> None:
        if gen != self._session_gen:
            return
        self._inserter.replace_current(text)
        committed = self._inserter.commit_current()
        if committed:
            self._locked_sentences.append(committed)

    # ---- UI 主线程每帧调用 ----

    def tick(self) -> None:
        """轮询热键/托盘命令/错误条件。必须在主线程、非阻塞。"""
        if self.hotkey is not None and self.hotkey.wait_toggle(0):
            self.hotkey.clear_toggle()
            self.request_toggle()

        while True:
            try:
                cmd, _ = self.cmd_queue.get_nowait()
            except queue.Empty:
                break
            if cmd == "toggle":
                self.request_toggle()

        if self._active and not self._busy:
            if self._capture.error or self._inserter.aborted:
                reason = self._capture.error or "剪贴板模式持续被占用，上屏已暂停"
                print(f"[听写中断] {reason}")
                self.push_state("proofreading")
                self._busy = True
                threading.Thread(target=self._finish_toggle, daemon=True).start()
            elif self._capture.seconds_since_audio() > WATCHDOG_SECONDS:
                print("[听写中断] 麦克风无响应，可能已断开。请检查设备后重新开始。")
                self.push_state("proofreading")
                self._busy = True
                threading.Thread(target=self._finish_toggle, daemon=True).start()

    def apply_settings(self, cfg_dict: dict) -> dict:
        """设置窗口保存回调（主线程）：热键重注册；返回生效值供写盘。

        热键 rebind 失败时保留旧组合——调用方以返回值为准持久化，
        避免"磁盘是坏热键、运行中是旧热键"的分叉。
        """
        new_combo = str(cfg_dict.get("hotkey", ""))
        if self.hotkey is not None and new_combo and new_combo != self.hotkey.combo:
            try:
                self.hotkey.rebind(new_combo)
                self._cfg.hotkey = new_combo
                print(f"[设置] 热键已更换为 {new_combo}")
            except Exception as exc:  # noqa: BLE001
                cfg_dict["hotkey"] = self.hotkey.combo  # rebind 失败回退旧值
                print(f"[设置] 热键更换失败（{exc}），保留 {self.hotkey.combo}")
        self._cfg.proofread_enabled = bool(cfg_dict.get("proofread_enabled", True))
        self._cfg.sound_cue = bool(cfg_dict.get("sound_cue", True))
        self._cfg.widget_scale = float(cfg_dict.get("widget_scale", 1.0))
        self._cfg.widget_opacity = float(cfg_dict.get("widget_opacity", 0.92))
        self.apply_settings_scale = (self._cfg.widget_scale, self._cfg.widget_opacity)
        return dict(cfg_dict)


def _gui_main() -> int:
    cfg = load_config()
    print(f"voice2text v{__version__}  热键: {cfg.hotkey}")
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
        cfg.proofread_enabled = False
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, missing_detail, "voice2text", 0x30)
        except Exception:  # noqa: BLE001
            pass

    # 延迟导入：tkinter 仅在模型就绪后需要
    from voice2text.settings_window import SettingsWindow
    from voice2text.tray import build_tray, update_icon
    from voice2text.widget import DictationWidget

    app = DictationApp(cfg)
    try:
        app.hotkey = HotkeyListener(cfg.hotkey)
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 全局热键初始化失败：{exc}")
        return 1

    ui = types.SimpleNamespace(widget=None, settings=None, tray=None, visible=True)

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
        opacity=cfg.widget_opacity,
        on_toggle=app.request_toggle,
        on_settings=lambda: app.cmd_queue.put(("settings", None)),
        on_hide=hide_widget,
        on_quit=quit_app,
    )

    def drain_cmds() -> None:
        while True:
            try:
                cmd, _ = app.cmd_queue.get_nowait()
            except queue.Empty:
                return
            if cmd == "toggle_widget":
                (hide_widget if ui.visible else show_widget)()
            elif cmd == "settings":
                w = ui.settings
                if w is None or not w.root.winfo_exists():
                    cfg_dict = {
                        "hotkey": cfg.hotkey,
                        "widget_scale": cfg.widget_scale,
                        "widget_opacity": cfg.widget_opacity,
                        "proofread_enabled": cfg.proofread_enabled,
                        "sound_cue": cfg.sound_cue,
                    }
                    ui.settings = SettingsWindow(cfg_dict, app.apply_settings)
                else:
                    w.root.attributes("-topmost", True)
                    w.root.lift()
            elif cmd == "help":
                os.startfile(str(PROJECT_ROOT / "README.md"))  # noqa: S606
            elif cmd == "quit":
                raise SystemExit

    last_state = [None]

    def tick() -> None:
        ui.widget.pump(app.ui_queue)
        drain_cmds()
        app.tick()
        if app.apply_settings_scale:  # 设置保存后应用新外观（M1/M2：主线程 ui.widget）
            widget_scale, widget_opacity = app.apply_settings_scale
            ui.widget.apply_appearance(widget_scale, widget_opacity)
            app.apply_settings_scale = None
        if ui.widget.state != last_state[0]:
            last_state[0] = ui.widget.state
            update_icon(ui.tray, ui.widget.state)

    def loop() -> None:
        try:
            tick()
        except SystemExit:
            try:
                if app.active:
                    app._capture.stop()
                    app._inserter.end_session()
                if app.hotkey is not None:
                    app.hotkey.shutdown()
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
        ui.widget.root.after(150, loop)

    ui.tray = build_tray(app.cmd_queue, app, hotkey=cfg.hotkey)
    threading.Thread(target=ui.tray.run, daemon=True).start()
    app.preload_models()  # 后台加载模型（悬浮窗"加载中"，完成后"待命中"）
    loop()
    ui.widget.root.mainloop()
    return 0


def main() -> int:
    # pythonw 下 stdout/stderr 为 None，print 会崩——重定向到 devnull
    if sys.stdout is None or sys.stderr is None:
        devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        sys.stdout = sys.stderr = devnull
    return _gui_main()


if __name__ == "__main__":
    sys.exit(main())

"""设置窗口（tkinter，美术稿 assets/设置菜单.jpg）：快捷键、悬浮窗外观、功能开关。

保存 = 应用到运行中的组件（热键重注册/悬浮窗缩放透明度/校对开关）+ 写回 config.json。
自启动用 HKCU Run 注册表项，指向 run_gui.pyw（pythonw 无控制台启动）。
"""

from __future__ import annotations

import json
import tkinter
import winreg
from pathlib import Path

import keyboard  # type: ignore[import-untyped]

from voice2text.config import PROJECT_ROOT

_BG = "#1E2836"
_CARD = "#26303F"
_TEXT = "#E8EDF4"
_SUB = "#97A3B4"
_ACCENT = "#4C9DF8"

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "voice2text"


# ---- 开机自启动（注册表 HKCU Run）----

def _pythonw_path() -> str | None:
    """当前解释器对应的 pythonw.exe。"""
    exe = Path(__import__("sys").executable)
    pythonw = exe.with_name("pythonw.exe")
    return str(pythonw) if pythonw.is_file() else None


def get_autostart() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """注册/注销自启动。返回是否成功（缺 pythonw 时失败）。

    -I 隔离模式：忽略用户站点包（nuget 普通布局无 ._pth，登录启动无
    PYTHONNOUSERSITE 保护）；run_gui.pyw 自行把项目根插 sys.path，不受影响。
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if not enabled:
                try:
                    winreg.DeleteValue(k, _RUN_NAME)
                except FileNotFoundError:
                    pass
                return True
            pythonw = _pythonw_path()
            script = PROJECT_ROOT / "run_gui.pyw"
            if not pythonw or not script.is_file():
                return False
            winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, f'"{pythonw}" -I "{script}"')
            return True
    except OSError:
        return False


_MOD_CTRL = 0x0004
_MOD_SHIFT = 0x0001
_MOD_ALT = 0x20000  # Windows 下 Tk 的 Alt 掩码；部分版本为 Mod1(0x8)
_MOD_ALT_ALT = 0x0008


def _normalize_combo(ev) -> str | None:
    """把 tkinter 按键事件规范化为 keyboard 库组合串（必须含 Ctrl 或 Alt，防单键劫持）。"""
    name = ev.keysym.lower()
    if name in (
        "shift_l", "shift_r", "control_l", "control_r", "alt_l", "alt_r",
        "win_l", "win_r", "meta_l", "meta_r", "caps_lock",
    ):
        return None
    s = int(ev.state)
    ctrl = bool(s & _MOD_CTRL)
    alt = bool(s & (_MOD_ALT | _MOD_ALT_ALT))
    shift = bool(s & _MOD_SHIFT)
    if not (ctrl or alt):
        return None
    parts = []
    if ctrl:
        parts.append("ctrl")
    if alt:
        parts.append("alt")
    if shift:
        parts.append("shift")
    parts.append(name)
    return "+".join(parts)


class SettingsWindow:
    """设置窗口。apply_cb(config_dict) 在保存时被调用（主线程）。"""

    def __init__(self, cfg_dict: dict, apply_cb) -> None:
        self._apply_cb = apply_cb
        self._cfg = dict(cfg_dict)
        self._capturing = False

        self.root = tkinter.Toplevel()
        self.root.title("语音输入 设置")
        self.root.configure(bg=_BG)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        pad = {"padx": 18, "pady": 8}
        tkinter.Label(
            self.root, text="语音输入", bg=_BG, fg=_TEXT,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w", padx=18, pady=(14, 2))

        # ---- 快捷键卡片 ----
        card = self._card()
        tkinter.Label(card, text="快捷键", bg=_CARD, fg=_TEXT, font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w", padx=14, pady=(10, 0)
        )
        tkinter.Label(card, text="按下快捷键开始或停止语音输入", bg=_CARD, fg=_SUB, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", padx=14
        )
        row = tkinter.Frame(card, bg=_CARD)
        row.pack(fill="x", padx=14, pady=(4, 12))
        self._hotkey_var = tkinter.StringVar(value=self._display_combo(self._cfg["hotkey"]))
        self._hotkey_entry = tkinter.Entry(
            row, textvariable=self._hotkey_var, state="readonly", readonlybackground="#161E2A",
            fg=_TEXT, insertbackground=_TEXT, font=("Consolas", 10), relief="flat",
        )
        self._hotkey_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._hotkey_btn = tkinter.Button(
            row, text="修改", command=self._start_capture, bg="#33405A", fg=_TEXT,
            activebackground=_ACCENT, activeforeground="#fff", relief="flat", padx=14,
        )
        self._hotkey_btn.pack(side="left", padx=(8, 0), ipady=2)
        card.pack(fill="x", **pad)

        # ---- 悬浮窗设置卡片 ----
        card = self._card()
        tkinter.Label(card, text="悬浮窗设置", bg=_CARD, fg=_TEXT, font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w", padx=14, pady=(10, 0)
        )
        tkinter.Label(card, text="调整悬浮窗的大小与透明度", bg=_CARD, fg=_SUB, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", padx=14
        )
        self._scale_var = tkinter.DoubleVar(value=float(self._cfg.get("widget_scale", 1.0)) * 100)
        self._opacity_var = tkinter.DoubleVar(value=float(self._cfg.get("widget_opacity", 0.92)) * 100)
        for label, var, lo, hi in (("窗口大小", self._scale_var, 50, 150), ("不透明度", self._opacity_var, 30, 100)):
            row = tkinter.Frame(card, bg=_CARD)
            row.pack(fill="x", padx=14, pady=4)
            tkinter.Label(row, text=label, bg=_CARD, fg=_TEXT, width=8, anchor="w", font=("Microsoft YaHei UI", 9)).pack(side="left")
            tkinter.Scale(
                row, variable=var, from_=lo, to=hi, orient="horizontal", showvalue=False,
                bg=_CARD, fg=_TEXT, highlightthickness=0, troughcolor="#161E2A",
                activebackground=_ACCENT, sliderrelief="flat", length=220,
            ).pack(side="left", fill="x", expand=True, padx=8)
            tkinter.Label(row, textvariable=var, bg=_CARD, fg=_SUB, width=5, font=("Consolas", 9)).pack(side="left")
        card.pack(fill="x", **pad)

        # ---- 功能设置卡片 ----
        card = self._card()
        tkinter.Label(card, text="功能设置", bg=_CARD, fg=_TEXT, font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w", padx=14, pady=(10, 0)
        )
        self._proof_var = tkinter.BooleanVar(value=bool(self._cfg.get("proofread_enabled", True)))
        self._sound_var = tkinter.BooleanVar(value=bool(self._cfg.get("sound_cue", True)))
        self._autostart_var = tkinter.BooleanVar(value=get_autostart())
        for label, sub, var in (
            ("开启二次校对", "语音输入停止后自动进行智能校对，提高准确率", self._proof_var),
            ("录音时播放提示音", "开始和停止录音时播放提示音", self._sound_var),
            ("开机自启动", "随系统启动，方便随时使用", self._autostart_var),
        ):
            row = tkinter.Frame(card, bg=_CARD)
            row.pack(fill="x", padx=14, pady=4)
            tkinter.Checkbutton(
                row, variable=var, bg=_CARD, fg=_TEXT, activebackground=_CARD,
                selectcolor="#161E2A", highlightthickness=0, relief="flat",
            ).pack(side="left")
            box = tkinter.Frame(row, bg=_CARD)
            box.pack(side="left")
            tkinter.Label(box, text=label, bg=_CARD, fg=_TEXT, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
            tkinter.Label(box, text=sub, bg=_CARD, fg=_SUB, font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        card.pack(fill="x", **pad)

        tkinter.Button(
            self.root, text="保存并应用", command=self._save, bg=_ACCENT, fg="#FFFFFF",
            activebackground="#3B82D8", activeforeground="#fff", relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"), padx=20, pady=4,
        ).pack(pady=(2, 16))

        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def _card(self) -> tkinter.Frame:
        return tkinter.Frame(self.root, bg=_CARD, highlightbackground="#33405A", highlightthickness=1)

    @staticmethod
    def _display_combo(combo: str) -> str:
        return " + ".join(p.capitalize() for p in combo.split("+"))

    # ---- 快捷键捕获 ----

    def _start_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self._hotkey_btn.config(text="按下组合键…", bg=_ACCENT)
        self._hotkey_entry.config(fg=_ACCENT)
        self._hotkey_var.set("")

        def capture_key(ev):
            if not self._capturing:
                return
            try:
                if ev.keysym == "Escape":  # Esc 取消
                    self._finish_capture(None)
                    return "break"
                self._finish_capture(_normalize_combo(ev))
                return "break"
            except tkinter.TclError:
                return "break"  # 窗口已销毁（捕获中关窗），静默退出捕获态

        self.root.bind_all("<Key>", capture_key, add="+")

    def _finish_capture(self, combo: str | None) -> None:
        self._capturing = False
        self.root.unbind_all("<Key>")
        self._hotkey_btn.config(text="修改", bg="#33405A")
        self._hotkey_entry.config(fg=_TEXT)
        if combo:
            self._cfg["hotkey"] = combo
            self._hotkey_var.set(self._display_combo(combo))
        else:
            self._hotkey_var.set(self._display_combo(self._cfg["hotkey"]))

    # ---- 保存 ----

    def _save(self) -> None:
        self._finish_capture(None)  # 若在捕获态保存/关窗，先干净退出捕获
        self._cfg["widget_scale"] = round(self._scale_var.get() / 100, 2)
        self._cfg["widget_opacity"] = round(self._opacity_var.get() / 100, 2)
        self._cfg["proofread_enabled"] = bool(self._proof_var.get())
        self._cfg["sound_cue"] = bool(self._sound_var.get())
        self._cfg["autostart"] = bool(self._autostart_var.get())
        set_autostart(bool(self._autostart_var.get()))
        # 先应用（热键 rebind 失败会回退旧值），再以生效值写盘
        effective = self._apply_cb(dict(self._cfg)) or dict(self._cfg)
        self._cfg.update(effective)
        # 写回 config.json（保留未知键）
        cfg_path = PROJECT_ROOT / "config.json"
        try:
            on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            on_disk = {}
        on_disk.update(self._cfg)
        cfg_path.write_text(json.dumps(on_disk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.root.destroy()

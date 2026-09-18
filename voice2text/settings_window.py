"""设置窗口（tkinter，美术稿 assets/设置菜单.jpg）：快捷键、悬浮窗外观、功能开关。

UI 全部 Canvas 手绘（无边框自定义标题栏、圆角滑条、胶囊开关），与悬浮窗同风格。
保存 = 先应用（热键 rebind 失败回退旧值），再以生效值写 config.json。
自启动用 HKCU Run 注册表项，指向 run_gui.pyw（pythonw -I 无控制台启动）。
"""

from __future__ import annotations

import json
import tkinter
import winreg
from pathlib import Path

from voice2text.config import PROJECT_ROOT

_BG = "#151D2A"
_CARD = "#212B3B"
_CARD_EDGE = "#33405A"
_TEXT = "#E8EDF4"
_SUB = "#97A3B4"
_ACCENT = "#4C9DF8"
_TRACK = "#161E2A"

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

    -I 隔离模式：忽略用户站点包（独立 runtime 无 PYTHONNOUSERSITE 保护）；
    run_gui.pyw 自行把项目根插 sys.path，不受影响。
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


# ---- 手绘控件 ----

class Toggle(tkinter.Canvas):
    """胶囊开关（美术稿样式）：开=蓝色，关=深灰。"""

    def __init__(self, master, variable: tkinter.BooleanVar, command=None):
        super().__init__(master, width=46, height=24, bg=master["bg"], highlightthickness=0, cursor="hand2")
        self._var = variable
        self._command = command
        self.bind("<Button-1>", self._flip)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        on = bool(self._var.get())
        track = _ACCENT if on else "#39465C"
        self.create_round = None
        # 圆角轨道
        self.create_polygon(
            [1, 2, 45, 2, 45, 22, 1, 22], smooth=True, fill=track, outline=""
        )
        kx = 33 if on else 13
        self.create_oval(kx - 8, 4, kx + 8, 20, fill="#F2F5F9", outline="")

    def _flip(self, _ev) -> None:
        self._var.set(not bool(self._var.get()))
        self._draw()
        if self._command:
            self._command()


class Slider(tkinter.Canvas):
    """圆角滑条：轨道 + 已填充段 + 圆形旋钮，拖动设置 0~100。"""

    def __init__(self, master, variable: tkinter.DoubleVar, w: int = 240):
        super().__init__(master, width=w, height=26, bg=master["bg"], highlightthickness=0)
        self._var = variable
        self._track_w = w
        self._pad = 8
        self.bind("<Button-1>", self._on_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self._draw()

    def _pct(self) -> float:
        v = float(self._var.get())
        return max(0.0, min(1.0, v / 100.0))

    def _draw(self) -> None:
        self.delete("all")
        y = 13
        x0, x1 = self._pad, self._track_w - self._pad
        self.create_rectangle(x0, y - 2, x1, y + 2, fill=_TRACK, width=0)
        px = x0 + int((x1 - x0) * self._pct())
        if px > x0:
            self.create_rectangle(x0, y - 2, px, y + 2, fill=_ACCENT, width=0)
        self.create_oval(px - 7, y - 7, px + 7, y + 7, fill="#F2F5F9", outline="")

    def _on_drag(self, ev) -> None:
        x0, x1 = self._pad, self._track_w - self._pad
        pct = max(0.0, min(1.0, (ev.x - x0) / (x1 - x0)))
        self._var.set(round(pct * 100))
        self._draw()


def _rounded(canvas: tkinter.Canvas, x0, y0, x1, y1, r, **kw) -> None:
    pts = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
        x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    canvas.create_polygon(pts, smooth=True, **kw)


# ---- 组合串规范化 ----

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
    """设置窗口。apply_cb(config_dict) 在保存时被调用（主线程），返回生效值供写盘。"""

    def __init__(self, cfg_dict: dict, apply_cb) -> None:
        self._apply_cb = apply_cb
        self._cfg = dict(cfg_dict)
        self._capturing = False

        W, H = 460, 560
        self.root = tkinter.Toplevel()
        self.root.title("语音输入 设置")
        self.root.overrideredirect(True)  # 无边框：自绘标题栏
        self.root.attributes("-topmost", True)
        self.root.configure(bg=_BG)
        self.root.geometry(f"{W}x{H}+160+120")

        # 标题栏（可拖动）
        tb = tkinter.Canvas(self.root, width=W, height=36, bg="#121926", highlightthickness=0)
        tb.pack(fill="x")
        tb.create_text(16, 18, text="语音输入  设置", anchor="w", fill=_TEXT,
                       font=("Microsoft YaHei UI", 10, "bold"))
        cx = W - 22
        tb.create_line(cx - 6, 12, cx + 6, 24, fill=_SUB, width=2)
        tb.create_line(cx - 6, 24, cx + 6, 12, fill=_SUB, width=2)
        tb.create_rectangle(cx - 12, 0, cx + 12, 36, fill="", outline="", tags="close")
        tb.tag_bind("close", "<Button-1>", lambda e: self.root.destroy())
        self._tb = tb
        tb.bind("<ButtonPress-1>", self._tb_press)
        tb.bind("<B1-Motion>", self._tb_motion)
        self._tb_off = None

        body = tkinter.Frame(self.root, bg=_BG)
        body.pack(fill="both", expand=True, padx=18)

        def section_title(text):
            tkinter.Label(body, text=text, bg=_BG, fg=_TEXT,
                          font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", pady=(12, 6))

        def card(parent):
            f = tkinter.Frame(parent, bg=_CARD, highlightbackground=_CARD_EDGE, highlightthickness=1)
            return f

        # ---- 快捷键 ----
        section_title("快捷键")
        c1 = card(body)
        c1.pack(fill="x")
        tkinter.Label(c1, text="按下快捷键开始或停止语音输入", bg=_CARD, fg=_SUB,
                      font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=16, pady=(12, 6))
        row = tkinter.Frame(c1, bg=_CARD)
        row.pack(fill="x", padx=16, pady=(0, 14))
        self._hotkey_var = tkinter.StringVar(value=self._display_combo(self._cfg["hotkey"]))
        self._hotkey_entry = tkinter.Entry(
            row, textvariable=self._hotkey_var, state="readonly", readonlybackground=_TRACK,
            fg=_TEXT, insertbackground=_TEXT, font=("Consolas", 11), relief="flat",
        )
        self._hotkey_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self._hotkey_btn = tkinter.Button(
            row, text=" 修改 ", command=self._start_capture, bg="#2E3A4E", fg=_TEXT,
            activebackground=_ACCENT, activeforeground="#fff", relief="flat",
            font=("Microsoft YaHei UI", 9), bd=0, padx=16, pady=5, cursor="hand2",
        )
        self._hotkey_btn.pack(side="left", padx=(10, 0))

        # ---- 悬浮窗设置 ----
        section_title("悬浮窗设置")
        c2 = card(body)
        c2.pack(fill="x")
        tkinter.Label(c2, text="调整悬浮窗的大小与不透明度", bg=_CARD, fg=_SUB,
                      font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=16, pady=(12, 4))
        self._scale_var = tkinter.DoubleVar(value=round(float(self._cfg.get("widget_scale", 1.0)) * 100))
        self._opacity_var = tkinter.DoubleVar(value=round(float(self._cfg.get("widget_opacity", 0.92)) * 100))
        for label, var in (("窗口大小", self._scale_var), ("不透明度", self._opacity_var)):
            row = tkinter.Frame(c2, bg=_CARD)
            row.pack(fill="x", padx=16, pady=6)
            tkinter.Label(row, text=label, bg=_CARD, fg=_TEXT, width=8, anchor="w",
                          font=("Microsoft YaHei UI", 9)).pack(side="left")
            Slider(row, var, w=230).pack(side="left", padx=6)
            tkinter.Label(row, textvariable=var, bg=_CARD, fg=_SUB, width=5,
                          font=("Consolas", 9)).pack(side="left")
        tkinter.Frame(c2, bg=_CARD, height=12).pack()

        # ---- 功能设置 ----
        section_title("功能设置")
        c3 = card(body)
        c3.pack(fill="x")
        self._proof_var = tkinter.BooleanVar(value=bool(self._cfg.get("proofread_enabled", True)))
        self._sound_var = tkinter.BooleanVar(value=bool(self._cfg.get("sound_cue", True)))
        self._autostart_var = tkinter.BooleanVar(value=get_autostart())
        for label, sub, var in (
            ("开启二次校对", "语音输入停止后自动进行智能校对，提高准确率", self._proof_var),
            ("录音时播放提示音", "开始和停止录音时播放提示音", self._sound_var),
            ("开机自启动", "随系统启动，方便随时使用", self._autostart_var),
        ):
            row = tkinter.Frame(c3, bg=_CARD)
            row.pack(fill="x", padx=16, pady=7)
            Toggle(row, var).pack(side="left", padx=(0, 12))
            box = tkinter.Frame(row, bg=_CARD)
            box.pack(side="left")
            tkinter.Label(box, text=label, bg=_CARD, fg=_TEXT,
                          font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
            tkinter.Label(box, text=sub, bg=_CARD, fg=_SUB,
                          font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        tkinter.Frame(c3, bg=_CARD, height=8).pack()

        # 保存按钮（手绘圆角）
        btn = tkinter.Canvas(body, width=140, height=36, bg=_BG, highlightthickness=0, cursor="hand2")
        btn.pack(pady=16)
        _rounded(btn, 0, 0, 139, 35, 18, fill=_ACCENT, outline="")
        btn.create_text(70, 18, text="保存并应用", fill="#FFFFFF", font=("Microsoft YaHei UI", 10, "bold"))
        btn.bind("<Button-1>", lambda e: self._save())

        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def _tb_press(self, ev) -> None:
        self._tb_off = (ev.x, ev.y)

    def _tb_motion(self, ev) -> None:
        if self._tb_off is None:
            return
        self.root.geometry(f"+{self.root.winfo_x() + ev.x - self._tb_off[0]}"
                           f"+{self.root.winfo_y() + ev.y - self._tb_off[1]}")

    def _card(self):
        pass  # 兼容占位

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
                return "break"
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
        self._hotkey_btn.config(text=" 修改 ", bg="#2E3A4E")
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

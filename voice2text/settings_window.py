"""设置窗口（tkinter，美术稿 assets/设置菜单.jpg）：快捷键、悬浮窗外观、功能开关。

深蓝侧栏与圆角分区，原生文字控件结合超采样绘图，小屏幕支持滚动。
保存 = 先应用（热键 rebind 失败回退旧值），再以生效值写 config.json。
自启动用 HKCU Run 注册表项，指向 run_gui.pyw（pythonw -I 无控制台启动）。
"""

from __future__ import annotations

import json
import math
import tkinter
import tkinter.messagebox as messagebox
import tkinter.font as tkfont
import winreg
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

from voice2text.config import PROJECT_ROOT, load_config
from voice2text.model_download import model_download
from voice2text import __version__
from voice2text.dpi import system_scale
from voice2text.update import update_manager

_BG = "#16243D"
_CARD = "#20314D"
_CARD_EDGE = "#344865"
_TEXT = "#EDF3FC"
_SUB = "#A5B5CD"
_ACCENT = "#519CFF"
_TRACK = "#132139"
_SIDE = "#1B2D4B"
_FONT = "Microsoft YaHei UI"
_WINDOW_KEY = "#010203"
_WINDOW_RADIUS = 14


def _ui_scale(master) -> float:
    return float(getattr(master.winfo_toplevel(), "_v2t_dpi_scale", 1.0))


def _nav_icon(kind: str, scale: float = 1.0) -> ImageTk.PhotoImage:
    image = Image.new("RGBA", (72, 72))
    d = ImageDraw.Draw(image)
    color = "#BED1EC"
    if kind == "all":
        points = []
        for i in range(48):
            angle = math.tau * i / 48
            radius = 27 if i % 6 in (1, 2, 3, 4) else 21
            points.append((36 + radius * math.cos(angle), 36 + radius * math.sin(angle)))
        d.line(points + [points[0]], fill=color, width=4, joint="curve")
        d.ellipse((27, 27, 45, 45), outline=color, width=4)
    elif kind == "hotkey":
        d.rounded_rectangle((8, 17, 64, 55), radius=6, outline=color, width=4)
        for y in (27, 36):
            for x in (19, 30, 41, 52):
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
        d.line((24, 46, 48, 46), fill=color, width=3)
    elif kind == "appearance":
        d.rounded_rectangle((9, 12, 63, 49), radius=5, outline=color, width=4)
        d.line((36, 49, 36, 60), fill=color, width=4)
        d.line((24, 60, 48, 60), fill=color, width=4)
    else:
        d.rounded_rectangle((27, 9, 45, 42), radius=9, outline=color, width=4)
        d.arc((18, 22, 54, 53), 0, 180, fill=color, width=4)
        d.line((36, 53, 36, 63), fill=color, width=4)
        d.line((27, 63, 45, 63), fill=color, width=4)
    side = round(24 * scale)
    return ImageTk.PhotoImage(image.resize((side, side), Image.Resampling.LANCZOS))


def _surface(w: int, h: int, radius: int, fill: str, edge: str | None = None) -> ImageTk.PhotoImage:
    """控件背景统一超采样，避免 Tk 原生圆弧的锯齿。"""
    image = Image.new("RGBA", (w * 3, h * 3))
    ImageDraw.Draw(image).rounded_rectangle(
        (1, 1, w * 3 - 2, h * 3 - 2), radius=radius * 3,
        fill=fill, outline=edge, width=3,
    )
    return ImageTk.PhotoImage(image.resize((w, h), Image.Resampling.LANCZOS))


class Card(tkinter.Canvas):
    """圆角卡片，内部仍用原生布局管理文本与交互。"""

    def __init__(self, master):
        self._dpi = _ui_scale(master)
        p = lambda value: round(value * self._dpi)
        super().__init__(master, bg=_BG, highlightthickness=0, height=1)
        self.content = tkinter.Frame(self, bg=_CARD)
        self._item = self.create_window(p(18), p(10), window=self.content, anchor="nw")
        self.bind("<Configure>", self._layout)
        self.content.bind("<Configure>", self._layout)

    def _layout(self, _ev=None):
        p = lambda value: round(value * self._dpi)
        w = max(p(60), self.winfo_width())
        self.itemconfigure(self._item, width=w - p(36))
        h = self.content.winfo_reqheight() + p(20)
        self.configure(height=h)
        self._image = _surface(w, h, p(12), _CARD, _CARD_EDGE)
        self.delete("surface")
        self.create_image(0, 0, image=self._image, anchor="nw", tags="surface")
        self.tag_lower("surface")

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
        self._dpi = _ui_scale(master)
        super().__init__(master, width=round(46 * self._dpi), height=round(26 * self._dpi), bg=master["bg"], highlightthickness=1,
                         highlightbackground=master["bg"], highlightcolor=_ACCENT,
                         cursor="hand2", takefocus=True)
        self._var = variable
        self._command = command
        self.bind("<Button-1>", self._flip)
        self.bind("<space>", self._flip)
        self._draw()

    def _draw(self) -> None:
        p = lambda value: round(value * self._dpi)
        self.delete("all")
        on = bool(self._var.get())
        track = _ACCENT if on else "#39465C"
        self._image = _surface(p(46), p(26), p(13), track, None if on else "#6C809E")
        self.create_image(0, 0, image=self._image, anchor="nw")
        kx = 33 if on else 13
        self.create_oval(p(kx - 8), p(5), p(kx + 8), p(21), fill="#F2F5F9", outline="")

    def _flip(self, _ev) -> None:
        self._var.set(not bool(self._var.get()))
        self._draw()
        if self._command:
            self._command()


class Slider(tkinter.Canvas):
    """圆角滑条：在调用方指定的百分比范围内拖动或用方向键调整。"""

    def __init__(self, master, variable: tkinter.DoubleVar, w: int = 240,
                 minimum: int = 0, maximum: int = 100):
        self._dpi = _ui_scale(master)
        super().__init__(master, width=round(w * self._dpi), height=round(28 * self._dpi), bg=master["bg"], highlightthickness=1,
                         highlightbackground=master["bg"], highlightcolor=_ACCENT,
                         takefocus=True, cursor="hand2")
        self._var = variable
        self._minimum, self._maximum = minimum, maximum
        self._track_w = round(w * self._dpi)
        # 圆点半径为 9px，另留出 1px Canvas 高亮边框；避免最小/最大值时被裁切。
        self._pad = round(11 * self._dpi)
        self.bind("<Button-1>", self._on_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<Configure>", self._resize)
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        self._draw()

    def _pct(self) -> float:
        v = float(self._var.get())
        return max(0.0, min(1.0, (v - self._minimum) / (self._maximum - self._minimum)))

    def _resize(self, ev):
        self._track_w = ev.width - 2
        self._draw()

    def _step(self, delta):
        self._var.set(max(self._minimum, min(self._maximum, self._var.get() + delta)))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        p = lambda value: round(value * self._dpi)
        y = p(13)
        x0, x1 = self._pad, self._track_w - self._pad
        self.create_line(x0, y, x1, y, fill="#384D6D", width=p(5), capstyle="round")
        px = x0 + int((x1 - x0) * self._pct())
        if px > x0:
            self.create_line(x0, y, px, y, fill=_ACCENT, width=p(5), capstyle="round")
        self.create_oval(px - p(9), y - p(9), px + p(9), y + p(9), fill=_ACCENT, outline="", tags="knob")
        self.create_oval(px - p(5), y - p(5), px + p(5), y + p(5), fill="#E8F2FF", outline="", tags="knob_inner")

    def _on_drag(self, ev) -> None:
        x0, x1 = self._pad, self._track_w - self._pad
        pct = max(0.0, min(1.0, (ev.x - x0) / (x1 - x0)))
        self._var.set(round(self._minimum + pct * (self._maximum - self._minimum)))
        self._draw()


class RoundedButton(tkinter.Canvas):
    """统一的圆角按钮/侧栏项。"""

    def __init__(self, master, text: str, command, width=120, height=42, bg="#304766",
                 fg=_TEXT, active=_ACCENT, image=None, bold=False, anchor="center"):
        self._dpi = _ui_scale(master)
        super().__init__(master, width=round(width * self._dpi), height=round(height * self._dpi), bg=master["bg"],
                         highlightthickness=0, cursor="hand2", takefocus=True)
        self._text, self._command = text, command
        self._fill, self._fg, self._active = bg, fg, active
        self._icon, self._bold, self._anchor = image, bold, anchor
        self._pressed = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self.bind("<ButtonPress-1>", lambda e: setattr(self, "_pressed", True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", lambda e: self._command())
        self.bind("<space>", lambda e: self._command())
        self._draw()

    def set_style(self, *, text=None, bg=None, fg=None) -> None:
        if text is not None:
            self._text = text
        if bg is not None:
            self._fill = bg
        if fg is not None:
            self._fg = fg
        self._draw()

    def _draw(self, hover=False) -> None:
        self.delete("all")
        w, h = max(2, self.winfo_width()), max(2, self.winfo_height())
        self._surface = _surface(w, h, round(8 * self._dpi), self._active if hover else self._fill)
        self.create_image(0, 0, image=self._surface, anchor="nw")
        font_scale = float(getattr(self.winfo_toplevel(), "_v2t_font_scale", 1.0))
        font = (_FONT, -round(14 * self._dpi * font_scale), "bold" if self._bold else "normal")
        if self._anchor == "w":
            x = round(18 * self._dpi)
            if self._icon is not None:
                self.create_image(x, h // 2, image=self._icon, anchor="w")
                x += round(34 * self._dpi)
            self.create_text(x, h // 2, text=self._text, anchor="w", fill=self._fg,
                             font=font)
        else:
            self.create_text(w // 2, h // 2, text=self._text, fill=self._fg,
                             font=font)

    def _release(self, ev) -> None:
        was_pressed, self._pressed = self._pressed, False
        if was_pressed and 0 <= ev.x < self.winfo_width() and 0 <= ev.y < self.winfo_height():
            self._command()


class RoundedField(tkinter.Canvas):
    """带真实左内边距的圆角只读文本框。"""

    def __init__(self, master, variable: tkinter.StringVar):
        self._dpi = _ui_scale(master)
        p = lambda value: round(value * self._dpi)
        super().__init__(master, height=p(42), bg=master["bg"], highlightthickness=0, takefocus=False)
        self.entry = tkinter.Entry(self, textvariable=variable, state="readonly",
                                   readonlybackground=_TRACK, fg=_TEXT,
                                   font=(_FONT, -15), relief="flat", bd=0)
        self._window = self.create_window(p(13), p(21), window=self.entry, anchor="w", height=p(30))
        self.bind("<Configure>", self._layout)
        self._layout()

    def _layout(self, _ev=None) -> None:
        p = lambda value: round(value * self._dpi)
        w = max(p(40), self.winfo_width())
        self._surface = _surface(w, p(42), p(8), _TRACK, _CARD_EDGE)
        self.delete("surface")
        self.create_image(0, 0, image=self._surface, anchor="nw", tags="surface")
        self.tag_lower("surface")
        self.itemconfigure(self._window, width=max(p(10), w - p(26)))

    def set_foreground(self, color: str) -> None:
        self.entry.config(fg=color)


# ---- 组合串规范化 ----

_MODIFIER_KEYSYMS = {
    "control_l": "ctrl", "control_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt",
    "shift_l": "shift", "shift_r": "shift",
}
_KEYSYM_NAMES = {
    "escape": "esc",
    "return": "enter",
    "prior": "page up",
    "next": "page down",
}


def _normalize_combo(keysym: str, modifiers: set[str]) -> str | None:
    """把本次捕获中实际按下的按键规范化为 keyboard 库组合串。"""
    name = keysym.lower()
    if name in (*_MODIFIER_KEYSYMS, "win_l", "win_r", "meta_l", "meta_r", "caps_lock"):
        return None
    parts = [modifier for modifier in ("ctrl", "alt", "shift") if modifier in modifiers]
    parts.append(_KEYSYM_NAMES.get(name, name))
    return "+".join(parts)


class SettingsWindow:
    """设置窗口。apply_cb(config_dict) 在保存时被调用（主线程），返回生效值供写盘。"""

    def _px(self, value: float) -> int:
        return round(value * self._dpi_scale)

    def __init__(self, cfg_dict: dict, apply_cb, preview_image: Image.Image | None = None,
                 on_debug=None, on_update=None, dpi_scale: float | None = None) -> None:
        self._apply_cb = apply_cb
        self._on_debug = on_debug
        self._on_update = on_update
        self._cfg = dict(cfg_dict)
        self._dpi_scale = dpi_scale if dpi_scale is not None else system_scale()
        p = self._px
        self._font_scale = float(self._cfg.get("font_scale", 1.0))
        self._font_widgets = []
        self._capturing = False
        self._preview_source = preview_image
        self._preview_scale = float(cfg_dict.get("widget_scale", 1.0))
        self._cards = {}
        self._nav = {}
        self._nav_images = {}
        self.root = tkinter.Toplevel()
        # 窄屏上保持整套侧栏与页脚可用；高 DPI 倍率仍尽量接近系统设置。
        self._dpi_scale = min(self._dpi_scale, max(1.0, self.root.winfo_screenwidth() / 984))
        self.root._v2t_dpi_scale = self._dpi_scale
        self.root._v2t_font_scale = self._font_scale
        self.root.title("语音输入 设置")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=_WINDOW_KEY)
        width = min(p(920), self.root.winfo_screenwidth() - p(64))
        height = min(p(840), self.root.winfo_screenheight() - p(80))
        top = max(0, min(p(40), self.root.winfo_screenheight() - height))
        self.root.geometry(f"{width}x{height}+{max(0, (self.root.winfo_screenwidth() - width) // 2)}+{top}")
        self.root.after_idle(self._apply_window_rounding)

        border = tkinter.Frame(self.root, bg=_CARD_EDGE)
        border.pack(fill="both", expand=True)
        shell = tkinter.Frame(border, bg=_BG)
        shell.pack(fill="both", expand=True, padx=p(1), pady=p(1))
        sidebar = tkinter.Frame(shell, bg=_SIDE, width=p(196))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tkinter.Frame(sidebar, bg=_SIDE)
        brand.pack(fill="x", padx=p(24), pady=(p(32), p(30)))
        tkinter.Label(brand, text="语音输入", bg=_SIDE, fg=_TEXT,
                      font=(_FONT, -21, "bold")).pack(anchor="w")
        tkinter.Label(brand, text="设置", bg=_SIDE, fg=_SUB,
                      font=(_FONT, -13)).pack(anchor="w", pady=(p(5), 0))
        for key, label in (("all", "常规"), ("hotkey", "快捷键"),
                           ("appearance", "外观"), ("features", "识别与校对")):
            self._nav_images[key] = _nav_icon(key, self._dpi_scale)
            button = RoundedButton(
                sidebar, label, command=lambda name=key: self._select_page(name),
                width=172, height=52, bg=_SIDE, fg=_SUB, active="#304A70",
                image=self._nav_images[key], anchor="w",
            )
            button.pack(fill="x", padx=p(12), pady=p(3))
            self._nav[key] = button
        tkinter.Label(sidebar, text="voice2text\n本地识别 · 离线运行", justify="left",
                      bg=_SIDE, fg=_SUB, font=(_FONT, -12)).pack(side="bottom", anchor="w", padx=p(24), pady=p(24))
        tkinter.Frame(shell, bg=_CARD_EDGE, width=p(1)).pack(side="left", fill="y")
        main = tkinter.Frame(shell, bg=_BG)
        main.pack(side="left", fill="both", expand=True)

        tb = tkinter.Canvas(main, height=p(32), bg=_BG, highlightthickness=0)
        tb.pack(fill="x")
        self._tb = tb
        self._tb_off = None
        def titlebar(ev):
            tb.delete("all")
            cx = ev.width - p(24)
            tb.create_line(cx - p(5), p(11), cx + p(5), p(21), fill=_SUB, width=p(1.5))
            tb.create_line(cx - p(5), p(21), cx + p(5), p(11), fill=_SUB, width=p(1.5))
            tb.create_rectangle(cx - p(17), 0, cx + p(17), p(32), fill="", outline="", tags="close")
            tb.tag_bind("close", "<Button-1>", lambda e: self._close())
        tb.bind("<Configure>", titlebar)
        tb.bind("<ButtonPress-1>", self._tb_press)
        tb.bind("<B1-Motion>", self._tb_motion)
        heading = tkinter.Frame(main, bg=_BG)
        heading.pack(fill="x", padx=p(28), pady=(0, p(12)))
        self._heading = tkinter.Label(heading, text="常规", bg=_BG, fg=_TEXT, font=(_FONT, -24, "bold"))
        self._heading.pack(anchor="w")
        self._subtitle = tkinter.Label(heading, text="自定义语音输入的使用体验", bg=_BG, fg=_SUB, font=(_FONT, -13))
        self._subtitle.pack(anchor="w", pady=(p(4), 0))

        # 页脚固定在滚动区外，小屏幕也始终能保存或取消。
        footer = tkinter.Frame(main, bg=_BG)
        footer.pack(side="bottom", fill="x", padx=p(28), pady=p(16))
        tkinter.Label(footer, text="更改将在保存后生效", bg=_BG, fg=_SUB,
                      font=(_FONT, -12)).pack(side="left")
        if self._on_debug:
            RoundedButton(footer, "运行输出", self._open_debug, width=88, height=40,
                          bg=_CARD, fg=_SUB, active="#304A70").pack(side="left", padx=(p(18), 0))
        self._save_btn = RoundedButton(footer, "保存并应用", self._save, width=124, height=44,
                                       bg=_ACCENT, fg="#FFFFFF", active="#70AEFF", bold=True)
        self._save_btn.pack(side="right")
        RoundedButton(footer, "取消", self._close, width=74, height=44,
                      bg=_BG, fg=_SUB, active=_CARD).pack(side="right", padx=(0, p(8)))

        viewport = tkinter.Frame(main, bg=_BG)
        viewport.pack(fill="both", expand=True, padx=(p(28), p(16)))
        self._scroll = tkinter.Canvas(viewport, bg=_BG, highlightthickness=0)
        bar = tkinter.Canvas(viewport, width=p(10), bg=_BG, highlightthickness=0)
        bar.pack(side="right", fill="y")
        self._scroll.pack(side="left", fill="both", expand=True)
        def scrollbar(first, last):
            bar.delete("all")
            if float(last) - float(first) < 0.999:
                h = bar.winfo_height()
                bar.create_line(p(5), max(p(4), float(first) * h), p(5), min(h - p(4), float(last) * h),
                                fill="#536987", width=p(4), capstyle="round")
        def scroll_to(ev):
            first, last = self._scroll.yview()
            self._scroll.yview_moveto(ev.y / max(1, bar.winfo_height()) - (last - first) / 2)
        bar.bind("<Button-1>", scroll_to)
        bar.bind("<B1-Motion>", scroll_to)
        bar.bind("<Configure>", lambda e: scrollbar(*self._scroll.yview()))
        self._scroll.configure(yscrollcommand=scrollbar)
        body = tkinter.Frame(self._scroll, bg=_BG)
        item = self._scroll.create_window(0, 0, window=body, anchor="nw")
        self._scroll.bind("<Configure>", lambda e: self._scroll.itemconfigure(item, width=e.width - p(4)))
        body.bind("<Configure>", lambda e: self._scroll.configure(scrollregion=self._scroll.bbox("all")))
        self.root.bind("<MouseWheel>", self._wheel)

        def card(key, title, subtitle):
            panel = Card(body)
            self._cards[key] = panel
            content = panel.content
            tkinter.Label(content, text=title, bg=_CARD, fg=_TEXT,
                          font=(_FONT, -15, "bold")).pack(anchor="w")
            if subtitle:
                tkinter.Label(content, text=subtitle, bg=_CARD, fg=_SUB,
                              font=(_FONT, -12)).pack(anchor="w", pady=(p(3), p(8)))
            return content

        c1 = card("hotkey", "快捷键", "按下快捷键，开始或停止语音输入")
        row = tkinter.Frame(c1, bg=_CARD)
        row.pack(fill="x", pady=(0, p(2)))
        self._hotkey_var = tkinter.StringVar(value=self._display_combo(self._cfg["hotkey"]))
        self._hotkey_entry = RoundedField(row, self._hotkey_var)
        self._hotkey_entry.pack(side="left", fill="x", expand=True)
        self._hotkey_btn = RoundedButton(row, "修改", self._start_capture,
                                         width=72, height=42, bg="#304766", active=_ACCENT)
        self._hotkey_btn.pack(side="left", padx=(p(10), 0))

        c2 = card("appearance", "悬浮窗设置", "调整大小与不透明度，在下方预览效果")
        self._scale_var = tkinter.DoubleVar(value=round(float(self._cfg.get("widget_scale", 1.0)) * 100))
        self._aspect_var = tkinter.DoubleVar(value=round(float(self._cfg.get("widget_aspect", 3.27)) * 100))
        self._opacity_var = tkinter.DoubleVar(value=round(float(self._cfg.get("widget_opacity", 0.92)) * 100))
        self._font_var = tkinter.DoubleVar(value=round(self._font_scale * 100))
        self._sliders = []
        self._percent_vars = []
        for label, var, low, high, suffix in (("窗口大小", self._scale_var, 50, 150, "%"),
                                      ("长宽比", self._aspect_var, 100, 500, ""),
                                      ("不透明度", self._opacity_var, 30, 100, "%"),
                                      ("界面字体", self._font_var, 85, 135, "%")):
            row = tkinter.Frame(c2, bg=_CARD)
            row.pack(fill="x", pady=p(2))
            tkinter.Label(row, text=label, bg=_CARD, fg=_TEXT, width=9, anchor="w",
                          font=(_FONT, -13)).pack(side="left")
            pct = tkinter.StringVar(value=(f"{var.get():.0f}%" if suffix else f"{var.get() / 100:.2f}"))
            self._percent_vars.append(pct)
            tkinter.Label(row, textvariable=pct, bg=_CARD, fg=_SUB, width=5, anchor="e",
                          font=(_FONT, -13)).pack(side="right")
            slider = Slider(row, var, minimum=low, maximum=high)
            slider.pack(side="left", fill="x", expand=True, padx=(p(6), p(14)))
            self._sliders.append(slider)
            var.trace_add("write", lambda *_, v=var, text=pct, unit=suffix: self._appearance_changed(v, text, unit))
        self._font_var.trace_add("write", lambda *_: self._set_font_scale(self._font_var.get() / 100))
        self._preview = tkinter.Canvas(c2, height=p(118), bg=_CARD, highlightthickness=0)
        self._preview.pack(fill="x", pady=(p(6), 0))
        self._preview.bind("<Configure>", lambda e: self._draw_preview())

        c3 = card("features", "功能设置", "")
        self._llm_path = load_config().llm_model_path
        proofread_ready = self._llm_path.is_file()
        self._proof_var = tkinter.BooleanVar(
            value=bool(self._cfg.get("proofread_enabled", True)) and proofread_ready
        )
        model_row = tkinter.Frame(c3, bg=_CARD)
        model_row.pack(fill="x", pady=(p(4), p(12)))
        self._model_status = tkinter.StringVar()
        tkinter.Label(model_row, textvariable=self._model_status, bg=_CARD, fg=_SUB,
                      font=(_FONT, -12), wraplength=p(440), justify="left").pack(side="left", fill="x", expand=True)
        self._download_button = RoundedButton(model_row, text="下载校对模型 · 1.1 GB",
                      command=self._download_model, bg=_TRACK, fg=_TEXT, width=210, height=38)
        self._download_button.pack(side="right")
        self._poll_model_download()
        mic_row = tkinter.Frame(c3, bg=_CARD)
        mic_row.pack(fill="x", pady=(p(4), p(8)))
        tkinter.Label(mic_row, text="输入设备", bg=_CARD, fg=_TEXT,
                      font=(_FONT, -14)).pack(anchor="w")
        tkinter.Label(
            mic_row,
            text="可指定真实麦克风；设备列表会在每次听写时重新解析，适配热插拔。",
            bg=_CARD, fg=_SUB, font=(_FONT, -12),
        ).pack(anchor="w", pady=(p(2), p(5)))
        from voice2text.capture import list_input_device_choices
        self._mic_selector_by_label = {"（系统默认）": ""}
        try:
            self._mic_selector_by_label.update(
                (label, selector) for label, selector in list_input_device_choices()
            )
        except Exception as exc:  # noqa: BLE001 —— 枚举失败时仍允许保存默认设备
            tkinter.Label(mic_row, text=f"无法读取设备列表：{exc}", bg=_CARD,
                          fg=_SUB, font=(_FONT, -11), wraplength=p(450),
                          justify="left").pack(anchor="w")
        saved_selector = str(self._cfg.get("input_device", "") or "")
        selected_label = next(
            (label for label, selector in self._mic_selector_by_label.items()
             if selector == saved_selector),
            "（系统默认）" if not saved_selector else f"不可用设备：{saved_selector}",
        )
        if saved_selector and selected_label not in self._mic_selector_by_label:
            self._mic_selector_by_label[selected_label] = saved_selector
        self._mic_var = tkinter.StringVar(value=selected_label)
        self._mic_menu = tkinter.OptionMenu(
            mic_row, self._mic_var, *self._mic_selector_by_label.keys()
        )
        self._mic_menu.config(bg=_TRACK, fg=_TEXT, activebackground="#304766",
                              activeforeground=_TEXT, relief="flat", bd=0,
                              highlightthickness=1, highlightbackground=_CARD_EDGE,
                              anchor="w", font=(_FONT, -12))
        self._mic_menu["menu"].config(bg=_CARD, fg=_TEXT, activebackground=_ACCENT,
                                      activeforeground="#FFFFFF", font=(_FONT, -12))
        self._mic_menu.pack(fill="x")
        self._sound_var = tkinter.BooleanVar(value=bool(self._cfg.get("sound_cue", True)))
        self._autostart_var = tkinter.BooleanVar(value=get_autostart())
        self._toggles = []
        for label, sub, var in (
            ("开启二次校对", "停止听写后，自动整理标点与语句", self._proof_var),
            ("录音提示音", "开始和停止录音时播放提示音", self._sound_var),
            ("开机自启动", "随系统启动，随时开始听写", self._autostart_var),
        ):
            row = tkinter.Frame(c3, bg=_CARD)
            row.pack(fill="x", pady=(p(7), p(1)))
            value_label = tkinter.Label(row, text="开" if var.get() else "关", bg=_CARD,
                                        fg=_SUB, width=2, font=(_FONT, -12))
            value_label.pack(side="right", padx=(p(8), 0))
            if label == "开启二次校对":
                command = lambda text=value_label: self._proofread_toggle_changed(text)
            else:
                command = lambda v=var, text=value_label: text.config(text="开" if v.get() else "关")
            toggle = Toggle(row, var, command=command)
            if label == "开启二次校对":
                self._proof_toggle = toggle
            toggle.pack(side="right", padx=(p(16), 0))
            self._toggles.append(toggle)
            box = tkinter.Frame(row, bg=_CARD)
            box.pack(side="left", fill="x", expand=True)
            tkinter.Label(box, text=label, bg=_CARD, fg=_TEXT, font=(_FONT, -14)).pack(anchor="w")
            tkinter.Label(box, text=sub, bg=_CARD, fg=_SUB, font=(_FONT, -12)).pack(anchor="w", pady=(p(2), 0))

        update_row = tkinter.Frame(c3, bg=_CARD)
        update_row.pack(fill="x", pady=(p(18), p(2)))
        update_box = tkinter.Frame(update_row, bg=_CARD)
        update_box.pack(side="left", fill="x", expand=True)
        tkinter.Label(update_box, text=f"软件更新 · 当前 v{__version__}", bg=_CARD, fg=_TEXT,
                      font=(_FONT, -14)).pack(anchor="w")
        self._update_status = tkinter.StringVar(value="可手动检查 GitHub 正式版本")
        tkinter.Label(update_box, textvariable=self._update_status, bg=_CARD, fg=_SUB,
                      font=(_FONT, -12), wraplength=p(390), justify="left").pack(anchor="w", pady=(p(2), 0))
        self._update_button = RoundedButton(
            update_row, "检查更新", self._update_clicked,
            bg=_TRACK, fg=_TEXT, width=150, height=38,
        )
        self._update_button.pack(side="right", padx=(p(12), 0))
        self._poll_update()
        self._record_font_widgets()
        self._set_font_scale(self._font_scale)
        self._select_page("all")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Destroy>", self._cancel_polls, add="+")
        self.root.bind("<Escape>", lambda e: self._finish_capture(None) if self._capturing else self._close())
        self.root.deiconify()
        self.root.lift()

    def _download_model(self) -> None:
        if not self._llm_path.is_file():
            model_download.start(self._llm_path)

    def _proofread_toggle_changed(self, value_label) -> None:
        """没有本地 GGUF 时拒绝开启，并把原因直接反馈到设置页。"""
        if self._proof_var.get() and not self._llm_path.is_file():
            self._proof_var.set(False)
            self._proof_toggle._draw()
            value_label.config(text="关")
            messagebox.showwarning(
                "需要校对模型",
                "请先下载校对模型，下载完成后才能开启二次校对。",
                parent=self.root,
            )
            return
        value_label.config(text="开" if self._proof_var.get() else "关")

    def _poll_model_download(self) -> None:
        if not self.root.winfo_exists():
            return
        active, message = model_download.snapshot()
        ready = self._llm_path.is_file()
        self._model_status.set(message or ("校对模型已安装" if ready else "可选：未安装校对模型，语音与标点仍可正常使用"))
        self._download_button.set_style(text="下载中…" if active else "已安装" if ready else "下载校对模型 · 1.1 GB",
                                        fg=_SUB if active or ready else _TEXT)
        self._model_poll = self.root.after(500, self._poll_model_download)

    def _update_clicked(self) -> None:
        snapshot = update_manager.snapshot()
        if snapshot.state == "ready" and snapshot.archive is not None:
            if self._on_update is None:
                return
            if messagebox.askyesno(
                "安装更新",
                f"v{snapshot.version} 已下载并验证。\n\n现在退出程序、安装更新并自动重启吗？",
                parent=self.root,
            ):
                self._on_update(snapshot.archive, snapshot.version)
                self.root.destroy()
            return
        update_manager.start()

    def _poll_update(self) -> None:
        if not self.root.winfo_exists():
            return
        snapshot = update_manager.snapshot()
        if not update_manager.supported:
            text, fg = "仅安装版支持", _SUB
            message = "源码开发环境不执行自更新；分发版可在此一键更新"
        else:
            labels = {
                "idle": "检查更新", "checking": "检查中…", "downloading": "下载中…",
                "ready": "安装并重启", "current": "重新检查", "error": "重试",
            }
            text = labels.get(snapshot.state, "检查更新")
            fg = _SUB if snapshot.state in {"checking", "downloading"} else _TEXT
            message = snapshot.message or "可手动检查 GitHub 正式版本"
        self._update_status.set(message)
        self._update_button.set_style(text=text, fg=fg)
        self._update_poll = self.root.after(500, self._poll_update)

    def _cancel_polls(self, event) -> None:
        if event.widget is self.root:
            for name in ("_model_poll", "_update_poll"):
                try:
                    self.root.after_cancel(getattr(self, name))
                except (AttributeError, tkinter.TclError):
                    pass

    def _apply_window_rounding(self) -> None:
        """用透明色角罩裁掉无边框设置窗的四个方形外角。"""
        if not self.root.winfo_exists():
            return
        try:
            self.root.attributes("-transparentcolor", _WINDOW_KEY)
        except tkinter.TclError:
            return
        r = self._px(_WINDOW_RADIUS)
        specs = (
            (0.0, 0.0, "nw", (0, 0, r * 2, r * 2), _SIDE),
            (1.0, 0.0, "ne", (-r, 0, r, r * 2), _BG),
            (0.0, 1.0, "sw", (0, -r, r * 2, r), _SIDE),
            (1.0, 1.0, "se", (-r, -r, r, r), _BG),
        )
        self._corner_masks = []
        for relx, rely, anchor, oval, fill in specs:
            corner = tkinter.Canvas(
                self.root, width=r, height=r, bg=_WINDOW_KEY,
                highlightthickness=0, borderwidth=0,
            )
            corner.create_oval(*oval, fill=fill, outline=_CARD_EDGE, width=1)
            corner.place(relx=relx, rely=rely, anchor=anchor)
            self._corner_masks.append(corner)

    def _select_page(self, key: str) -> None:
        titles = {"all": ("常规", "自定义语音输入的使用体验"),
                  "hotkey": ("快捷键", "用顺手的组合键，随时开始听写"),
                  "appearance": ("外观", "让悬浮窗适合你的桌面"),
                  "features": ("识别与校对", "设置听写后的处理方式与启动偏好")}
        self._heading.config(text=titles[key][0])
        self._subtitle.config(text=titles[key][1])
        for name, button in self._nav.items():
            button.set_style(bg="#304A70" if name == key else _SIDE,
                             fg=_TEXT if name == key else _SUB)
        for name, panel in self._cards.items():
            panel.pack_forget()
            if key == "all" or name == key:
                panel.pack(fill="x", pady=(0, self._px(10)))
        self.root.update_idletasks()
        self._scroll.configure(scrollregion=self._scroll.bbox("all"))
        self._scroll.yview_moveto(0)

    def _wheel(self, ev) -> None:
        bounds = self._scroll.bbox("all")
        if bounds and bounds[3] > self._scroll.winfo_height():
            self._scroll.yview_scroll(-int(ev.delta / 120), "units")

    def _appearance_changed(self, var, text, suffix="%") -> None:
        text.set(f"{var.get():.0f}%" if suffix else f"{var.get() / 100:.2f}")
        self._draw_preview()

    def _record_font_widgets(self) -> None:
        """记录当前控件字号，便于字体滑条即时缩放整个设置页。"""
        self._font_widgets.clear()
        def visit(widget):
            try:
                spec = widget.cget("font")
                if spec:
                    f = tkfont.Font(font=spec)
                    size = abs(int(f.cget("size")))
                    if size:
                        self._font_widgets.append((widget, f.cget("family"), size,
                                                   f.cget("weight"), f.cget("slant"),
                                                   f.cget("underline"), f.cget("overstrike")))
            except (tkinter.TclError, TypeError):
                pass
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)

    def _set_font_scale(self, value: float) -> None:
        self._font_scale = max(0.85, min(1.35, float(value)))
        self.root._v2t_font_scale = self._font_scale
        for widget, family, base, weight, slant, underline, overstrike in self._font_widgets:
            try:
                widget.configure(font=(family, -max(self._px(8), self._px(base * self._font_scale)), weight,
                                       slant, underline, overstrike))
            except tkinter.TclError:
                pass
        def redraw_buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, RoundedButton):
                    child._draw()
                redraw_buttons(child)
        redraw_buttons(self.root)

    def _open_debug(self) -> None:
        if self._on_debug:
            # 让新开的运行输出窗口可见；设置页仍保留在后台，关闭输出后可继续编辑。
            self.root.attributes("-topmost", False)
            self.root.lower()
            self._on_debug()

    def _draw_preview(self) -> None:
        if not hasattr(self, "_preview"):
            return
        canvas = self._preview
        canvas.delete("all")
        w = max(1, canvas.winfo_width())
        if self._preview_source is not None:
            # 与实际悬浮窗共用同一帧；先按目标比例居中裁切，避免把内容横向压扁。
            source = self._preview_source
            height = max(1, self._px(104 * self._scale_var.get() / 100 * 0.6))
            aspect = self._aspect_var.get() / 100
            width = max(1, round(height * aspect))
            source_aspect = source.width / source.height
            if aspect < source_aspect:
                crop_w = max(1, round(source.height * aspect))
                left = (source.width - crop_w) // 2
                source = source.crop((left, 0, left + crop_w, source.height))
            elif aspect > source_aspect:
                crop_h = max(1, round(source.width / aspect))
                top = (source.height - crop_h) // 2
                source = source.crop((0, top, source.width, top + crop_h))
            image = source.resize((width, height), Image.Resampling.LANCZOS)
            image.putalpha(image.getchannel("A").point(lambda a: round(a * self._opacity_var.get() / 100)))
            self._preview_photo = ImageTk.PhotoImage(image)
            canvas.create_image(w // 2, 50, image=self._preview_photo)
            caption = "外观预览（缩略）"
        else:
            caption = "保存后应用到悬浮窗"
        canvas.create_text(w // 2, 107, text=caption, fill=_SUB, font=(_FONT, -11))

    def _close(self) -> None:
        if self._capturing:
            self._finish_capture(None)
        self.root.destroy()

    def _tb_press(self, ev) -> None:
        self._tb_off = (ev.x, ev.y)

    def _tb_motion(self, ev) -> None:
        if self._tb_off is None:
            return
        self.root.geometry(f"+{self.root.winfo_x() + ev.x - self._tb_off[0]}"
                           f"+{self.root.winfo_y() + ev.y - self._tb_off[1]}")

    @staticmethod
    def _display_combo(combo: str) -> str:
        return " + ".join(p.capitalize() for p in combo.split("+"))

    # ---- 快捷键捕获 ----

    def _start_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self._hotkey_btn.set_style(text="按组合键…", bg=_ACCENT)
        self._hotkey_entry.set_foreground(_ACCENT)
        self._hotkey_var.set("")
        modifiers: set[str] = set()

        def capture_press(ev):
            if not self._capturing:
                return "break"
            try:
                if ev.keysym == "Escape":  # Esc 取消
                    self._finish_capture(None)
                    return "break"
                modifier = _MODIFIER_KEYSYMS.get(ev.keysym.lower())
                if modifier:
                    modifiers.add(modifier)
                    return "break"
                combo = _normalize_combo(ev.keysym, modifiers)
                if combo:
                    self._finish_capture(combo)
                return "break"
            except tkinter.TclError:
                return "break"  # 窗口已销毁（捕获中关窗），静默退出捕获态

        def capture_release(ev):
            modifier = _MODIFIER_KEYSYMS.get(ev.keysym.lower())
            if modifier:
                modifiers.discard(modifier)
            return "break"

        self._capture_bindings = (
            ("<KeyPress>", self.root.bind("<KeyPress>", capture_press, add="+")),
            ("<KeyRelease>", self.root.bind("<KeyRelease>", capture_release, add="+")),
        )
        self._hotkey_btn.focus_set()

    def _finish_capture(self, combo: str | None) -> None:
        self._capturing = False
        for sequence, binding in getattr(self, "_capture_bindings", ()):
            if binding:
                self.root.unbind(sequence, binding)
        self._capture_bindings = ()
        self._hotkey_btn.set_style(text="修改", bg="#304766")
        self._hotkey_entry.set_foreground(_TEXT)
        if combo:
            self._cfg["hotkey"] = combo
            self._hotkey_var.set(self._display_combo(combo))
        else:
            self._hotkey_var.set(self._display_combo(self._cfg["hotkey"]))

    # ---- 保存 ----

    def _save(self) -> None:
        self._finish_capture(None)  # 若在捕获态保存/关窗，先干净退出捕获
        self._cfg["widget_scale"] = round(self._scale_var.get() / 100, 2)
        self._cfg["widget_aspect"] = round(self._aspect_var.get() / 100, 2)
        self._cfg["widget_opacity"] = round(self._opacity_var.get() / 100, 2)
        self._cfg["font_scale"] = round(self._font_var.get() / 100, 2)
        self._cfg["proofread_enabled"] = bool(self._proof_var.get()) and self._llm_path.is_file()
        self._cfg["input_device"] = self._mic_selector_by_label.get(
            self._mic_var.get(), ""
        )
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

    def sync_appearance(self, scale: float, aspect: float) -> None:
        """悬浮窗拖拽尺寸后，同步仍打开的设置页面和预览。"""
        self._scale_var.set(round(scale * 100))
        self._aspect_var.set(round(aspect * 100))

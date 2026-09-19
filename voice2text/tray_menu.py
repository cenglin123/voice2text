"""参考 assets/托盘菜单.jpg 的深蓝圆角自绘菜单。"""
from __future__ import annotations

import ctypes
import math
import tkinter
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from voice2text import layered

SS = 3
WIDTH = 308
PAD = 8
TOP_H = 58
ROW_H = 42
PANEL = (22, 31, 45, 248)
TOP = (35, 46, 64, 255)
HOVER = (43, 57, 78, 255)
EDGE = (79, 93, 112, 220)
TEXT = (241, 245, 251, 255)
SUB = (174, 184, 200, 255)
ACCENT = (82, 166, 255, 255)

_user = ctypes.WinDLL("user32", use_last_error=True)
_user.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user.GetAsyncKeyState.restype = ctypes.c_short
_user.WindowFromPoint.argtypes = [wintypes.POINT]
_user.WindowFromPoint.restype = wintypes.HWND
_user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user.GetAncestor.restype = wintypes.HWND
_user.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user.MonitorFromPoint.restype = wintypes.HANDLE


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


_user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
_user.GetMonitorInfoW.restype = wintypes.BOOL


def _font(size: int):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
    except OSError:
        return ImageFont.load_default()


def _hotkey_text(draw, combo: str, max_width: int):
    """在固定右栏内完整显示快捷键；长组合改用紧凑拼写并逐级缩小。"""
    aliases = {
        "ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
        "page_down": "PgDn", "page_up": "PgUp", "print_screen": "PrtSc",
        "backspace": "Bksp", "space": "Space", "escape": "Esc",
        "media_volume_up": "Vol+", "media_volume_down": "Vol-",
    }
    parts = [aliases.get(part.lower(), part.replace("_", " ").title())
             for part in combo.split("+")]
    candidates = [" + ".join(parts), "+".join(parts)]
    if len(parts) > 2:
        candidates.append(f"{parts[0]}+…+{parts[-1]}")
    for candidate in candidates:
        for size in (12, 11, 10):
            font = _font(size * SS)
            if draw.textlength(candidate, font=font) <= max_width:
                return candidate, font
    return candidates[-1], _font(10 * SS)


class TrayMenu:
    """不抢焦点的分层窗口，适合听写期间直接点“停止”。"""

    def __init__(self, master, app, command) -> None:
        self.app = app
        self.command = command
        self.rows = [
            ("widget", lambda: "隐藏悬浮窗" if app.widget_visible else "显示悬浮窗", "toggle_widget"),
            ("gear", lambda: "设置", "settings"),
            ("book", lambda: "使用帮助", "help"),
            ("terminal", lambda: "运行输出", "debug"),
            ("exit", lambda: "退出", "quit"),
        ]
        self.height = PAD * 2 + TOP_H + ROW_H * len(self.rows) + 8
        self.root = tkinter.Toplevel(master)
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{WIDTH}x{self.height}")
        self.canvas = tkinter.Canvas(self.root, width=WIDTH, height=self.height,
                                     bg="#10161F", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.hwnd = layered.window_handle(self.root.winfo_id())
        layered.enable(self.hwnd)
        layered.no_activate(self.hwnd)
        self.hover = -1
        self.visible = False
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(-1))
        self.canvas.bind("<ButtonRelease-1>", self._click)
        self.canvas.bind("<ButtonRelease-3>", lambda e: self.hide())
        self._render()
        self._poll()

    def show(self, x: int, y: int) -> None:
        info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
        monitor = _user.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
        if monitor and _user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            left, top, right, bottom = info.work.left, info.work.top, info.work.right, info.work.bottom
        else:
            left, top = 0, 0
            right, bottom = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.x = max(left + 8, min(x - WIDTH, right - WIDTH - 8))
        self.y = max(top + 8, min(y - self.height - 8, bottom - self.height - 8))
        self.root.geometry(f"{WIDTH}x{self.height}+{self.x}+{self.y}")
        _user.GetAsyncKeyState(0x01)  # 清除上一次点击的低位状态，避免重开后立即收起
        self.root.deiconify()
        self.visible = True
        self.hover = -1
        self._render()

    def hide(self) -> None:
        if self.visible:
            self.visible = False
            self.root.withdraw()

    def _motion(self, ev) -> None:
        index = self._row_at(ev.y)
        self._set_hover(index)

    def _set_hover(self, index: int) -> None:
        if index != self.hover:
            self.hover = index
            self._render()

    def _row_at(self, y: int) -> int:
        if PAD <= y < PAD + TOP_H:
            return 0
        start = PAD + TOP_H
        if start <= y < start + ROW_H * len(self.rows):
            return 1 + (y - start) // ROW_H
        return -1

    def _click(self, ev) -> None:
        index = self._row_at(ev.y)
        if index < 0:
            return
        self.hide()
        if index == 0:
            self.command("toggle")
        else:
            self.command(self.rows[index - 1][2])

    def _poll(self) -> None:
        if self.visible and _user.GetAsyncKeyState(0x01) & 0x8001:
            point = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            if _user.GetAncestor(_user.WindowFromPoint(point), 2) != self.hwnd:
                self.hide()
        self.root.after(50, self._poll)

    def _render(self) -> None:
        W, H = WIDTH * SS, self.height * SS
        image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        box = [PAD * SS, PAD * SS, (WIDTH - PAD) * SS - 1, (self.height - PAD) * SS - 1]
        sd.rounded_rectangle([v + 3 * SS for v in box], radius=16 * SS, fill=(0, 0, 0, 125))
        shadow = shadow.filter(ImageFilter.GaussianBlur(6 * SS))
        image.alpha_composite(shadow)
        d = ImageDraw.Draw(image)
        d.rounded_rectangle(box, radius=16 * SS, fill=PANEL, outline=EDGE, width=SS)

        left, right = 18 * SS, (WIDTH - 18) * SS
        top_box = [left, 14 * SS, right, (PAD + TOP_H - 5) * SS]
        d.rounded_rectangle(top_box, radius=10 * SS,
                            fill=HOVER if self.hover == 0 else TOP)
        top_y = (PAD + TOP_H // 2) * SS
        self._icon(d, "mic", 41 * SS, top_y, ACCENT)
        label = "停止听写" if self.app.active else "开始听写"
        d.text((70 * SS, top_y), label, anchor="lm", font=_font(16 * SS), fill=TEXT)
        hotkey_right = (WIDTH - 22) * SS
        hotkey_max = (WIDTH - 172) * SS
        hotkey, hotkey_font = _hotkey_text(d, self.app.hotkey.combo, hotkey_max)
        self._hotkey_display = hotkey
        self._hotkey_width = d.textlength(hotkey, font=hotkey_font)
        d.text((hotkey_right, top_y), hotkey, anchor="rm", font=hotkey_font, fill=SUB)

        start = PAD + TOP_H
        for i, (kind, label_fn, _) in enumerate(self.rows):
            y0 = (start + i * ROW_H) * SS
            if self.hover == i + 1:
                d.rounded_rectangle([left, y0 + 3 * SS, right, y0 + (ROW_H - 3) * SS],
                                    radius=9 * SS, fill=HOVER)
            cy = y0 + ROW_H * SS // 2
            self._icon(d, kind, 41 * SS, cy, SUB)
            d.text((70 * SS, cy), label_fn(), anchor="lm", font=_font(14 * SS), fill=TEXT)
            if kind in {"gear", "book", "terminal"}:
                self._chevron(d, (WIDTH - 27) * SS, cy, SUB)
            if i in (1, 3):
                line_y = y0 + ROW_H * SS
                d.line([26 * SS, line_y, (WIDTH - 26) * SS, line_y], fill=(61, 73, 91, 180), width=SS)

        small = image.resize((WIDTH, self.height), Image.Resampling.LANCZOS)
        self._last_image = small
        if self.visible:
            layered.update(self.hwnd, small, self.x, self.y)

    @staticmethod
    def _chevron(d, x, y, color):
        s = 5 * SS
        d.line([x - s, y - s, x, y, x - s, y + s], fill=color, width=2 * SS, joint="curve")

    @staticmethod
    def _icon(d, kind, x, y, color):
        s = SS
        if kind == "mic":
            d.rounded_rectangle([x - 6*s, y - 13*s, x + 6*s, y + 7*s], radius=6*s, outline=color, width=2*s)
            d.arc([x - 10*s, y - 6*s, x + 10*s, y + 13*s], 0, 180, fill=color, width=2*s)
            d.line([x, y + 13*s, x, y + 18*s], fill=color, width=2*s)
        elif kind == "gear":
            points = []
            for i in range(36):
                a = math.tau * i / 36
                r = (13 if i % 6 in (1, 2, 3, 4) else 10) * s
                points.append((x + math.cos(a) * r, y + math.sin(a) * r))
            d.line(points + [points[0]], fill=color, width=2*s, joint="curve")
            d.ellipse([x - 4*s, y - 4*s, x + 4*s, y + 4*s], outline=color, width=2*s)
        elif kind == "book":
            left = [(x, y - 9*s), (x - 5*s, y - 12*s), (x - 13*s, y - 10*s),
                    (x - 13*s, y + 10*s), (x - 5*s, y + 8*s), (x, y + 11*s)]
            right = [(x, y - 9*s), (x + 5*s, y - 12*s), (x + 13*s, y - 10*s),
                     (x + 13*s, y + 10*s), (x + 5*s, y + 8*s), (x, y + 11*s)]
            d.line(left, fill=color, width=2*s, joint="curve")
            d.line(right, fill=color, width=2*s, joint="curve")
        elif kind == "terminal":
            d.rounded_rectangle([x - 14*s, y - 10*s, x + 14*s, y + 10*s], radius=3*s, outline=color, width=2*s)
            d.line([x - 9*s, y - 4*s, x - 4*s, y, x - 9*s, y + 4*s], fill=color, width=2*s)
            d.line([x, y + 5*s, x + 8*s, y + 5*s], fill=color, width=2*s)
        elif kind == "widget":
            d.rounded_rectangle([x - 14*s, y - 9*s, x + 14*s, y + 9*s], radius=5*s, outline=color, width=2*s)
            d.line([x - 6*s, y, x + 6*s, y], fill=color, width=2*s)
        else:
            d.rounded_rectangle([x - 13*s, y - 13*s, x + 6*s, y + 13*s], radius=3*s, outline=color, width=2*s)
            d.line([x - 2*s, y, x + 14*s, y], fill=color, width=2*s)
            d.line([x + 8*s, y - 6*s, x + 14*s, y, x + 8*s, y + 6*s], fill=color, width=2*s)

"""悬浮窗：置顶、可拖动的药丸形状态窗（tkinter，美术稿 assets/悬浮窗-*.jpg）。

布局：左侧 品牌格点+「语音输入」；中央 麦克风圆环（点击=开始/停止）+状态文字；
右侧 设置齿轮 | 分隔线 | 关闭。听写中圆环与声波变红并跳动。

线程约定：所有公开方法必须在 tkinter 主线程调用；工作线程通过 ui_queue 传
("state", 状态) 消息，由 pump() 轮询应用。
"""

from __future__ import annotations

import queue
import tkinter

BG = "#1B2433"
EDGE = "#43536B"
KEY_COLOR = "#010203"  # transparentcolor 魔法色
TEXT_PRIMARY = "#E8EDF4"
TEXT_SECONDARY = "#97A3B4"
IDLE_COLOR = "#C9D2DD"
LISTEN_COLOR = "#FA5A52"
PROOF_COLOR = "#4C9DF8"
ERROR_COLOR = "#8A94A2"

BASE_W, BASE_H = 340, 96

STATUS_TEXT = {
    "idle": "待命中...",
    "listening": "正在聆听...",
    "proofreading": "校对中...",
    "error": "不可用",
}


def _rounded(canvas: tkinter.Canvas, x0, y0, x1, y1, r, **kw) -> None:
    """圆角矩形（多段路径）。"""
    pts = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
        x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    canvas.create_polygon(pts, smooth=True, **kw)


class DictationWidget:
    """悬浮窗。on_toggle/on_settings/on_hide/on_quit 为 UI 回调（主线程）。"""

    def __init__(
        self,
        scale: float = 1.0,
        opacity: float = 0.92,
        on_toggle=None,
        on_settings=None,
        on_hide=None,
        on_quit=None,
    ) -> None:
        self._scale = scale
        self._opacity = opacity
        self._on_toggle = on_toggle
        self._on_settings = on_settings
        self._on_hide = on_hide
        self._on_quit = on_quit
        self._state = "idle"
        try:  # 高 DPI 模糊缓解——必须早于首个窗口创建（进程级设置）
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass

        self.root = tkinter.Tk()
        self.root.withdraw()
        self.root.title("voice2text")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", opacity)
        self.root.attributes("-transparentcolor", KEY_COLOR)
        w, h = int(BASE_W * scale), int(BASE_H * scale)
        self.root.geometry(f"{w}x{h}+60+60")

        self.canvas = tkinter.Canvas(self.root, width=w, height=h, bg=KEY_COLOR, highlightthickness=0)
        self.canvas.pack()
        self._state = "idle"
        self._wave_phase = 0.0
        self._anim_job = None
        self._drag_off = None
        self._drag_moved = False

        self._draw()
        self._bind()
        self.root.deiconify()
        self._animate()

    @property
    def state(self) -> str:
        return self._state

    # ---- 绘制 ----

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        s = self._scale
        w, h = int(BASE_W * s), int(BASE_H * s)
        accent = {
            "idle": IDLE_COLOR,
            "listening": LISTEN_COLOR,
            "proofreading": PROOF_COLOR,
            "error": ERROR_COLOR,
        }[self._state]

        _rounded(c, 1, 1, w - 2, h - 2, h // 2 - 1, fill=BG, outline=EDGE, width=1)

        # 左上：品牌格点 + 标题
        gx, gy, gs = int(20 * s), int(18 * s), max(3, int(4 * s))
        gap = gs + max(2, int(3 * s))
        for dx in (0, 1):
            for dy in (0, 1):
                c.create_rectangle(
                    gx + dx * gap, gy + dy * gap, gx + dx * gap + gs, gy + dy * gap + gs,
                    fill=TEXT_SECONDARY, outline="",
                )
        c.create_text(
            gx + gap * 2 - gs + int(8 * s), gy + gs,
            text="语音输入", anchor="w", fill=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", max(8, int(10 * s))),
        )

        # 右上：齿轮 | 分隔 | 关闭
        self._tags = {}
        cx, cy = w - int(64 * s), int(24 * s)
        self._draw_gear(cx, cy, int(9 * s), TEXT_SECONDARY, tag="gear")
        c.create_line(w - int(48 * s), int(18 * s), w - int(48 * s), h - int(18 * s), fill=EDGE)
        self._draw_cross(w - int(26 * s), int(24 * s), int(8 * s), TEXT_SECONDARY, tag="close")

        # 中央：麦克风圆环 + 麦克风
        mr, mcx, mcy = int(30 * s), w // 2, int(38 * s)
        ring_w = 2 if self._state == "idle" else 3
        c.create_oval(mcx - mr, mcy - mr, mcx + mr, mcy + mr, outline=accent, width=ring_w)
        self._draw_mic(mcx, mcy, s, accent)

        # 声波（聆听态）
        if self._state == "listening":
            heights = self._wave_heights()
            for i, hh in enumerate(heights):
                x = mcx - mr - int(14 * s) - i * int(7 * s)
                c.create_line(x, mcy - hh, x, mcy + hh, fill=LISTEN_COLOR, width=max(2, int(2.5 * s)))
            for i, hh in enumerate(heights):
                x = mcx + mr + int(14 * s) + i * int(7 * s)
                c.create_line(x, mcy - hh, x, mcy + hh, fill=LISTEN_COLOR, width=max(2, int(2.5 * s)))

        # 状态文字
        c.create_text(
            mcx, h - int(16 * s), text=STATUS_TEXT.get(self._state, ""), fill=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", max(8, int(10 * s))),
        )

    def _draw_mic(self, cx: int, cy: int, s: float, color: str) -> None:
        c = self.canvas
        mw, mh = int(11 * s), int(14 * s)
        c.create_rectangle(cx - mw, cy - int(16 * s), cx + mw, cy - int(16 * s) + 2 * mh, fill=color, outline="")
        c.create_arc(cx - int(16 * s), cy - int(12 * s), cx + int(16 * s), cy + int(14 * s),
                     start=20, extent=140, style="arc", outline=color, width=max(2, int(3 * s)))
        c.create_line(cx, cy + int(14 * s), cx, cy + int(19 * s), fill=color, width=max(2, int(3 * s)))
        c.create_line(cx - int(7 * s), cy + int(19 * s), cx + int(7 * s), cy + int(19 * s),
                      fill=color, width=max(2, int(3 * s)))

    def _draw_gear(self, cx: int, cy: int, r: int, color: str, tag: str) -> None:
        c = self.canvas
        c.create_oval(cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2, outline=color, width=2, tags=tag)
        import math

        for k in range(8):
            a = math.pi * k / 4
            c.create_line(
                cx + int((r - 2) * math.cos(a)), cy + int((r - 2) * math.sin(a)),
                cx + int(r * math.cos(a)), cy + int(r * math.sin(a)),
                fill=color, width=2, tags=tag,
            )

    def _draw_cross(self, cx: int, cy: int, r: int, color: str, tag: str) -> None:
        c = self.canvas
        c.create_line(cx - r, cy - r, cx + r, cy + r, fill=color, width=2, tags=tag)
        c.create_line(cx - r, cy + r, cx + r, cy - r, fill=color, width=2, tags=tag)

    def _wave_heights(self) -> list[int]:
        import math

        s = self._scale
        base = int(6 * s)
        heights = []
        for i in range(5):
            v = math.sin(self._wave_phase + i * 0.9) * 0.5 + 0.5
            heights.append(int((base + v * int(12 * s)) / 2))
        return heights

    def _animate(self) -> None:
        if not self.root.winfo_exists():
            return
        if self._state == "listening":
            self._wave_phase += 0.55
            self._draw()
        elif self._state == "proofreading":
            self._wave_phase += 0.25
        self._anim_job = self.root.after(80, self._animate)

    # ---- 交互 ----

    def _bind(self) -> None:
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, ev) -> None:
        self._drag_off = (ev.x, ev.y)
        self._drag_moved = False

    def _on_motion(self, ev) -> None:
        if self._drag_off is None:
            return
        dx, dy = ev.x - self._drag_off[0], ev.y - self._drag_off[1]
        if not self._drag_moved and abs(dx) + abs(dy) > 4:
            self._drag_moved = True  # 超过阈值才算拖动，此前不挪窗（防 1-3px 抖动）
        if self._drag_moved:
            self.root.geometry(f"+{self.root.winfo_x() + dx}+{self.root.winfo_y() + dy}")

    def _on_release(self, ev) -> None:
        if not self._drag_moved and self._drag_off is not None:
            tags = self.canvas.find_withtag("current")
            cur = self.canvas.gettags(tags[0]) if tags else ()
            if "gear" in cur and self._on_settings:
                self._on_settings()
            elif "close" in cur and self._on_hide:
                self._on_hide()
            elif self._on_toggle:  # 麦克风/其他区域 = 切换听写
                self._on_toggle()
        self._drag_off = None

    # ---- 状态与队列（工作线程 → 主线程）----

    def set_state(self, state: str) -> None:
        """主线程调用：切换状态并重绘。"""
        if state != self._state:
            self._state = state
            self._draw()

    def pump(self, ui_queue: "queue.Queue[tuple]") -> None:
        """主线程轮询：应用工作线程投递的状态消息。"""
        while True:
            try:
                kind, value = ui_queue.get_nowait()
            except queue.Empty:
                return
            if kind == "state":
                self.set_state(value)

    def show(self) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def hide(self) -> None:
        self.root.withdraw()

    def apply_appearance(self, scale: float, opacity: float) -> None:
        """主线程调用：调整大小与透明度并重绘。"""
        self._scale = scale
        self._opacity = opacity
        self.root.attributes("-alpha", opacity)
        w, h = int(BASE_W * scale), int(BASE_H * scale)
        self.canvas.config(width=w, height=h)
        self.root.geometry(f"{w}x{h}")
        self._draw()

    def run_tick(self, tick, interval_ms: int = 150) -> None:
        """驱动主循环：tick() 由调用方提供（热键/托盘命令/看门狗）。"""
        def _loop():
            try:
                tick()
            except SystemExit:
                self.root.destroy()
                return
            except Exception:  # noqa: BLE001 —— 单次轮询异常不终结 UI
                pass
            self.root.after(interval_ms, _loop)

        _loop()
        self.root.mainloop()

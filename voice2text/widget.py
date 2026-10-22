"""悬浮窗：置顶、可拖动的圆角磨砂状态窗（美术稿 assets/悬浮窗-*.jpg）。

渲染：整面板用 Pillow 以 3x 超采样绘制再缩小（抗锯齿），tkinter 只负责贴图与
事件；系统合成器实时模糊背后内容，失败回退深蓝渐变。声波按 ~90ms 重绘。

状态：idle 待命 / loading 准备 / listening 聆听 / proofreading 校对 / error 短暂不可用提示。
线程约定：公开方法须在主线程调用；工作线程经 ui_queue 传 ("state", s) 由 pump 应用。
"""

from __future__ import annotations

import ctypes
import queue
import tkinter

from PIL import Image, ImageTk

from voice2text import layered
from voice2text.dpi import enable_dpi_awareness, window_scale, window_workarea

KEY_COLOR = "#10161F"  # transparentcolor 魔法色——取接近药丸底色的深藏青，边缘混合不显黑边
ERROR_RESET_MS = 2000
NOTICE_DURATION_MS = 7500
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNOACTIVATE = 4

from voice2text.widget_render import (
    BASE_W, BASE_H, MIN_ASPECT, MAX_ASPECT, CORNER_RADIUS, WidgetRenderer,
)


class DictationWidget:
    """悬浮窗。on_toggle/on_settings/on_hide/on_quit 为 UI 回调（主线程）。"""

    def __init__(
        self,
        scale: float = 1.0,
        aspect: float = BASE_W / BASE_H,
        opacity: float = 0.92,
        on_toggle=None,
        on_settings=None,
        on_hide=None,
        on_quit=None,
        on_resize=None,
    ) -> None:
        enable_dpi_awareness()
        self._dpi_scale = 1.0
        self._scale = scale
        self._aspect = max(MIN_ASPECT, min(MAX_ASPECT, aspect))
        self._opacity = opacity
        self._on_toggle = on_toggle
        self._on_settings = on_settings
        self._on_hide = on_hide
        self._on_quit = on_quit
        self._on_resize = on_resize
        self._state = "idle"
        self._error_reset_job = None
        self._notice_window = None
        self._notice_text = None
        self._notice_title = None
        self._notice_footer = None
        self._notice_job = None
        self._phase = 0.0
        self.root = tkinter.Tk()
        self.root.withdraw()
        self.root.title("voice2text")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry("+60+60")
        self.root.update_idletasks()
        self._dpi_scale = window_scale(self.root)
        self._scale = scale * self._dpi_scale
        self._h = round(BASE_H * self._scale)
        self._w = round(self._h * self._aspect)
        self.root.geometry(f"{self._w}x{self._h}+60+60")
        self._opacity_pct = int(round(opacity * 255))
        # 分层窗口（逐像素 alpha，边缘真平滑）；失败回退 transparentcolor + 整窗 alpha
        self._layered = False
        self._glass = False
        self._backdrop = None
        self._fallback_applied = False

        self.canvas = tkinter.Canvas(self.root, width=self._w, height=self._h, bg="#10161F", highlightthickness=0)
        self.canvas.pack()
        self._photo = None
        self._hits: dict[str, tuple[int, int, int]] = {}  # kind -> (cx, cy, r)
        self._render()
        self._bind()
        self.root.deiconify()
        self._init_layered()
        self.root.bind("<Configure>", self._on_configure)
        self.root.bind("<Destroy>", self._on_root_destroy, add="+")
        self._animate()

    @property
    def state(self) -> str:
        return self._state

    def snapshot(self) -> Image.Image:
        """返回未施加整体透明度的当前画面，供设置页预览。"""
        return self._last_pil.copy()

    # ---- 渲染（PIL 3x 超采样）----

    def _render(self) -> None:
        painter = WidgetRenderer(self._w, self._h, self._scale, self._state, self._phase, self._glass)
        self._last_pil = painter.render()
        self._hits = painter.hits
        self._sync_surface(self._last_pil)

    def _sync_surface(self, small: Image.Image) -> None:
        """把渲染结果呈现到窗口：分层模式走 ULW（真逐像素 alpha），否则 Tk 贴图。"""
        if self._layered:
            if self._opacity_pct < 255:  # 整窗不透明度烘焙进 alpha 通道
                a = small.getchannel("A").point(lambda v: v * self._opacity_pct // 255)
                small = small.copy()
                small.putalpha(a)
            x, y = self.root.winfo_x(), self.root.winfo_y()
            ok = layered.update(self._hwnd, small, x, y)
            if not ok:  # ULW 中途失败（如休眠恢复）→ 回退贴图
                self._use_fallback()
                return  # 回退已按不透明底重新渲染，不能再覆盖为当前透光帧
            else:
                return
        self._photo = ImageTk.PhotoImage(small)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    def _init_layered(self) -> None:
        """尝试启用逐像素 alpha 分层窗口。"""
        self.root.update_idletasks()
        try:
            hwnd = layered.window_handle(self.root.winfo_id())
            layered.enable(hwnd)
            layered.no_activate(hwnd)
            self._hwnd = hwnd
            self._layered = True
            self._backdrop = tkinter.Toplevel(self.root)
            self._backdrop.withdraw()
            self._backdrop.overrideredirect(True)
            self._backdrop.attributes("-topmost", True)
            self._backdrop.geometry(f"{self._w}x{self._h}")
            self._backdrop.update_idletasks()
            self._backdrop_hwnd = layered.window_handle(self._backdrop.winfo_id())
            layered.enable(self._backdrop_hwnd)
            layered.no_activate(self._backdrop_hwnd)
            pad = max(2, round(2 * self._scale))
            self._glass = layered.enable_blur(self._backdrop_hwnd, self._w - 2 * pad, self._h - 2 * pad,
                                              max(1, round(CORNER_RADIUS * self._scale) - pad))
            if self._glass:
                self._backdrop.deiconify()
                self._sync_backdrop()
            else:
                self._backdrop.destroy()
                self._backdrop = None
            # ULW 自行保留表面。Expose 时重贴旧尺寸会覆盖尚在处理的 Tk geometry。
            self._render()
        except Exception:  # noqa: BLE001
            self._use_fallback()

    def _on_configure(self, ev) -> None:
        if ev.widget is self.root:
            if not getattr(self, "_resizing", False):
                self._refresh_dpi()
            if self._glass:
                self._sync_backdrop()

    def _refresh_dpi(self) -> None:
        scale = window_scale(self.root)
        if abs(scale - self._dpi_scale) > 0.01:
            preference = self._scale / self._dpi_scale
            self._dpi_scale = scale
            self.apply_appearance(preference, self._opacity)

    def _sync_backdrop(self) -> None:
        if not self._glass or self._backdrop is None:
            return
        pad = max(2, round(2 * self._scale))
        w, h = self._w - pad * 2, self._h - pad * 2
        x, y = self.root.winfo_x() + pad, self.root.winfo_y() + pad
        shape = (w, h, pad)
        if getattr(self, "_backdrop_shape", None) != shape:
            if not layered.resize_blur(self._backdrop_hwnd, w, h,
                                       max(1, round(CORNER_RADIUS * self._scale) - pad)):
                self._disable_backdrop()
                return
            self._backdrop_shape = shape
        surface = Image.new("RGBA", (w, h), (0, 0, 0, 1))
        if not layered.update(self._backdrop_hwnd, surface, x, y):
            self._disable_backdrop()
            return
        layered.place_behind(self._backdrop_hwnd, self._hwnd, x, y, w, h)

    def _disable_backdrop(self) -> None:
        self._glass = False
        if self._backdrop is not None:
            self._backdrop.destroy()
            self._backdrop = None
        self._render()

    def _use_fallback(self) -> None:
        """回退 transparentcolor + 整窗 alpha（有边缘损失，保功能）。"""
        if self._fallback_applied:
            return
        self._fallback_applied = True
        self._glass = False
        if self._backdrop is not None:
            self._backdrop.destroy()
            self._backdrop = None
        if hasattr(self, "_hwnd"):
            layered.disable(self._hwnd)
        self._layered = False
        self._glass = False
        self.root.attributes("-transparentcolor", KEY_COLOR)
        self.root.attributes("-alpha", self._opacity_pct / 255)
        self._render()

    def _animate(self) -> None:
        if not self.root.winfo_exists():
            return
        if self._state in ("listening", "proofreading", "loading"):
            self._phase += 1
            self._render()
        self._anim_job = self.root.after(90, self._animate)

    # ---- 交互 ----

    def _bind(self) -> None:
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, ev) -> None:
        self._drag_off = (ev.x, ev.y)
        self._drag_moved = False
        self._resizing = ev.x >= self._w - max(18, round(20 * self._scale)) and ev.y >= self._h - max(18, round(20 * self._scale))
        self._resize_origin = (getattr(ev, "x_root", ev.x), getattr(ev, "y_root", ev.y), self._w, self._h)

    def _hit(self, x: int, y: int) -> str | None:
        for kind, (cx, cy, r) in self._hits.items():
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                return kind
        return None

    def _on_motion(self, ev) -> None:
        if self._drag_off is None:
            return
        if self._resizing:
            x0, y0, w0, h0 = self._resize_origin
            wanted_h = max(round(BASE_H * 0.5 * self._dpi_scale),
                           min(round(BASE_H * 1.5 * self._dpi_scale), h0 + ev.y_root - y0))
            wanted_w = max(round(wanted_h * MIN_ASPECT), min(round(wanted_h * MAX_ASPECT), w0 + ev.x_root - x0))
            self._scale = wanted_h / BASE_H
            self._aspect = wanted_w / wanted_h
            self._resize_surface(wanted_w, wanted_h)
            self._drag_moved = True
            return
        dx, dy = ev.x - self._drag_off[0], ev.y - self._drag_off[1]
        if not self._drag_moved and abs(dx) + abs(dy) > 4:
            self._drag_moved = True  # 超过阈值才算拖动，此前不挪窗（防 1-3px 抖动）
        if self._drag_moved:
            self.root.geometry(f"+{self.root.winfo_x() + dx}+{self.root.winfo_y() + dy}")
            self.root.update_idletasks()  # 先落实位置，否则 ULW 会用旧坐标撤销移动
            if self._layered and self._last_pil is not None:
                self._sync_surface(self._last_pil)

    def _on_release(self, ev) -> None:
        if self._resizing and self._drag_moved and self._on_resize:
            self._on_resize(self._scale / self._dpi_scale, self._aspect)
        if not self._resizing and not self._drag_moved and self._drag_off is not None:
            kind = self._hit(ev.x, ev.y)
            if kind == "gear" and self._on_settings:
                self._on_settings()
            elif kind == "close" and self._on_hide:
                self._on_hide()
            elif self._on_toggle:  # 麦克风/其他区域 = 切换听写
                self._on_toggle()
        self._drag_off = None
        self._resizing = False
        self._refresh_dpi()

    # ---- 状态与队列（工作线程 → 主线程）----

    def set_state(self, state: str) -> None:
        """主线程调用：切换状态并重绘。"""
        if state in ("loading", "listening", "proofreading"):
            self._cancel_notice()
        if self._error_reset_job is not None:
            self.root.after_cancel(self._error_reset_job)
            self._error_reset_job = None
        if state != self._state:
            self._state = state
            self._render()
        if state == "error":
            self._error_reset_job = self.root.after(ERROR_RESET_MS, self._reset_error)

    def _reset_error(self) -> None:
        self._error_reset_job = None
        if self._state == "error":
            self.set_state("idle")

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
        if self._glass and self._backdrop is not None:
            self._backdrop.deiconify()
            self.root.update_idletasks()
            self._sync_backdrop()

    def hide(self) -> None:
        if self._backdrop is not None:
            self._backdrop.withdraw()
        self.root.withdraw()

    def show_notice(self, message: str) -> None:
        """在悬浮窗附近显示不抢焦点的输入位置提示，7.5 秒后自动关闭。"""
        if self._notice_job is not None:
            try:
                self.root.after_cancel(self._notice_job)
            except tkinter.TclError:
                pass
            self._notice_job = None

        scale = self._dpi_scale
        left, top, right, bottom = window_workarea(self.root)
        work_w, work_h = max(1, right - left), max(1, bottom - top)
        width = min(round(420 * scale), max(1, work_w - round(16 * scale)))
        height = min(round(188 * scale), max(1, work_h - round(16 * scale)))
        gap = round(12 * scale)
        if self.root.winfo_viewable():
            x = self.root.winfo_rootx() + (self._w - width) // 2
            y = self.root.winfo_rooty() + self._h + gap
            if y + height > bottom - round(8 * scale):
                y = self.root.winfo_rooty() - height - gap
        else:
            x, y = right - width - round(16 * scale), bottom - height - round(16 * scale)
        x = max(left + round(8 * scale), min(x, right - width - round(8 * scale)))
        y = max(top + round(8 * scale), min(y, bottom - height - round(8 * scale)))

        notice = self._notice_window
        if notice is None or not notice.winfo_exists():
            notice = tkinter.Toplevel(self.root)
            self._notice_window = notice
            notice.withdraw()
            notice.overrideredirect(True)
            notice.attributes("-topmost", True)
            notice.configure(takefocus=False)
            notice.configure(bg="#172334")
            notice.title("未开始听写")
            notice_frame = tkinter.Frame(notice, bg="#172334", padx=round(16 * scale), pady=round(12 * scale))
            notice_frame.pack(fill="both", expand=True)
            self._notice_title = tkinter.Label(
                notice_frame, text="未开始听写", anchor="w", bg="#172334", fg="#FFFFFF",
                font=("Microsoft YaHei UI", -round(16 * scale), "bold"), takefocus=False,
            )
            self._notice_title.pack(fill="x")
            body = tkinter.Frame(notice_frame, bg="#172334")
            body.pack(fill="both", expand=True, pady=(round(6 * scale), round(6 * scale)))
            text = tkinter.Text(body, wrap="word", relief="flat", bd=0, padx=0, pady=0,
                                bg="#172334", fg="#E8EEF7", insertwidth=0,
                                font=("Microsoft YaHei UI", -round(14 * scale),),
                                takefocus=False, state="disabled", height=5)
            scrollbar = tkinter.Scrollbar(body, command=text.yview, takefocus=False)
            text.configure(yscrollcommand=scrollbar.set)
            text.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            self._notice_text = text
            self._notice_footer = tkinter.Label(
                notice_frame, text="请先点击输入框，再按快捷键开始听写。", anchor="w",
                bg="#172334", fg="#B8C7DA",
                font=("Microsoft YaHei UI", -round(12 * scale)), takefocus=False,
            )
            self._notice_footer.pack(fill="x")
        else:
            text = self._notice_text

        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", message)
        text.configure(state="disabled")
        notice.geometry(f"{width}x{height}+{x}+{y}")
        notice.update_idletasks()
        hwnd = layered.window_handle(notice.winfo_id())
        user = ctypes.windll.user32
        get_long = user.GetWindowLongW
        get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_long.restype = ctypes.c_long
        set_long = user.SetWindowLongW
        set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        set_long.restype = ctypes.c_long
        exstyle = get_long(hwnd, -20)
        set_long(hwnd, -20, exstyle | WS_EX_NOACTIVATE | 0x80)
        user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user.SetWindowPos(hwnd, ctypes.c_void_p(-1), x, y, width, height, 0x0010 | 0x0040)
        self._notice_job = self.root.after(NOTICE_DURATION_MS, self._dismiss_notice)

    def _dismiss_notice(self) -> None:
        self._notice_job = None
        self._destroy_notice()

    def _cancel_notice(self) -> None:
        if self._notice_job is not None:
            try:
                self.root.after_cancel(self._notice_job)
            except tkinter.TclError:
                pass
            self._notice_job = None
        self._destroy_notice()

    def _destroy_notice(self) -> None:
        notice, self._notice_window = self._notice_window, None
        self._notice_text = None
        self._notice_title = None
        self._notice_footer = None
        if notice is not None:
            try:
                if notice.winfo_exists():
                    notice.destroy()
            except tkinter.TclError:
                pass

    def _on_root_destroy(self, event) -> None:
        if event.widget is self.root:
            if self._notice_job is not None:
                try:
                    self.root.after_cancel(self._notice_job)
                except tkinter.TclError:
                    pass
                self._notice_job = None
            self._notice_window = None
            self._notice_text = None
            self._notice_title = None
            self._notice_footer = None

    def _resize_surface(self, width: int, height: int) -> None:
        self._w, self._h = width, height
        self.canvas.config(width=self._w, height=self._h)
        self.root.geometry(f"{self._w}x{self._h}")
        self.root.update_idletasks()
        if self._glass:
            self._sync_backdrop()
        self._render()

    def apply_appearance(self, scale: float, opacity: float, aspect: float | None = None) -> None:
        """主线程调用：调整大小与透明度并重绘。"""
        self._scale = scale * self._dpi_scale
        if aspect is not None:
            self._aspect = max(MIN_ASPECT, min(MAX_ASPECT, aspect))
        self._opacity = opacity
        self._opacity_pct = int(round(opacity * 255))
        if not self._layered:
            self.root.attributes("-alpha", opacity)
        height = round(BASE_H * self._scale)
        self._resize_surface(round(height * self._aspect), height)

    def run_tick(self, tick, interval_ms: int = 30) -> None:
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

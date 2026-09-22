"""悬浮窗：置顶、可拖动的圆角磨砂状态窗（美术稿 assets/悬浮窗-*.jpg）。

渲染：整面板用 Pillow 以 3x 超采样绘制再缩小（抗锯齿），tkinter 只负责贴图与
事件；系统合成器实时模糊背后内容，失败回退深蓝渐变。声波按 ~90ms 重绘。

状态：idle 待命 / loading 准备 / listening 聆听 / proofreading 校对 / error 短暂不可用提示。
线程约定：公开方法须在主线程调用；工作线程经 ui_queue 传 ("state", s) 由 pump 应用。
"""

from __future__ import annotations

import ctypes
import math
import queue
import tkinter

from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageFilter, ImageChops

from voice2text import layered

KEY_COLOR = "#10161F"  # transparentcolor 魔法色——取接近药丸底色的深藏青，边缘混合不显黑边
BASE_W, BASE_H = 340, 104
MIN_ASPECT, MAX_ASPECT = 1.0, 5.0
CORNER_RADIUS = 22
SS = 3  # 超采样倍数
ERROR_RESET_MS = 2000

# 美术稿取色
BG_TOP = (38, 53, 82)
BG_BOTTOM = (14, 21, 33)
EDGE = (82, 100, 130)
TEXT_PRIMARY = "#F4F7FC"
TEXT_SECONDARY = "#97A3B4"
IDLE_RING = (148, 161, 178)
IDLE_MIC = (232, 238, 246)
LISTEN = (255, 99, 95)
PROOF = (86, 168, 255)
LOADING = (152, 165, 179)
ERROR = (138, 148, 162)
CIRCLE_FILL = (12, 19, 31)

STATUS_TEXT = {
    "idle": "待命中...",
    "loading": "准备中，请稍候",
    "listening": "正在聆听...",
    "proofreading": "校对中...",
    "error": "不可用",
}

_STATE_COLOR = {
    "idle": IDLE_RING,
    "loading": LOADING,
    "listening": LISTEN,
    "proofreading": PROOF,
    "error": ERROR,
}


def _font(px: int):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", px)
    except OSError:
        return ImageFont.load_default()


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


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
        self._phase = 0.0
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
        self._h = round(BASE_H * scale)
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
        self._animate()

    @property
    def state(self) -> str:
        return self._state

    def snapshot(self) -> Image.Image:
        """返回未施加整体透明度的当前画面，供设置页预览。"""
        return self._last_pil.copy()

    # ---- 渲染（PIL 3x 超采样）----

    def _render(self) -> None:
        w, h = self._w, self._h
        W, H = w * SS, h * SS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        R = round(CORNER_RADIUS * self._scale * SS)

        # 原生模糊之上的深蓝透光层；回退模式使用不透明渐变。
        for y in range(H):
            t = y / H
            alpha = round(150 + 40 * t) if self._glass else 255
            d.line([0, y, W, y], fill=(*_lerp(BG_TOP, BG_BOTTOM, t), alpha))
        if self._glass:
            # 模糊底层内缩 4px，外边缘由不透明细边带遮住其硬裁剪。
            # 内外 alpha 平滑过渡，真正的外轮廓始终只由 ULW 抗锯齿承担。
            rim = Image.new("L", (W, H), 255)
            inset = round(4 * self._scale * SS)
            ImageDraw.Draw(rim).rounded_rectangle(
                [inset, inset, W - 1 - inset, H - 1 - inset],
                radius=max(1, R - inset), fill=0,
            )
            rim = rim.filter(ImageFilter.GaussianBlur(max(1, self._scale * SS)))
            img.putalpha(ImageChops.lighter(img.getchannel("A"), rim))
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=255)
        pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pill.paste(img, (0, 0), mask)
        d = ImageDraw.Draw(pill)
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=R, outline=(*EDGE, 255), width=SS)

        accent = _STATE_COLOR.get(self._state, IDLE_RING)
        accent255 = (*accent, 255)
        compact = self._aspect < 2.2

        # 左上：品牌格点 + 标题（与右侧按钮同一水平线）
        unit = self._scale * SS
        row_cy = round(23 * unit)
        gx = round(21 * unit)
        gs = round(4 * unit)
        gap = round(6 * unit)
        gy = row_cy - (gap + gs) // 2
        for dx in (0, 1):
            for dy in (0, 1):
                d.rounded_rectangle(
                    [gx + dx * gap, gy + dy * gap, gx + dx * gap + gs, gy + dy * gap + gs],
                    radius=max(1, round(unit)), fill=(170, 184, 204, 255),
                )
        if not compact:
            f_title = _font(round(11 * unit))
            d.text((round(39 * unit), row_cy), "语音输入", anchor="lm",
                   font=f_title, fill=(185, 198, 218, 255))

        # 右上：齿轮 | 分隔线 | 关闭（加大图标、留足右缘呼吸空间）
        gear_cx = W - round((47 if compact else 67) * unit)
        div_x = W - round((31 if compact else 47) * unit)
        close_cx = W - round((16 if compact else 27) * unit)
        self._draw_gear(d, gear_cx, row_cy, round((6 if compact else 7) * unit), (170, 184, 204, 255))
        d.line([div_x, row_cy - 7 * unit, div_x, row_cy + 7 * unit],
               fill=(67, 83, 107, 200), width=max(1, round(unit)))
        r_x = round(5 * unit)
        d.line([close_cx - r_x, row_cy - r_x, close_cx + r_x, row_cy + r_x], fill=(178, 190, 206, 255), width=max(1, round(1.2 * unit)))
        d.line([close_cx - r_x, row_cy + r_x, close_cx + r_x, row_cy - r_x], fill=(178, 190, 206, 255), width=max(1, round(1.2 * unit)))
        # 命中区（最终像素坐标）
        self._hits = {
            "gear": (gear_cx // SS, row_cy // SS, int((13 if compact else 16) * self._scale)),
            "close": (close_cx // SS, row_cy // SS, int((12 if compact else 14) * self._scale)),
        }

        # 中央：麦克风圆环 + 麦克风
        mr = round((23 if compact else 26) * unit)
        mcx, mcy = W // 2, round((54 if compact else 46) * unit)
        d.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], fill=(*CIRCLE_FILL, 155 if self._glass else 255))
        ring_w = max(1, round((1.2 if self._state in ("idle", "loading") else 1.6) * unit))
        d.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], outline=accent255, width=ring_w)
        mic_hit = int(18 * self._scale) if compact else int(mr / SS * 1.2)
        self._hits["mic"] = (mcx // SS, mcy // SS, mic_hit)
        self._draw_mic(d, mcx, mcy, mr, (*IDLE_MIC, 255) if self._state == "idle" else accent255)

        # 声波（聆听）或旋转指示（校对/加载）
        if self._state == "listening":
            heights = self._wave_heights(mr)
            if compact:
                heights = heights[:3]
            bar_w = max(2, round(2.5 * unit))
            for i, hh in enumerate(heights):
                start_gap = 5 if compact else 10
                bar_gap = 5 if compact else 8
                x = mcx - mr - int(start_gap * self._scale * SS) - i * int(bar_gap * self._scale * SS)
                fade = 1 - i * 0.12
                col = tuple(round(c * fade) for c in LISTEN) + (255,)
                d.rounded_rectangle([x - bar_w // 2, mcy - hh, x + bar_w // 2, mcy + hh], radius=bar_w // 2, fill=col)
                x2 = mcx + mr + int(start_gap * self._scale * SS) + i * int(bar_gap * self._scale * SS)
                d.rounded_rectangle([x2 - bar_w // 2, mcy - hh, x2 + bar_w // 2, mcy + hh], radius=bar_w // 2, fill=col)
        elif self._state in ("proofreading", "loading"):
            start_a = (self._phase * 240) % 360
            d.arc([mcx - mr, mcy - mr, mcx + mr, mcy + mr], start=start_a, end=start_a + 110,
                  fill=accent255, width=int(2 * SS))

        # 状态文字
        f_status = _font(round((9 if compact else 11) * unit))
        text = STATUS_TEXT.get(self._state, "")
        d.text((W / 2, round((89 if compact else 86) * unit)), text, anchor="mm", font=f_status, fill=(232, 237, 244, 255))

        # 右下角尺寸手柄：足够克制，但让“可调整大小”可以被发现。
        grip = round(8 * unit)
        gx, gy = W - round(9 * unit), H - round(9 * unit)
        for offset in (0, round(4 * unit)):
            d.line([gx - grip + offset, gy, gx, gy - grip + offset],
                   fill=(119, 139, 168, 185), width=max(1, round(unit)))

        # 缩小抗锯齿 → 贴图
        small = pill.resize((w, h), Image.LANCZOS)
        self._last_pil = small  # 测试/导出挂钩
        self._sync_surface(small)

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
        if ev.widget is self.root and self._glass:
            self._sync_backdrop()

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

    def _draw_mic(self, d: ImageDraw.ImageDraw, cx: int, cy: int, mr: int, color) -> None:
        u = mr / 19  # 麦克风占圆环约 60%，留足环内呼吸空间
        cap_w, cap_h = 3.5 * u, 6 * u
        d.rounded_rectangle(
            [cx - cap_w, cy - 11 * u, cx + cap_w, cy - 11 * u + 2 * cap_h],
            radius=cap_w, fill=color,
        )
        d.arc([cx - 6.5 * u, cy - 6 * u, cx + 6.5 * u, cy + 7 * u], start=0, end=180,
              fill=color, width=max(1, int(1.6 * u)))
        d.line([cx, cy + 7 * u, cx, cy + 10.5 * u], fill=color, width=max(1, int(1.6 * u)))
        d.rounded_rectangle([cx - 3.5 * u, cy + 10 * u, cx + 3.5 * u, cy + 11.5 * u],
                            radius=u, fill=color)

    def _draw_gear(self, d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color) -> None:
        points = []
        for k in range(48):
            a = math.tau * k / 48
            rr = r if k % 6 in (1, 2, 3, 4) else r * 0.78
            points.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        width = max(1, round(self._scale * SS))
        d.line(points + [points[0]], fill=color, width=width, joint="curve")
        inner = r * 0.32
        d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], outline=color, width=width)

    def _wave_heights(self, mr: int) -> list[int]:
        base = mr * 0.18
        amp = mr * 0.42
        out = []
        for i in range(5):
            v = math.sin(self._phase + i * 1.1) * 0.5 + 0.5
            out.append(int(base + v * amp) + 2)
        return out

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
            wanted_h = max(round(BASE_H * 0.5), min(round(BASE_H * 1.5), h0 + ev.y_root - y0))
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
            self._on_resize(self._scale, self._aspect)
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

    # ---- 状态与队列（工作线程 → 主线程）----

    def set_state(self, state: str) -> None:
        """主线程调用：切换状态并重绘。"""
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
        self._scale = scale
        if aspect is not None:
            self._aspect = max(MIN_ASPECT, min(MAX_ASPECT, aspect))
        self._opacity = opacity
        self._opacity_pct = int(round(opacity * 255))
        if not self._layered:
            self.root.attributes("-alpha", opacity)
        height = round(BASE_H * scale)
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

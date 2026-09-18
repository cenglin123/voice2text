"""悬浮窗：置顶、可拖动的圆角磨砂状态窗（美术稿 assets/悬浮窗-*.jpg）。

渲染：整面板用 Pillow 以 3x 超采样绘制再缩小（抗锯齿），tkinter 只负责贴图与
事件；系统合成器实时模糊背后内容，失败回退深蓝渐变。声波按 ~90ms 重绘。

状态：idle 待命 / loading 模型加载 / listening 聆听 / proofreading 校对 / error 不可用。
线程约定：公开方法须在主线程调用；工作线程经 ui_queue 传 ("state", s) 由 pump 应用。
"""

from __future__ import annotations

import ctypes
import math
import queue
import tkinter

from PIL import Image, ImageDraw, ImageFont, ImageTk

from voice2text import layered

KEY_COLOR = "#10161F"  # transparentcolor 魔法色——取接近药丸底色的深藏青，边缘混合不显黑边
BASE_W, BASE_H = 340, 104
CORNER_RADIUS = 22
SS = 3  # 超采样倍数

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
    "loading": "加载中...",
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
        self._w, self._h = int(BASE_W * scale), int(BASE_H * scale)
        self.root.geometry(f"{self._w}x{self._h}+60+60")
        self._opacity_pct = int(round(opacity * 255))
        # 分层窗口（逐像素 alpha，边缘真平滑）；失败回退 transparentcolor + 整窗 alpha
        self._layered = False
        self._glass = False
        self._fallback_applied = False

        self.canvas = tkinter.Canvas(self.root, width=self._w, height=self._h, bg="#10161F", highlightthickness=0)
        self.canvas.pack()
        self._photo = None
        self._hits: dict[str, tuple[int, int, int]] = {}  # kind -> (cx, cy, r)
        self._render()
        self._bind()
        self.root.deiconify()
        self._init_layered()
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
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=255)
        pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pill.paste(img, (0, 0), mask)
        d = ImageDraw.Draw(pill)
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=R, outline=(*EDGE, 255), width=SS)

        accent = _STATE_COLOR.get(self._state, IDLE_RING)
        accent255 = (*accent, 255)

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
        f_title = _font(round(11 * unit))
        d.text((round(39 * unit), row_cy), "语音输入", anchor="lm",
               font=f_title, fill=(185, 198, 218, 255))

        # 右上：齿轮 | 分隔线 | 关闭（加大图标、留足右缘呼吸空间）
        gear_cx = round(273 * unit)
        div_x = round(293 * unit)
        close_cx = round(313 * unit)
        self._draw_gear(d, gear_cx, row_cy, round(7 * unit), (170, 184, 204, 255))
        d.line([div_x, row_cy - 8 * unit, div_x, row_cy + 8 * unit],
               fill=(67, 83, 107, 200), width=max(1, round(unit)))
        r_x = round(5 * unit)
        d.line([close_cx - r_x, row_cy - r_x, close_cx + r_x, row_cy + r_x], fill=(178, 190, 206, 255), width=max(1, round(1.2 * unit)))
        d.line([close_cx - r_x, row_cy + r_x, close_cx + r_x, row_cy - r_x], fill=(178, 190, 206, 255), width=max(1, round(1.2 * unit)))
        # 命中区（最终像素坐标）
        self._hits = {
            "gear": (gear_cx // SS, row_cy // SS, int(16 * self._scale)),
            "close": (close_cx // SS, row_cy // SS, int(14 * self._scale)),
        }

        # 中央：麦克风圆环 + 麦克风
        mr = round(26 * unit)
        mcx, mcy = W // 2, round(46 * unit)
        d.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], fill=(*CIRCLE_FILL, 155 if self._glass else 255))
        ring_w = max(1, round((1.2 if self._state in ("idle", "loading") else 1.6) * unit))
        d.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], outline=accent255, width=ring_w)
        self._hits["mic"] = (mcx // SS, mcy // SS, int(mr / SS * 1.2))
        self._draw_mic(d, mcx, mcy, mr, (*IDLE_MIC, 255) if self._state == "idle" else accent255)

        # 声波（聆听）或旋转指示（校对/加载）
        if self._state == "listening":
            heights = self._wave_heights(mr)
            bar_w = max(2, round(2.5 * unit))
            for i, hh in enumerate(heights):
                x = mcx - mr - int(10 * self._scale * SS) - i * int(8 * self._scale * SS)
                fade = 1 - i * 0.12
                col = tuple(round(c * fade) for c in LISTEN) + (255,)
                d.rounded_rectangle([x - bar_w // 2, mcy - hh, x + bar_w // 2, mcy + hh], radius=bar_w // 2, fill=col)
                x2 = mcx + mr + int(10 * self._scale * SS) + i * int(8 * self._scale * SS)
                d.rounded_rectangle([x2 - bar_w // 2, mcy - hh, x2 + bar_w // 2, mcy + hh], radius=bar_w // 2, fill=col)
        elif self._state in ("proofreading", "loading"):
            start_a = (self._phase * 240) % 360
            d.arc([mcx - mr, mcy - mr, mcx + mr, mcy + mr], start=start_a, end=start_a + 110,
                  fill=accent255, width=int(2 * SS))

        # 状态文字
        f_status = _font(round(11 * unit))
        text = STATUS_TEXT.get(self._state, "")
        d.text((W / 2, round(86 * unit)), text, anchor="mm", font=f_status, fill=(232, 237, 244, 255))

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
            self._hwnd = hwnd
            self._layered = True
            self._glass = layered.enable_blur(hwnd, self._w, self._h,
                                              round(CORNER_RADIUS * self._scale))
            # ULW 自行保留表面。Expose 时重贴旧尺寸会覆盖尚在处理的 Tk geometry。
            self._render()
        except Exception:  # noqa: BLE001
            self._use_fallback()

    def _use_fallback(self) -> None:
        """回退 transparentcolor + 整窗 alpha（有边缘损失，保功能）。"""
        if self._fallback_applied:
            return
        self._fallback_applied = True
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

    def _hit(self, x: int, y: int) -> str | None:
        for kind, (cx, cy, r) in self._hits.items():
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                return kind
        return None

    def _on_motion(self, ev) -> None:
        if self._drag_off is None:
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
        if not self._drag_moved and self._drag_off is not None:
            kind = self._hit(ev.x, ev.y)
            if kind == "gear" and self._on_settings:
                self._on_settings()
            elif kind == "close" and self._on_hide:
                self._on_hide()
            elif self._on_toggle:  # 麦克风/其他区域 = 切换听写
                self._on_toggle()
        self._drag_off = None

    # ---- 状态与队列（工作线程 → 主线程）----

    def set_state(self, state: str) -> None:
        """主线程调用：切换状态并重绘。"""
        if state != self._state:
            self._state = state
            self._render()

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
        self._opacity_pct = int(round(opacity * 255))
        if not self._layered:
            self.root.attributes("-alpha", opacity)
        self._w, self._h = int(BASE_W * scale), int(BASE_H * scale)
        self.canvas.config(width=self._w, height=self._h)
        self.root.geometry(f"{self._w}x{self._h}")
        self.root.update_idletasks()
        if self._glass:
            if not layered.resize_blur(self._hwnd, self._w, self._h,
                                       round(CORNER_RADIUS * self._scale)):
                layered.disable_blur(self._hwnd)
                self._glass = False
        self._render()

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

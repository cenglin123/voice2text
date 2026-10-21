"""悬浮窗的纯 Pillow 绘制：实际窗口与设置页状态预览共用，无 Tk 或 Win32 副作用。"""
from __future__ import annotations

import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

BASE_W, BASE_H = 340, 104
MIN_ASPECT, MAX_ASPECT = 1.0, 5.0
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
    "idle": "待命中",
    "loading": "准备中，请稍候",
    "listening": "正在聆听",
    "proofreading": "校对中",
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


class WidgetRenderer:
    def __init__(self, width: int, height: int, scale: float, state: str,
                 phase: float = 0.0, glass: bool = False) -> None:
        self._w, self._h = width, height
        self._scale, self._state = scale, state
        self._aspect = width / height
        self._phase, self._glass = phase, glass
        self.hits: dict[str, tuple[int, int, int]] = {}
        self.text_bounds: dict[str, tuple[float, float, float, float]] = {}
        self.wave_bounds: list[tuple[float, float, float, float]] = []

    def render(self) -> Image.Image:
        self.text_bounds.clear()
        self.wave_bounds.clear()
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
        row_cy = round((19 if compact else 23) * unit)
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
        self.hits = {
            "gear": (gear_cx // SS, row_cy // SS, int((13 if compact else 16) * self._scale)),
            "close": (close_cx // SS, row_cy // SS, int((12 if compact else 14) * self._scale)),
        }

        # 中央：麦克风圆环 + 麦克风
        mr = round((22 if compact else 26) * unit)
        mcx, mcy = W // 2, round((55 if compact else 46) * unit)
        d.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], fill=(*CIRCLE_FILL, 155 if self._glass else 255))
        ring_w = max(1, round((1.2 if self._state in ("idle", "loading") else 1.6) * unit))
        d.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], outline=accent255, width=ring_w)
        mic_hit = int(18 * self._scale) if compact else int(mr / SS * 1.2)
        self.hits["mic"] = (mcx // SS, mcy // SS, mic_hit)
        self._draw_mic(d, mcx, mcy, mr, (*IDLE_MIC, 255) if self._state == "idle" else accent255)

        # 声波（聆听）或旋转指示（校对/加载）
        if self._state == "listening":
            heights = self._wave_heights(mr)
            start_gap = (6 if compact else 10) * unit
            bar_gap = (5 if compact else 8) * unit
            # 窄窗只画可容纳的声波，禁止横向拉扁或画出面板。
            count = min(len(heights), 1 + max(0, int((mcx - mr - start_gap - 12 * unit) / bar_gap)))
            heights = heights[:count]
            bar_w = max(2, round(2.5 * unit))
            for i, hh in enumerate(heights):
                x = mcx - mr - start_gap - i * bar_gap
                fade = 1 - i * 0.12
                col = tuple(round(c * fade) for c in LISTEN) + (255,)
                d.rounded_rectangle([x - bar_w // 2, mcy - hh, x + bar_w // 2, mcy + hh], radius=bar_w // 2, fill=col)
                self.wave_bounds.append((x - bar_w // 2, mcy - hh, x + bar_w // 2, mcy + hh))
                x2 = mcx + mr + start_gap + i * bar_gap
                d.rounded_rectangle([x2 - bar_w // 2, mcy - hh, x2 + bar_w // 2, mcy + hh], radius=bar_w // 2, fill=col)
                self.wave_bounds.append((x2 - bar_w // 2, mcy - hh, x2 + bar_w // 2, mcy + hh))
        elif self._state in ("proofreading", "loading"):
            start_a = (self._phase * 240) % 360
            d.arc([mcx - mr, mcy - mr, mcx + mr, mcy + mr], start=start_a, end=start_a + 110,
                  fill=accent255, width=max(1, round(2 * unit)))

        # 状态文字
        f_status = _font(max(1, round((10 if compact else 11) * unit)))
        text = STATUS_TEXT.get(self._state, "")
        if compact and self._state == "loading":
            text = "准备中"
        position = (W / 2, round((89 if compact else 86) * unit))
        self.text_bounds["status"] = d.textbbox(position, text, anchor="mm", font=f_status)
        d.text(position, text, anchor="mm", font=f_status, fill=(232, 237, 244, 255))

        # 右下角尺寸手柄：足够克制，但让“可调整大小”可以被发现。
        grip = round(8 * unit)
        gx, gy = W - round(9 * unit), H - round(9 * unit)
        for offset in (0, round(4 * unit)):
            d.line([gx - grip + offset, gy, gx, gy - grip + offset],
                   fill=(119, 139, 168, 185), width=max(1, round(unit)))

        # 缩小抗锯齿 → 贴图
        small = pill.resize((w, h), Image.LANCZOS)
        return small

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

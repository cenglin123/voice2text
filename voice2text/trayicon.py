"""托盘图标：Pillow 按美术稿绘制麦克风剪影，四种状态配色。

状态映射（assets/托盘图标形状.jpg）：
- idle      白色（待命）
- listening 蓝色+声波（识别中）
- recording 红色+右上角圆点（录音/听写中）
- error     灰色+斜杠（不可用）
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

COLOR_IDLE = "#F2F5F9"
COLOR_LISTEN = "#4C9DF8"
COLOR_RECORD = "#FA5A52"
COLOR_ERROR = "#76808E"

_TRANSPARENT = (0, 0, 0, 0)


def draw_icon(state: str = "idle", size: int = 64) -> Image.Image:
    """绘制指定状态的托盘图标。size 为边长（正方形）。"""
    img = Image.new("RGBA", (size, size), _TRANSPARENT)
    d = ImageDraw.Draw(img)
    s = size / 64.0  # 按 64 设计稿缩放

    color = {
        "idle": COLOR_IDLE,
        "listening": COLOR_LISTEN,
        "recording": COLOR_RECORD,
        "error": COLOR_ERROR,
    }.get(state, COLOR_IDLE)

    lw = max(2, round(4 * s))
    # 麦克风主体：胶囊形
    d.rounded_rectangle([26 * s, 10 * s, 38 * s, 34 * s], radius=6 * s, fill=color)
    # U 形支架（下半圆弧）
    d.arc([20 * s, 16 * s, 44 * s, 42 * s], start=15, end=165, fill=color, width=lw)
    # 杆 + 底座
    d.line([32 * s, 42 * s, 32 * s, 48 * s], fill=color, width=lw)
    d.rounded_rectangle([24 * s, 48 * s, 40 * s, 53 * s], radius=2 * s, fill=color)

    if state == "listening":
        # 两侧声波（弧线）；坐标均为 64 设计稿单位，使用处统一乘 s
        for k, r in enumerate((3, 7)):
            x0 = 12 - k * 4
            d.arc(
                [x0 * s, (24 - r) * s, (x0 + 2 * r) * s, (24 + r) * s],
                start=70, end=290, fill=color, width=max(2, round(2.5 * s)),
            )
            x1 = 52 + k * 4
            d.arc(
                [(x1 - 2 * r) * s, (24 - r) * s, x1 * s, (24 + r) * s],
                start=250, end=470, fill=color, width=max(2, round(2.5 * s)),
            )
    elif state == "recording":
        # 右上角圆点
        d.ellipse([44 * s, 8 * s, 54 * s, 18 * s], fill=COLOR_RECORD)
    elif state == "error":
        # 斜杠
        d.line([14 * s, 50 * s, 50 * s, 14 * s], fill=color, width=lw)

    return img


def icon_bytes(state: str = "idle", size: int = 64) -> bytes:
    """PNG 字节（调试/落盘用）。"""
    buf = io.BytesIO()
    draw_icon(state, size).save(buf, format="PNG")
    return buf.getvalue()

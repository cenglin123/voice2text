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
    img = Image.new("RGBA", (size * 4, size * 4), _TRANSPARENT)
    d = ImageDraw.Draw(img)
    s = size * 4 / 64.0  # 超采样后缩小，16/20px 托盘也保留平滑轮廓

    color = {
        "idle": COLOR_IDLE,
        "listening": COLOR_LISTEN,
        "recording": COLOR_RECORD,
        "error": COLOR_ERROR,
    }.get(state, COLOR_IDLE)

    lw = max(2, round(6 * s))
    # 麦克风主体：胶囊形
    d.rounded_rectangle([22 * s, 5 * s, 42 * s, 36 * s], radius=10 * s, fill=color)
    # U 形支架（下半圆弧）
    d.arc([13 * s, 14 * s, 51 * s, 49 * s], start=0, end=180, fill=color, width=lw)
    # 杆 + 底座
    d.line([32 * s, 47 * s, 32 * s, 56 * s], fill=color, width=lw)
    d.rounded_rectangle([21 * s, 54 * s, 43 * s, 60 * s], radius=3 * s, fill=color)

    if state == "listening":
        # 两侧声波（弧线）；坐标均为 64 设计稿单位，使用处统一乘 s
        # 小尺寸仅保留一组粗声波，避免多重细弧缩小后粘连。
        d.arc([3 * s, 14 * s, 17 * s, 44 * s], 110, 250, fill=color, width=round(4 * s))
        d.arc([47 * s, 14 * s, 61 * s, 44 * s], -70, 70, fill=color, width=round(4 * s))
    elif state == "recording":
        # 右上角圆点
        d.ellipse([48 * s, 3 * s, 61 * s, 16 * s], fill=COLOR_RECORD)
    elif state == "error":
        # 斜杠
        d.line([9 * s, 55 * s, 55 * s, 9 * s], fill=color, width=lw)

    return img.resize((size, size), Image.Resampling.LANCZOS)


def icon_bytes(state: str = "idle", size: int = 64) -> bytes:
    """PNG 字节（调试/落盘用）。"""
    buf = io.BytesIO()
    draw_icon(state, size).save(buf, format="PNG")
    return buf.getvalue()

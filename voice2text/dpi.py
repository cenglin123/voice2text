"""Windows system-DPI-aware UI 的物理像素倍率。"""

from __future__ import annotations

import ctypes


def enable_system_dpi_awareness() -> None:
    """首个窗口创建前调用；已有 manifest/宿主设置时维持当前模式。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def system_scale() -> float:
    """系统 DPI 对 96 DPI 设计像素的倍率；未感知时由 Windows 自行缩放。"""
    try:
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
    except (AttributeError, OSError):
        return 1.0
    return max(1.0, min(4.0, dpi / 96.0))

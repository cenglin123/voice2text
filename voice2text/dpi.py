"""Windows 窗口 DPI 与可用工作区；兼容宿主已声明的 DPI 模式。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


def enable_dpi_awareness() -> None:
    """依赖和首个窗口创建前显式启用 PMv1；宿主已声明时不覆盖。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def system_scale() -> float:
    """系统 DPI 对 96 DPI 设计像素的倍率；未感知时由 Windows 自行缩放。"""
    try:
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
    except (AttributeError, OSError):
        return 1.0
    return max(1.0, min(4.0, dpi / 96.0))


def _window_handle(window) -> int:
    user = ctypes.windll.user32
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    return user.GetAncestor(window.winfo_id(), 2) or window.winfo_id()


def window_scale(window) -> float:
    """创建并定位窗口后读取；PM-aware 宿主下不能用系统 DPI 代替。"""
    try:
        user = ctypes.windll.user32
        user.GetDpiForWindow.argtypes = [wintypes.HWND]
        user.GetDpiForWindow.restype = wintypes.UINT
        dpi = user.GetDpiForWindow(_window_handle(window))
        if dpi:
            return max(1.0, min(4.0, dpi / 96.0))
    except (AttributeError, OSError):
        pass
    return system_scale()


def window_workarea(window) -> tuple[int, int, int, int]:
    """窗口所在显示器的工作区，排除任务栏，保留多屏负坐标。"""
    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

    user = ctypes.windll.user32
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HANDLE
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
    monitor = user.MonitorFromWindow(_window_handle(window), 2)
    if monitor and user.GetMonitorInfoW(monitor, ctypes.byref(info)):
        r = info.work
        return r.left, r.top, r.right, r.bottom
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()

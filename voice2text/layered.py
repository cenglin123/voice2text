"""Win32 分层窗口（UpdateLayeredWindow）：逐像素 alpha，悬浮窗边缘真平滑。

transparentcolor 方案只有 1 位透明（边缘半透明像素会与魔法色混出暗边/锯齿）；
本模块把整窗内容替换为一张带 alpha 的位图，边缘与桌面任意背景平滑混合。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import numpy as np

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]

    def __init__(self, width: int, height: int):
        super().__init__()
        self.biSize = ctypes.sizeof(self)
        self.biWidth = width
        self.biHeight = -height  # 负值 = 自顶向下
        self.biPlanes = 1
        self.biBitCount = 32


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
    wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
]
_user32.UpdateLayeredWindow.restype = wintypes.BOOL


def enable(hwnd: int) -> None:
    """给窗口加 WS_EX_LAYERED 扩展样式。"""
    ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)


def update(hwnd: int, img_rgba, x: int, y: int) -> bool:
    """把 RGBA 图（直通 alpha）作为窗口内容按屏幕坐标 (x, y) 呈现。

    内部做预乘（UpdateLayeredWindow 要求）并转 BGRA。失败返回 False。
    """
    w, h = img_rgba.size
    arr = np.asarray(img_rgba, dtype=np.uint16).copy()
    alpha = arr[..., 3:4]
    arr[..., 0:3] = arr[..., 0:3] * alpha // 255  # 预乘
    raw = arr[..., [2, 1, 0, 3]].astype(np.uint8).tobytes()  # RGBA → BGRA（仅交换 R/B）

    hdc_screen = _user32.GetDC(None)
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    ptr = ctypes.c_void_p()
    bmi = BITMAPINFOHEADER(w, h)
    hbmp = _gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(ptr), None, 0)
    ok = False
    if hbmp and ptr:
        ctypes.memmove(ptr, raw, len(raw))
        prev = _gdi32.SelectObject(hdc_mem, hbmp)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        dst = POINT(x, y)
        size = SIZE(w, h)
        src = POINT(0, 0)
        ok = bool(_user32.UpdateLayeredWindow(
            hwnd, hdc_screen, ctypes.byref(dst), ctypes.byref(size),
            hdc_mem, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
        ))
        _gdi32.SelectObject(hdc_mem, prev)
        _gdi32.DeleteObject(hbmp)
    _gdi32.DeleteDC(hdc_mem)
    _user32.ReleaseDC(None, hdc_screen)
    return ok

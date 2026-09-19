"""Win32 分层窗口（UpdateLayeredWindow）：逐像素 alpha，悬浮窗边缘真平滑。

transparentcolor 方案只有 1 位透明（边缘半透明像素会与魔法色混出暗边/锯齿）；
本模块把整窗内容替换为一张带 alpha 的位图，边缘与桌面任意背景平滑混合。
"""

from __future__ import annotations

import ctypes
import sys
import winreg
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

_user32.GetParent.argtypes = [wintypes.HWND]
_user32.GetParent.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
_gdi32.SelectObject.restype = wintypes.HANDLE
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
    wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
]
_user32.UpdateLayeredWindow.restype = wintypes.BOOL


class _AccentPolicy(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                ("color", wintypes.DWORD), ("animation", ctypes.c_int)]


class _CompositionData(ctypes.Structure):
    _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p),
                ("size", ctypes.c_size_t)]


class _HighContrast(ctypes.Structure):
    _fields_ = [("size", wintypes.UINT), ("flags", wintypes.DWORD),
                ("scheme", wintypes.LPWSTR)]


_set_composition = getattr(_user32, "SetWindowCompositionAttribute", None)
if _set_composition is not None:
    _set_composition.argtypes = [wintypes.HWND, ctypes.POINTER(_CompositionData)]
    _set_composition.restype = wintypes.BOOL
_gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
_gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
_user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
_user32.SetWindowRgn.restype = ctypes.c_int
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
_user32.SystemParametersInfoW.restype = wintypes.BOOL


def _accent(hwnd: int, state: int) -> bool:
    if _set_composition is None:
        return False
    policy = _AccentPolicy(state, 0, 0, 0)
    data = _CompositionData(19, ctypes.addressof(policy), ctypes.sizeof(policy))  # WCA_ACCENT_POLICY
    return bool(_set_composition(hwnd, ctypes.byref(data)))


def resize_blur(hwnd: int, width: int, height: int, radius: int) -> bool:
    """约束系统模糊区域，避免圆角外出现矩形磨砂底；成功后区域归系统管理。"""
    region = _gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius * 2, radius * 2)
    if not region:
        return False
    if not _user32.SetWindowRgn(hwnd, region, True):
        _gdi32.DeleteObject(region)
        return False
    return True


def enable_blur(hwnd: int, width: int, height: int, radius: int) -> bool:
    """使用系统合成器模糊背后窗口；不可用时保留普通分层绘制。

    Windows 10 使用非公开但广泛采用的 ACCENT_ENABLE_BLURBEHIND；
    不依赖 Windows 11 专属背景 API，不捕获或保存桌面内容。
    """
    if sys.getwindowsversion().major < 10 or _set_composition is None:
        return False
    if _user32.GetSystemMetrics(0x1000):  # SM_REMOTESESSION
        return False
    contrast = _HighContrast(ctypes.sizeof(_HighContrast), 0, None)
    if not _user32.SystemParametersInfoW(0x42, contrast.size, ctypes.byref(contrast), 0):
        return False
    if contrast.flags & 1:  # HCF_HIGHCONTRASTON
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            if not winreg.QueryValueEx(key, "EnableTransparency")[0]:
                return False
    except OSError:
        pass  # 未设置时采用系统默认开启
    if not _accent(hwnd, 3):  # ACCENT_ENABLE_BLURBEHIND
        return False
    if not resize_blur(hwnd, width, height, radius):
        disable_blur(hwnd)
        return False
    return True


def disable_blur(hwnd: int) -> None:
    """回退前清除背景效果和区域；正常销毁窗口时系统自动释放它们。"""
    _accent(hwnd, 0)
    _user32.SetWindowRgn(hwnd, None, True)


def disable(hwnd: int) -> None:
    """退出 ULW，允许 Tk 的 SetLayeredWindowAttributes 回退路径重新初始化。"""
    disable_blur(hwnd)
    ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)


def enable(hwnd: int) -> None:
    """给窗口加 WS_EX_LAYERED 扩展样式。"""
    ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)


def window_handle(tk_id: int) -> int:
    """取得 Tk 外层原生窗口，明确使用指针宽度的 HWND 签名。"""
    return _user32.GetParent(tk_id) or tk_id


def no_activate(hwnd: int) -> None:
    """悬浮控件不抢走输入窗口焦点，不在任务栏生成独立按钮。"""
    ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | 0x08000000 | 0x80)


def place_behind(hwnd: int, foreground_hwnd: int, x: int, y: int, w: int, h: int) -> None:
    _user32.SetWindowPos(hwnd, foreground_hwnd, x, y, w, h, 0x0010)  # SWP_NOACTIVATE


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
    if not hdc_screen:
        return False
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    if not hdc_mem:
        _user32.ReleaseDC(None, hdc_screen)
        return False
    hbmp = None
    prev = None
    try:
        ptr = ctypes.c_void_p()
        bmi = BITMAPINFOHEADER(w, h)
        hbmp = _gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(ptr), None, 0)
        if not hbmp or not ptr:
            return False
        ctypes.memmove(ptr, raw, len(raw))
        prev = _gdi32.SelectObject(hdc_mem, hbmp)
        if not prev or prev == ctypes.c_void_p(-1).value:
            prev = None
            return False
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        dst = POINT(x, y)
        size = SIZE(w, h)
        src = POINT(0, 0)
        return bool(_user32.UpdateLayeredWindow(
            hwnd, hdc_screen, ctypes.byref(dst), ctypes.byref(size),
            hdc_mem, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
        ))
    finally:
        if prev:
            _gdi32.SelectObject(hdc_mem, prev)
        if hbmp:
            _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(hdc_mem)
        _user32.ReleaseDC(None, hdc_screen)

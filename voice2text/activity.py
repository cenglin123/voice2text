"""观察物理编辑动作，发现光标位置可能改变时关闭本次写入，不拦截用户输入。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import keyboard

_user = ctypes.WinDLL("user32", use_last_error=True)
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_Hook = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user.SetWindowsHookExW.argtypes = [ctypes.c_int, _Hook, wintypes.HINSTANCE, wintypes.DWORD]
_user.SetWindowsHookExW.restype = wintypes.HANDLE
_user.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_user.CallNextHookEx.restype = ctypes.c_ssize_t
_user.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
_user.WindowFromPoint.argtypes = [wintypes.POINT]
_user.WindowFromPoint.restype = wintypes.HWND
_user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user.GetAncestor.restype = wintypes.HWND
_user.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user.GetAsyncKeyState.restype = ctypes.c_short
_user.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_user.MapVirtualKeyW.restype = wintypes.UINT
_kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel.GetModuleHandleW.restype = wintypes.HMODULE


class _Key(ctypes.Structure):
    _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD),
               ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


class _Mouse(ctypes.Structure):
    _fields_ = [("point", wintypes.POINT), ("data", wintypes.DWORD), ("flags", wintypes.DWORD),
               ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


def _pressed(vk: int) -> bool:
    return bool(_user.GetAsyncKeyState(vk) & 0x8000)


class InputActivityGuard:
    """在 Tk 主线程安装钩子，回调只做本地标记，无 COM、等待或注入。"""
    def __init__(self, inserter, combo: str) -> None:
        self.inserter = inserter
        steps = keyboard.parse_hotkey(combo)
        self._hotkey_groups = [{_user.MapVirtualKeyW(scan, 3) for scan in group} for group in steps[0]]
        self._down = {vk for group in self._hotkey_groups for vk in group if _pressed(vk)}
        self._hotkey_armed: set[int] = set()
        self._callbacks = [_Hook(self._key), _Hook(self._mouse)]
        self._handles = []
        try:
            for kind, callback in zip((13, 14), self._callbacks):
                handle = _user.SetWindowsHookExW(kind, callback, _kernel.GetModuleHandleW(None), 0)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                self._handles.append(handle)
        except Exception:
            self.close()
            raise

    def _key(self, code, message, pointer):
        if code >= 0 and message in (0x100, 0x104, 0x101, 0x105):
            event = ctypes.cast(pointer, ctypes.POINTER(_Key)).contents
            if not event.flags & 0x10:
                if message in (0x101, 0x105):
                    self._down.discard(event.vk)
                    self._hotkey_armed.discard(event.vk)
                else:
                    self._down.add(event.vk)
        if code >= 0 and message in (0x100, 0x104) and self.inserter._session_open:
            key = ctypes.cast(pointer, ctypes.POINTER(_Key)).contents
            # 注入文本/退格、修饰键、配置热键和 Alt+Tab 不改变目标内插入位置。
            modifiers = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
            switching = key.vk == 9 and _pressed(0x12)
            if not key.flags & 0x10 and key.vk not in modifiers and not switching:
                # 热键的普通键仅在修饰键按下时豁免，单独输入 v 仍须停止。
                hotkey = self._is_hotkey(key.vk)
                if not hotkey:
                    self.inserter.abort("检测到手动键盘编辑，已停止上屏以保留当前内容")
        return _user.CallNextHookEx(None, code, message, pointer)

    def _is_hotkey(self, vk: int) -> bool:
        armed = getattr(self, "_hotkey_armed", set())
        if vk in armed:
            return True
        matched = any(vk in group for group in self._hotkey_groups) and all(
            vk in group or any(candidate in self._down for candidate in group)
            for group in self._hotkey_groups
        )
        if matched:
            armed.add(vk)
            self._hotkey_armed = armed
        return matched

    def _mouse(self, code, message, pointer):
        target = self.inserter._target
        if code >= 0 and message in (0x201, 0x204, 0x207, 0x20A) and self.inserter._session_open and target:
            event = ctypes.cast(pointer, ctypes.POINTER(_Mouse)).contents
            if not event.flags & 1:
                hwnd = _user.WindowFromPoint(event.point)
                if _user.GetAncestor(hwnd, 2) == target.hwnd:
                    self.inserter.abort("检测到原窗口内鼠标操作，已停止上屏以避免修改其他位置")
        return _user.CallNextHookEx(None, code, message, pointer)

    def close(self) -> None:
        for handle in self._handles:
            _user.UnhookWindowsHookEx(handle)
        self._handles.clear()

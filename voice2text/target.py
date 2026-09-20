"""会话输入目标：保存纯身份数据，每个线程重新查询 UIA，不共享 COM 对象。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import time

import uiautomation as auto

_user = ctypes.WinDLL("user32", use_last_error=True)
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)


class _GUIInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("active", wintypes.HWND), ("focus", wintypes.HWND),
                ("capture", wintypes.HWND), ("menu", wintypes.HWND),
                ("move", wintypes.HWND), ("caret", wintypes.HWND), ("rect", wintypes.RECT)]


_user.GetForegroundWindow.restype = wintypes.HWND
_user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user.GetWindowThreadProcessId.restype = wintypes.DWORD
_user.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUIInfo)]
_user.GetGUIThreadInfo.restype = wintypes.BOOL
_user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user.IsWindow.argtypes = [wintypes.HWND]
_user.IsWindow.restype = wintypes.BOOL
_user.IsIconic.argtypes = [wintypes.HWND]
_user.SetForegroundWindow.argtypes = [wintypes.HWND]
_user.SetForegroundWindow.restype = wintypes.BOOL
_user.SetFocus.argtypes = [wintypes.HWND]
_user.SetFocus.restype = wintypes.HWND
_user.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user.AttachThreadInput.restype = wintypes.BOOL
_user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user.GetAncestor.restype = wintypes.HWND
_kernel.GetCurrentThreadId.restype = wintypes.DWORD
_kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel.OpenProcess.restype = wintypes.HANDLE
_kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_kernel.CloseHandle.argtypes = [wintypes.HANDLE]

_TERMINALS = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "VirtualConsoleClass"}
_NATIVE_FOCUS_APPS = {"wps", "et", "wpp"}
# Chromium/WebView 输入框会在页面更新时重建 UIA 节点，RuntimeId 不能作为
# 会话期间的稳定身份。开始时仍必须通过 UIA 可编辑校验；之后锁原生窗口和
# 焦点 HWND，并由 InputActivityGuard 监测用户主动切换。
_VOLATILE_UIA = {
    ("chatgpt", "Chrome_WidgetWin_1"),
    ("weixin", "Chrome_WidgetWin_1"),
}


def foreground() -> int:
    return _user.GetForegroundWindow() or 0


def _identity(hwnd: int) -> tuple[int, int]:
    pid = wintypes.DWORD()
    tid = _user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return tid, pid.value


def _class(hwnd: int) -> str:
    value = ctypes.create_unicode_buffer(256)
    _user.GetClassNameW(hwnd, value, len(value))
    return value.value


def _focus(tid: int) -> int:
    info = _GUIInfo(size=ctypes.sizeof(_GUIInfo))
    if not _user.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return 0
    return info.focus or 0


def _process_name(pid: int) -> str:
    handle = _kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        value = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(value))
        if _kernel.QueryFullProcessImageNameW(handle, 0, value, ctypes.byref(size)):
            return os.path.basename(value.value).lower().removesuffix(".exe")
        return ""
    finally:
        _kernel.CloseHandle(handle)


@dataclass(frozen=True)
class InputTarget:
    hwnd: int
    pid: int
    tid: int
    focus_hwnd: int
    runtime_id: tuple[int, ...]
    terminal: bool
    process: str

    @classmethod
    def capture(cls, blacklist: set[str]) -> "InputTarget":
        """只在用户发起开始请求时捕获；不把本程序或未知焦点当作目标。"""
        hwnd = foreground()
        tid, pid = _identity(hwnd)
        if not hwnd or not tid or pid == os.getpid():
            raise RuntimeError("请先将光标放入要听写的输入框，再按快捷键开始")
        process = _process_name(pid)
        if not process or process in blacklist:
            raise RuntimeError("目标进程无法验证或已被禁止输入")
        focus = _focus(tid)
        if not focus:
            raise RuntimeError("无法确定目标输入控件")
        window_class = _class(hwnd)
        terminal = window_class in _TERMINALS
        native_focus = terminal or process in _NATIVE_FOCUS_APPS
        volatile_uia = (process, window_class) in _VOLATILE_UIA
        runtime_id = ()
        try:
            ctrl = auto.GetFocusedControl()
            if ctrl is None:
                if not native_focus:
                    raise RuntimeError("无法读取目标输入控件")
            else:
                runtime_id = tuple(ctrl.GetRuntimeId() or ())
                if native_focus:
                    # TUI 和 WPS 编辑区使用动态/自绘控件，UIA 身份不可作为稳定依据。
                    runtime_id = ()
            if not native_focus:
                editable = ctrl.ControlTypeName in {"EditControl", "DocumentControl"}
                value = ctrl.GetValuePattern()
                if value is not None:
                    editable = not value.IsReadOnly
                if not editable or not runtime_id:
                    raise RuntimeError("当前控件不可编辑，请将光标放入输入框")
                # ChatGPT、微信桌面端会在流式文本更新时重建 WebView UIA 节点，
                # RuntimeId 随之变化，但原生焦点 HWND 保持不变。物理鼠标/键盘
                # 切换另由 InputActivityGuard 立即关闸，因此会话内可安全使用
                # 稳定原生身份。
                if volatile_uia:
                    runtime_id = ()
        except Exception as exc:
            if not native_focus:
                raise RuntimeError("无法验证目标输入控件，听写未开始") from exc
            runtime_id = ()
        if foreground() != hwnd or _focus(tid) != focus:
            raise RuntimeError("开始时焦点发生变化，请重新开始")
        return cls(hwnd, pid, tid, focus, runtime_id, terminal, process)

    def valid(self) -> bool:
        window_valid = bool(_user.IsWindow(self.hwnd) and _identity(self.hwnd) == (self.tid, self.pid))
        if self.process in _NATIVE_FOCUS_APPS:
            return window_valid
        return bool(window_valid and _user.IsWindow(self.focus_hwnd)
                    and _identity(self.focus_hwnd) == (self.tid, self.pid))

    def focused(self, check_control: bool = True) -> bool:
        """每批输入检查原生焦点；每次事务另核对 UIA 控件身份。"""
        if not self.valid() or foreground() != self.hwnd:
            return False
        current_focus = _focus(self.tid)
        if self.process in _NATIVE_FOCUS_APPS:
            return bool(current_focus and _identity(current_focus)[1] == self.pid)
        if current_focus != self.focus_hwnd:
            return False
        if check_control and self.runtime_id:
            try:
                ctrl = auto.GetFocusedControl()
                return ctrl is not None and tuple(ctrl.GetRuntimeId() or ()) == self.runtime_id
            except Exception:
                return False
        return True

    def restore(self) -> bool:
        """短暂连接输入队列恢复前台与原控件，任何失败都不得盲写。"""
        if self.focused():
            return True
        if not self.valid():
            return False
        # 同一前台下换了控件/终端页签，不能猜测位置或重新选中任意文本。
        if foreground() == self.hwnd:
            return False
        current_tid = _kernel.GetCurrentThreadId()
        active_tid, _ = _identity(foreground())
        attached = []
        try:
            for tid in {active_tid, self.tid} - {0, current_tid}:
                if _user.AttachThreadInput(current_tid, tid, True):
                    attached.append(tid)
            if _user.IsIconic(self.hwnd):
                _user.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            _user.SetForegroundWindow(self.hwnd)
            _user.SetFocus(self.focus_hwnd)
        finally:
            for tid in attached:
                _user.AttachThreadInput(current_tid, tid, False)
        for _ in range(5):
            if self.focused():
                return True
            time.sleep(0.01)
        return False

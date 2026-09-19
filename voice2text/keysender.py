"""键盘事件注入：SendInput 直发 Unicode 字符（VK_PACKET），不经剪贴板。

为什么不用剪贴板 + Ctrl+V（历史方案）：Windows 剪贴板历史（Win+V）会积累
每一次 partial 刷新的文本（用户实测截图），且与用户自己的剪贴板存在
保存/恢复竞态。VK_PACKET 字符事件绕过输入法直接插入文本，是 KeePass 等
自动输入工具的标准做法。

兼容性兜底：个别应用不认 VK_PACKET 字符（罕见），config.input_clipboard=true
可回退剪贴板粘贴路径。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK = 0x08

_GROUP_EVENTS = 16  # 每批发送的事件数
_GROUP_DELAY_S = 0.004  # 批间间隔：给慢应用的消息循环喘息，防事件乱序被 IME 拆散

PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


def _char_down_up(code: int) -> list[INPUT]:
    """一个 Unicode 码元的按下+抬起事件对（wVk=0, wScan=码元）。"""
    down = INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)))
    up = INPUT(
        type=INPUT_KEYBOARD,
        u=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)),
    )
    return [down, up]


def _build_char_inputs(text: str) -> list[INPUT]:
    """文本 → 事件序列。BMP 外字符（emoji 等）拆成 UTF-16 代理对逐码元发送。"""
    events: list[INPUT] = []
    for ch in text:
        encoded = ch.encode("utf-16-le")
        for i in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[i : i + 2], "little")
            events.extend(_char_down_up(unit))
    return events


def _build_backspace_inputs(n: int) -> list[INPUT]:
    events: list[INPUT] = []
    for _ in range(n):
        down = INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(VK_BACK, 0, 0, 0, None)))
        up = INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(VK_BACK, 0, KEYEVENTF_KEYUP, 0, None)))
        events.extend([down, up])
    return events


def _flush(events: list[INPUT], guard=None) -> None:
    """分批 SendInput：批内一次系统调用（原子、保序），批间留间隔。"""
    user32 = ctypes.windll.user32
    for i in range(0, len(events), _GROUP_EVENTS):
        group = events[i : i + _GROUP_EVENTS]
        arr = (INPUT * len(group))(*group)
        if guard is not None:
            guard()
        sent = user32.SendInput(len(group), arr, ctypes.sizeof(INPUT))
        if sent != len(group):
            raise OSError(f"SendInput 只注入了 {sent}/{len(group)} 个事件")
        if i + _GROUP_EVENTS < len(events):
            time.sleep(_GROUP_DELAY_S)


def send_text(text: str, guard=None) -> None:
    """在当前光标处插入文本（不经剪贴板，绕过输入法直接上屏）。"""
    if not text:
        return
    _flush(_build_char_inputs(text), guard)


def send_backspaces(n: int, guard=None) -> None:
    """发送 n 个退格。"""
    if n <= 0:
        return
    _flush(_build_backspace_inputs(n), guard)

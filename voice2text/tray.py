"""系统托盘图标；右键菜单由主线程中的自绘窗口呈现。

菜单：开始/停止听写（动态）、显示/隐藏悬浮窗（动态）、设置、使用帮助、退出。
动作通过 cmd_queue 投递给主线程执行（pystray 回调在自有线程）。
图标随状态更新（trayicon 四状态）。
"""

from __future__ import annotations

import queue

import ctypes
from ctypes import wintypes

from pystray._win32 import Icon as Win32Icon
from pystray._util import win32

from voice2text import trayicon


def toggle_label(app) -> str:
    return f"{'停止' if app.active else '开始'}听写（{app.hotkey.combo}）"


class StyledTrayIcon(Win32Icon):
    """保留 pystray 的图标生命周期，将右键位置交给自绘菜单。"""

    def __init__(self, *args, cmd_queue, **kwargs):
        self._cmd_queue = cmd_queue
        super().__init__(*args, **kwargs)

    def _on_notify(self, wparam, lparam):
        if lparam == win32.WM_LBUTTONUP:
            self._cmd_queue.put(("toggle", None))
        elif lparam == win32.WM_RBUTTONUP:
            point = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            self._cmd_queue.put(("tray_menu", (point.x, point.y)))


def build_tray(cmd_queue: "queue.Queue[tuple]", app, hotkey: str = "alt+v") -> StyledTrayIcon:
    """左键切换听写，右键请求主线程显示自绘菜单。"""
    icon = StyledTrayIcon("voice2text", trayicon.draw_icon("idle"),
                          f"voice2text 语音输入（{hotkey}）", menu=None,
                          cmd_queue=cmd_queue)
    return icon


def refresh_menu(icon: StyledTrayIcon) -> None:
    """动态菜单文案变化后调用（pystray 不自动重估 callable）。"""
    try:
        icon.update_menu()
    except Exception:  # noqa: BLE001 —— 托盘异常不影响听写
        pass


def update_icon(icon: StyledTrayIcon, state: str) -> None:
    """状态 → 图标：listening/recording 都算录音态（红），proofreading 蓝色声波，loading 待命白。"""
    mapping = {
        "idle": "idle",
        "loading": "idle",
        "listening": "recording",
        "proofreading": "listening",
        "error": "error",
    }
    icon.icon = trayicon.draw_icon(mapping.get(state, "idle"))

"""系统托盘（pystray，美术稿 assets/托盘菜单.jpg）。

菜单：开始/停止听写（动态）、显示/隐藏悬浮窗（动态）、设置、使用帮助、退出。
动作通过 cmd_queue 投递给主线程执行（pystray 回调在自有线程）。
图标随状态更新（trayicon 四状态）。
"""

from __future__ import annotations

import queue

import pystray

from voice2text import trayicon


def build_tray(cmd_queue: "queue.Queue[tuple]", app, hotkey: str = "alt+v") -> pystray.Icon:
    """app 需提供 active / widget_visible 属性（动态文案）。"""

    def _put(kind: str):
        def _action(icon, item):
            cmd_queue.put((kind, None))

        return _action

    menu = pystray.Menu(
        pystray.MenuItem(
            lambda item: "停止听写" if app.active else "开始听写",
            _put("toggle"),
            default=True,
        ),
        pystray.MenuItem(
            lambda item: "隐藏悬浮窗" if app.widget_visible else "显示悬浮窗",
            _put("toggle_widget"),
        ),
        pystray.MenuItem("设置", _put("settings")),
        pystray.MenuItem("使用帮助", _put("help")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _put("quit")),
    )

    icon = pystray.Icon("voice2text", trayicon.draw_icon("idle"), f"voice2text 语音输入（{hotkey}）", menu)
    return icon


def update_icon(icon: pystray.Icon, state: str) -> None:
    """状态 → 图标：listening/recording 都算录音态（红），proofreading 蓝色声波，loading 待命白。"""
    mapping = {
        "idle": "idle",
        "loading": "idle",
        "listening": "recording",
        "proofreading": "listening",
        "error": "error",
    }
    icon.icon = trayicon.draw_icon(mapping.get(state, "idle"))

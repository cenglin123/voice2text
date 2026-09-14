"""全局热键监听：Alt+V 切换听写状态。

keyboard 库在 Windows 普通用户权限即可安装低级键盘钩子；唯一限制是 UIPI——
焦点位于管理员权限窗口时收不到按键（见 docs/pitfalls.md），因此启动时做一次可达性自检，
不做默认提权。
热键回调运行在 keyboard 库的监听线程里，只设置 Event，不做任何耗时工作。
"""

from __future__ import annotations

import threading

import keyboard  # type: ignore[import-untyped]


class HotkeyListener:
    """全局热键监听器。

    通过 toggle_event 向主线程传递切换信号；last_press 用于启动自检时确认按键可达。
    """

    def __init__(self, combo: str = "alt+v") -> None:
        self._combo = combo
        self._toggle_event = threading.Event()
        self._last_press = threading.Event()
        self._hook = keyboard.add_hotkey(combo, self._on_hotkey, suppress=False)

    def _on_hotkey(self) -> None:
        self._last_press.set()
        self._toggle_event.set()

    @property
    def toggle_event(self) -> threading.Event:
        return self._toggle_event

    def self_check(self, timeout: float = 10.0) -> bool:
        """启动可达性自检：引导用户按一次热键。

        自检按键只确认可达性，不触发听写切换（toggle 信号会被清除）。
        超时则提示可能原因，程序继续运行等待。
        """
        print(f"请按一次 [{self._combo}] 确认热键可用（最多等待 {timeout:.0f} 秒）...")
        got = self._last_press.wait(timeout)
        if got:
            print("  热键可用")
            self._toggle_event.clear()
        else:
            print("  [警告] 未收到热键。可能原因：焦点在管理员权限窗口、热键被其他程序占用、")
            print("         或程序缺少权限。可尝试以管理员身份运行。程序继续等待按键。")
        return got

    def wait_toggle(self, timeout: float | None = None) -> bool:
        """阻塞等待切换信号。返回是否等到（False 表示超时）。"""
        return self._toggle_event.wait(timeout)

    def clear_toggle(self) -> None:
        self._toggle_event.clear()

    def shutdown(self) -> None:
        try:
            keyboard.remove_hotkey(self._hook)
        except (KeyError, ValueError):
            pass  # 进程退出时钩子可能已被清理

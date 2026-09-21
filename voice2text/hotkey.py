"""全局热键监听：Alt+V 切换听写状态。

keyboard 库在 Windows 普通用户权限即可安装低级键盘钩子；唯一限制是 UIPI——
焦点位于管理员权限窗口时收不到按键（见 docs/pitfalls.md），因此启动时做一次可达性自检，
不做默认提权。
热键回调运行在 keyboard 库的监听线程里，只设置 Event，不做任何耗时工作。
"""

from __future__ import annotations

import ctypes
import threading
from time import perf_counter_ns

import keyboard  # type: ignore[import-untyped]

_user = ctypes.WinDLL("user32", use_last_error=True)
_VK_MENU = 0x12
_VK_LMENU = 0xA4
_VK_RMENU = 0xA5
_KEYEVENTF_KEYUP = 0x0002


def _pressed(vk: int) -> bool:
    return bool(_user.GetAsyncKeyState(vk) & 0x8000)


def _release_latched_alt() -> None:
    """为 suppress 热键补齐偶发漏掉的 Alt key-up。

    回调由 keyboard 的监听线程发出，而主线程最多 150ms 后才会处理切换；此时
    正常按键已松开，本函数不产生事件。若 Windows 仍报告 Alt 被按住，则发送
    对应 key-up，避免菜单栏/其他程序把后续键当作 Alt 组合键。
    """
    keys = [vk for vk in (_VK_LMENU, _VK_RMENU) if _pressed(vk)]
    if not keys and _pressed(_VK_MENU):
        keys = [_VK_MENU]
    for vk in keys:
        _user.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


class HotkeyListener:
    """全局热键监听器。

    通过 toggle_event 向主线程传递切换信号；last_press 用于启动自检时确认按键可达。
    """

    def __init__(self, combo: str = "alt+v") -> None:
        self._combo = combo
        self._toggle_event = threading.Event()
        self._last_press = threading.Event()
        self._last_trigger_ns = 0
        # suppress=True：吞掉 Alt+V，不再透传给焦点应用。中文输入法激活时，
        # 透传的 v 会进入拼音组合框并弹出 v 模式面板（实测 bug），必须拦截。
        self._hook = keyboard.add_hotkey(
            combo, self._on_hotkey, suppress=True, trigger_on_release=True
        )

    def _on_hotkey(self) -> None:
        self._last_trigger_ns = perf_counter_ns()
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

    def clear_toggle(self) -> float:
        """清除切换事件并返回从热键释放到主线程处理的毫秒数。"""
        self._toggle_event.clear()
        _release_latched_alt()
        triggered = getattr(self, "_last_trigger_ns", 0)
        return (perf_counter_ns() - triggered) / 1_000_000 if triggered else 0.0

    def rebind(self, combo: str) -> None:
        """更换热键组合（设置窗口保存时调用）。失败时抛异常由调用方提示。"""
        old = self._hook
        self._hook = keyboard.add_hotkey(
            combo, self._on_hotkey, suppress=True, trigger_on_release=True
        )
        self._combo = combo
        try:
            keyboard.remove_hotkey(old)
        except (KeyError, ValueError):
            pass

    @property
    def combo(self) -> str:
        return self._combo

    def shutdown(self) -> None:
        try:
            keyboard.remove_hotkey(self._hook)
        except (KeyError, ValueError):
            pass  # 进程退出时钩子可能已被清理

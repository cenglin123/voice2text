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
        self._hook = self._register_blocking_hotkey(combo)

    def _register_blocking_hotkey(self, combo: str):
        """阻断组合键主键的 down/up，并在主键松开时只触发一次。

        keyboard.add_hotkey 的 trigger_on_release 抑制依赖库内修饰键重放状态机；
        Windows Terminal 真机可收到漏出的 v / Ctrl+X。这里独立跟踪物理扫描码，
        修饰键照常通过，只有完整组合中的主键被吞掉。
        """
        steps = keyboard.parse_hotkey_combinations(combo)
        if len(steps) != 1:
            raise ValueError("快捷键只支持单组按键组合")
        combinations = tuple(frozenset(codes) for codes in steps[0])
        main_by_combination = {
            codes: frozenset(code for code in codes if not keyboard.is_modifier(code))
            for codes in combinations
        }
        if not combinations or any(len(main) != 1 for main in main_by_combination.values()):
            raise ValueError("快捷键必须包含一个非修饰键")

        down: set[int] = set()
        armed: set[int] = set()

        def block(event) -> bool:
            scan_code = int(event.scan_code)
            if event.event_type == keyboard.KEY_DOWN:
                # 完整组合命中后，即使用户先松开修饰键，主键的自动重复
                # 仍必须持续吞掉，直到主键 keyup 才解除 armed。
                if scan_code in armed:
                    return False
                down.add(scan_code)
                matched_main = any(
                    codes.issubset(down) and scan_code in main_by_combination[codes]
                    for codes in combinations
                )
                if matched_main:
                    armed.add(scan_code)
                    return False
                return True

            was_armed = scan_code in armed
            down.discard(scan_code)
            if was_armed:
                armed.discard(scan_code)
                self._on_hotkey()
                return False
            return True

        return keyboard.hook(block, suppress=True)

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
        self._hook = self._register_blocking_hotkey(combo)
        self._combo = combo
        try:
            old()
        except (KeyError, ValueError, TypeError):
            pass

    @property
    def combo(self) -> str:
        return self._combo

    def shutdown(self) -> None:
        try:
            self._hook()
        except (KeyError, ValueError, TypeError):
            pass  # 进程退出时钩子可能已被清理

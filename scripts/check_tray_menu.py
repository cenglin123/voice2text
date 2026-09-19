"""自绘托盘菜单验证，不启动托盘图标或听写模型。"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tkinter
import time
import queue
from types import SimpleNamespace

from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text.tray_menu import PAD, TOP_H, ROW_H, TrayMenu
from voice2text.tray import build_tray


def post_click(hwnd: int, x: int, y: int, root) -> None:
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    point = wintypes.POINT(rect.left + x, rect.top + y)
    target = ctypes.windll.user32.WindowFromPoint(point)
    assert ctypes.windll.user32.GetAncestor(target, 2) == hwnd
    old = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(old))
    ctypes.windll.user32.SetCursorPos(point.x, point.y)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    root.after(80, root.quit)
    root.mainloop()
    ctypes.windll.user32.SetCursorPos(old.x, old.y)
    return target, (rect.left, rect.top, rect.right, rect.bottom), root.winfo_id()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--screen-capture", type=Path)
    parser.add_argument("--tray-lifecycle", action="store_true")
    parser.add_argument("--physical-click", action="store_true")
    args = parser.parse_args()
    root = tkinter.Tk()
    root.withdraw()
    calls = []
    app = SimpleNamespace(active=False, widget_visible=True,
                          hotkey=SimpleNamespace(combo="alt+v"))
    menu = TrayMenu(root, app, calls.append)
    try:
        menu.show(900, 760)
        root.update()
        assert menu.visible
        assert menu._row_at(PAD + TOP_H // 2) == 0
        assert menu._row_at(PAD + TOP_H + ROW_H * 2 + 4) == 3
        assert menu._last_image.getpixel((0, 0))[3] == 0
        if args.capture:
            args.capture.parent.mkdir(parents=True, exist_ok=True)
            menu._last_image.save(args.capture)
        if args.screen_capture:
            args.screen_capture.parent.mkdir(parents=True, exist_ok=True)
            root.after(250, root.quit)
            root.mainloop()
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(menu.hwnd, ctypes.byref(rect))
            ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).save(args.screen_capture)
        if args.physical_click:
            debug = post_click(menu.hwnd, 120, PAD + TOP_H // 2, root)
        else:
            debug = None
            menu._click(SimpleNamespace(y=PAD + TOP_H // 2))
        assert calls == ["toggle"] and not menu.visible, (calls, debug, menu.hwnd)
        app.active = True
        menu.show(900, 760)
        root.update()
        # 第二次打开验证动态文案和命令映射；一次真实 Win32 点击已覆盖 NOACTIVATE 路由。
        menu._click(SimpleNamespace(y=PAD + TOP_H + ROW_H * 4 + 5))
        assert calls[-1] == "quit"
    finally:
        menu.root.destroy()
        root.destroy()
    if args.tray_lifecycle:
        commands = queue.Queue()
        icon = build_tray(commands, app)
        icon.run_detached()
        deadline = time.monotonic() + 5
        while not icon._running and time.monotonic() < deadline:
            time.sleep(0.01)
        if not icon._running:
            icon._Icon__queue.put(False)
            icon._setup_thread.join(timeout=1)
            raise AssertionError(("tray did not become ready", icon._hwnd,
                                  getattr(icon, "_thread", None)))
        deadline = time.monotonic() + 2
        while not icon.visible and time.monotonic() < deadline:
            time.sleep(0.01)
        assert icon.visible
        icon.stop()
        icon._thread.join(timeout=2)
        assert not icon._thread.is_alive() and not icon._running
    print("PASS custom tray menu layout, alpha corners, hit rows and dynamic action")


if __name__ == "__main__":
    main()

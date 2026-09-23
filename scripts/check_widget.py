"""Windows 悬浮窗验证，不加载音频、热键或模型，不改配置。

用法：python scripts/check_widget.py [--capture-dir 临时目录]
截图模式需在交互式桌面运行；只截取本脚本创建的测试背景。
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tkinter
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab
from voice2text import layered
from voice2text.widget import DictationWidget


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path)
    args = parser.parse_args()
    failures = []
    calls = []
    widget = DictationWidget(on_toggle=lambda: calls.append("toggle"),
                             on_settings=lambda: calls.append("settings"),
                             on_hide=lambda: calls.append("hide"))
    widget.root.report_callback_exception = lambda *exc: failures.append(exc)
    try:
        for scale in (0.5, 1.0, 1.5):
            widget.apply_appearance(scale, 0.72)
            widget.root.update()
            for state in ("idle", "loading", "listening", "proofreading", "error"):
                widget.set_state(state)
                frame = widget.snapshot()
                assert frame.size == (round(340 * scale), round(104 * scale))
                assert frame.getpixel((0, 0))[3] == 0
                for name, (x, y, _) in widget._hits.items():
                    assert 0 <= x < frame.width and 0 <= y < frame.height
                    assert widget._hit(x, y) == name
        for key, result in (("gear", "settings"), ("close", "hide"), ("mic", "toggle")):
            x, y, _ = widget._hits[key]
            event = SimpleNamespace(x=x, y=y)
            widget._on_press(event)
            widget._on_release(event)
            assert calls[-1] == result
        widget.set_state("error")
        self_reset_job = widget._error_reset_job
        assert self_reset_job is not None
        widget.set_state("loading")
        assert widget._error_reset_job is None
        widget.set_state("error")
        widget._reset_error()
        assert widget.state == "idle"
        # 拖动必须经过同一透明度处理路径，且释放时不触发听写。
        with patch.object(layered, "update", wraps=layered.update) as update:
            before = len(calls)
            origin = (widget.root.winfo_x(), widget.root.winfo_y())
            widget._on_press(SimpleNamespace(x=100, y=20))
            widget._on_motion(SimpleNamespace(x=120, y=30))
            # Tk 事件坐标相对于已移动窗口；下一次再移动 2px 时 x=102。
            widget._on_motion(SimpleNamespace(x=102, y=20))
            widget._on_release(SimpleNamespace(x=120, y=30))
            widget.root.update()
            assert len(calls) == before
            assert (widget.root.winfo_x(), widget.root.winfo_y()) == (origin[0] + 22, origin[1] + 10)
            if widget._layered:
                assert update.call_count
                image = update.call_args.args[1]
                assert image.getchannel("A").getextrema()[1] <= widget._opacity_pct
        widget.hide()
        widget.root.update()
        assert not widget.root.winfo_viewable()
        widget.show()
        widget.root.update()
        assert widget.root.winfo_viewable()

        # 右下角拖动会同时更新缩放和长宽比，并在释放时同步给配置层。
        resized = []
        widget._on_resize = lambda scale, aspect: resized.append((scale, aspect))
        widget.apply_appearance(1.0, 0.92, 340 / 104)
        widget._on_press(SimpleNamespace(x=widget._w - 2, y=widget._h - 2,
                                         x_root=500, y_root=500))
        widget._on_motion(SimpleNamespace(x=widget._w - 2, y=widget._h - 2,
                                          x_root=560, y_root=520))
        widget._on_release(SimpleNamespace(x=widget._w - 2, y=widget._h - 2))
        assert resized and 0.5 <= resized[-1][0] <= 1.5 and 1.0 <= resized[-1][1] <= 5.0
        assert widget._w == round(widget._h * resized[-1][1])

        # 1:1 使用独立紧凑布局，不能把横向布局直接挤进正方形。
        widget.apply_appearance(1.0, 0.92, 1.0)
        widget.set_state("listening")
        square = widget.snapshot()
        assert square.size == (104, 104)
        assert square.getpixel((0, 0))[3] == 0
        assert len(widget._wave_heights(round(23 * 3))) >= 3
        for name, (x, y, _) in widget._hits.items():
            assert 0 <= x < square.width and 0 <= y < square.height
            assert widget._hit(x, y) == name
        compact_hits = list(widget._hits.items())
        for i, (_, (x1, y1, r1)) in enumerate(compact_hits):
            for _, (x2, y2, r2) in compact_hits[i + 1:]:
                assert (x1 - x2) ** 2 + (y1 - y2) ** 2 >= (r1 + r2) ** 2
        for scale in (0.5, 1.5):
            widget.apply_appearance(scale, 0.92, 1.0)
            assert widget.snapshot().size == (round(104 * scale), round(104 * scale))

        # 单击尺寸手柄不应透传为开始/停止听写。
        before = len(calls)
        widget._on_press(SimpleNamespace(x=widget._w - 2, y=widget._h - 2,
                                         x_root=500, y_root=500))
        widget._on_release(SimpleNamespace(x=widget._w - 2, y=widget._h - 2))
        assert len(calls) == before

        # 持续重绘和重建圆角区域不应积累 GDI 对象。
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        user = ctypes.WinDLL("user32")
        user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        user.GetGuiResources.restype = wintypes.DWORD
        process = kernel.GetCurrentProcess()
        # Tk/Windows 首次处理新尺寸会创建字体等缓存，先完成一轮消息循环。
        for i in range(80):
            widget.apply_appearance(1.0 if i % 2 else 1.5, 0.92)
        widget.root.update()
        count = user.GetGuiResources(process, 0)
        for i in range(80):
            widget.apply_appearance(1.0 if i % 2 else 1.5, 0.92)
            widget._phase += 0.2
            widget._render()
        widget.root.update()
        final_count = user.GetGuiResources(process, 0)
        assert final_count <= count + 2, (count, final_count)
        print(f"PASS states, scales, hit targets, drag opacity, visibility, GDI stability; blur={widget._glass}")

        if args.capture_dir:
            args.capture_dir.mkdir(parents=True, exist_ok=True)
            backdrop = tkinter.Toplevel(widget.root)
            backdrop.overrideredirect(True)
            backdrop.geometry("660x320+60+60")
            canvas = tkinter.Canvas(backdrop, width=660, height=320, bg="#375D8D", highlightthickness=0)
            canvas.pack()
            for x in range(0, 330, 12):
                canvas.create_rectangle(x, 0, x + 6, 320, fill="#F5CA76", outline="")
                canvas.create_rectangle(x + 6, 0, x + 12, 320, fill="#196FAD", outline="")
            canvas.create_text(500, 160, text="Windows\n背景文字", fill="white", font=("Microsoft YaHei UI", -25))
            backdrop.lower(widget.root)
            widget.root.geometry("+200+150")
            widget.apply_appearance(1.0, 0.92)
            widget.root.update()
            for state in ("idle", "listening"):
                widget.set_state(state)
                widget.root.update()
                # 等待 DWM 合成，不触发音频或桌面输入。
                widget.root.after(250, widget.root.quit)
                widget.root.mainloop()
                ImageGrab.grab(bbox=(60, 60, 720, 380)).save(args.capture_dir / f"widget-{state}.png")
            widget.apply_appearance(1.0, 0.92, 1.0)
            widget.set_state("listening")
            widget.root.update()
            widget.root.after(250, widget.root.quit)
            widget.root.mainloop()
            ImageGrab.grab(bbox=(175, 125, 329, 279)).save(args.capture_dir / "widget-square.png")
            backdrop.destroy()

        with patch.object(layered, "update", return_value=False):
            widget._render()
        assert not widget._layered and not widget._glass and widget._fallback_applied
        assert widget.snapshot().getpixel((100, 60))[3] == 255
        widget.apply_appearance(0.5, 0.6)
        widget.set_state("listening")
        widget.root.update()
        assert widget._photo is not None
        assert not failures, failures
        print("PASS injected ULW failure -> opaque Tk fallback; fallback resize and state")
    finally:
        widget.root.destroy()

    with patch.object(layered, "enable_blur", return_value=False):
        widget = DictationWidget()
        try:
            assert not widget._glass
            assert widget.snapshot().getpixel((100, 60))[3] == 255
        finally:
            widget.root.destroy()
    print("PASS unsupported blur -> ordinary layered surface")

    with patch("voice2text.widget.system_scale", return_value=1.5):
        resized = []
        widget = DictationWidget(on_resize=lambda scale, aspect: resized.append((scale, aspect)))
        try:
            assert widget.snapshot().size == (510, 156)
            widget.apply_appearance(1.0, 0.92, 1.0)
            assert widget.snapshot().size == (156, 156)
            widget._on_press(SimpleNamespace(x=widget._w - 2, y=widget._h - 2,
                                             x_root=500, y_root=500))
            widget._on_motion(SimpleNamespace(x=widget._w - 2, y=widget._h - 2,
                                              x_root=530, y_root=515))
            widget._on_release(SimpleNamespace(x=widget._w - 2, y=widget._h - 2))
            assert resized and 1.0 < resized[-1][0] < 1.2
            assert widget._w == round(widget._h * resized[-1][1])
        finally:
            widget.root.destroy()
    print("PASS 150% DPI widget size and drag-to-settings scale")


if __name__ == "__main__":
    main()

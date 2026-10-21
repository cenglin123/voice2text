"""DPI API 回归：真实 HWND、系统倍率差异、旧系统回退与多屏工作区。"""
from pathlib import Path
import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text.dpi import window_scale, window_workarea, enable_dpi_awareness


def main() -> None:
    # HWND 超过 32 位；所在屏幕 200%，系统屏幕 100%。
    hwnd = 0x123456789
    user = SimpleNamespace(GetAncestor=Mock(return_value=hwnd),
                           GetDpiForWindow=Mock(return_value=192),
                           GetDpiForSystem=Mock(return_value=96))
    window = SimpleNamespace(winfo_id=lambda: hwnd,
                             winfo_screenwidth=lambda: 1920,
                             winfo_screenheight=lambda: 1080)
    with patch.object(ctypes, "windll", SimpleNamespace(user32=user)):
        assert window_scale(window) == 2.0
        user.GetDpiForWindow.assert_called_once_with(hwnd)
        assert user.GetDpiForWindow.argtypes == [ctypes.wintypes.HWND]
        del user.GetDpiForWindow
        assert window_scale(window) == 1.0
        user.GetDpiForSystem.return_value = 144
        assert window_scale(window) == 1.5

        def monitor_info(_monitor, pointer):
            pointer._obj.work.left = -2560
            pointer._obj.work.top = 0
            pointer._obj.work.right = 0
            pointer._obj.work.bottom = 1400
            return True

        user.MonitorFromWindow = Mock(return_value=7)
        user.GetMonitorInfoW = Mock(side_effect=monitor_info)
        assert window_workarea(window) == (-2560, 0, 0, 1400)
        user.GetMonitorInfoW.side_effect = None
        user.GetMonitorInfoW.return_value = False
        assert window_workarea(window) == (0, 0, 1920, 1080)

    shcore = SimpleNamespace(SetProcessDpiAwareness=Mock(return_value=0))
    with patch.object(ctypes, "windll", SimpleNamespace(shcore=shcore)):
        enable_dpi_awareness()
        shcore.SetProcessDpiAwareness.assert_called_once_with(2)
    print("PASS per-window DPI, 64-bit HWND, fallback and negative monitor coordinates")


if __name__ == "__main__":
    main()

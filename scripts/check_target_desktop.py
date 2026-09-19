"""交互桌面验证：仅向脚本自建的两个编辑框输入，不加载录音/模型。"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text.target import InputTarget, _user, _identity
from voice2text.input import TextInserter

_user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
_user.CreateWindowExW.restype = wintypes.HWND
_user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
_user.SendMessageW.restype = ctypes.c_ssize_t
_user.DestroyWindow.argtypes = [wintypes.HWND]
_user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def host():
    windows = []
    for index in range(2):
        hwnd = _user.CreateWindowExW(0, "STATIC", "voice2text isolated input test",
            0x10CF0000, 150 + index * 420, 200, 400, 180, None, None, None, None)
        edit = _user.CreateWindowExW(0, "EDIT", "", 0x50800004,
            10, 10, 350, 100, hwnd, None, None, None)
        windows.append([hwnd, edit])
    print(json.dumps(windows), flush=True)
    message = wintypes.MSG()
    while _user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        _user.TranslateMessage(ctypes.byref(message))
        _user.DispatchMessageW(ctypes.byref(message))


def text(hwnd):
    value = ctypes.create_unicode_buffer(4096)
    _user.SendMessageW(hwnd, 0xD, len(value), value)  # WM_GETTEXT，跨进程 EDIT
    return value.value


def main():
    process = subprocess.Popen([sys.executable, __file__, "--host"], stdout=subprocess.PIPE,
        text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        windows = json.loads(process.stdout.readline())
        first, second = windows
        def destination(window):
            tid, pid = _identity(window[0])
            return InputTarget(window[0], pid, tid, window[1], (), False, "python")
        original = destination(first)
        # 刚创建窗口时已有前台但未聚焦 EDIT，先通过另一个测试窗恢复。
        _user.SetForegroundWindow(second[0])
        assert original.restore(), "cannot focus isolated editor"
        locked = InputTarget.capture(set())
        inserter = TextInserter()
        inserter.begin_session(locked)
        assert inserter.replace_current("原窗口测试")
        inserter.commit_current()
        assert destination(second).restore(), "cannot switch to second editor"
        assert inserter.guard_focus(), "original focus not restored"
        assert inserter.replace_committed_range(0, 0, "原窗口测试。")
        time.sleep(0.1)
        assert text(first[1]) == "原窗口测试。", repr(text(first[1]))
        assert text(second[1]) == "", repr(text(second[1]))
        _user.PostMessageW(first[0], 0x10, 0, 0)  # WM_CLOSE，仅本脚本窗口
        time.sleep(0.1)
        assert not inserter.guard_focus()
        assert not inserter.replace_current("不得写入第二个窗口")
        assert text(second[1]) == ""
        print("PASS native Unicode input, focus recovery, proofreading destination, closed target")
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    host() if "--host" in sys.argv else main()

"""托盘常驻的单实例与有界运行输出，不隐藏用户原有的命令行窗口。"""

from __future__ import annotations

from collections import deque
import ctypes
from ctypes import wintypes
import io
import sys
import threading
import tkinter
from tkinter.scrolledtext import ScrolledText


class SingleInstance:
    """会话内只运行一个听写实例，避免重复热键和重复上屏。"""

    def __init__(self) -> None:
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel.CreateMutexW.restype = wintypes.HANDLE
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self._kernel.CreateMutexW(None, False, r"Local\voice2text.desktop.v1")
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.already_running = ctypes.get_last_error() == 183

    def close(self) -> None:
        if self.handle:
            self._kernel.CloseHandle(self.handle)
            self.handle = None


class RuntimeOutput(io.TextIOBase):
    """跨线程输出环形缓冲，仅驻留内存；调试启动时同步到原控制台。"""

    limit = 120_000

    def __init__(self, original=None) -> None:
        self.original = original
        self._chunks = deque()
        self._length = 0
        self._version = 0
        self._lock = threading.Lock()

    @property
    def encoding(self) -> str:
        return "utf-8"

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self._lock:
            chunk = text[-self.limit:]
            self._chunks.append(chunk)
            self._length += len(chunk)
            while self._length > self.limit:
                excess = self._length - self.limit
                head = self._chunks.popleft()
                if len(head) > excess:
                    self._chunks.appendleft(head[excess:])
                    self._length -= excess
                else:
                    self._length -= len(head)
            self._version += 1
        if self.original is not None:
            try:
                self.original.write(text)
            except (OSError, ValueError):
                pass
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            try:
                self.original.flush()
            except (OSError, ValueError):
                pass

    def snapshot(self) -> tuple[int, str]:
        with self._lock:
            return self._version, "".join(self._chunks)


class DebugWindow:
    """右键托盘按需打开，关闭只隐藏，不影响听写服务。"""

    def __init__(self, master, output: RuntimeOutput) -> None:
        self.output = output
        self._version = -1
        self.root = tkinter.Toplevel(master)
        self.root.title("voice2text · 运行输出（调试）")
        self.root.geometry("880x500")
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)
        self.text = ScrolledText(self.root, bg="#151D2A", fg="#DFE7F2",
                                 insertbackground="white", font=("Consolas", 10),
                                 state="disabled", wrap="word")
        self.text.pack(fill="both", expand=True)
        self._poll()

    def _poll(self) -> None:
        if self.root.winfo_viewable():
            version, value = self.output.snapshot()
            if version != self._version:
                at_end = self.text.yview()[1] >= 0.98
                self.text.configure(state="normal")
                self.text.delete("1.0", "end")
                self.text.insert("1.0", value)
                self.text.configure(state="disabled")
                if at_end:
                    self.text.see("end")
                self._version = version
        self.root.after(250, self._poll)

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()


def install_output() -> RuntimeOutput:
    """在模型导入和初始化前安装，pythonw 下也保留 Python 诊断信息。"""
    output = RuntimeOutput(sys.stdout)
    sys.stdout = output
    sys.stderr = output
    return output

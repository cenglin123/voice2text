"""受保护的临时剪贴板文本事务。

临时听写文本通过 Windows 隐私格式排除在剪贴板历史和云同步之外；粘贴完成后，
仅在剪贴板仍由本事务持有时恢复原 IDataObject，避免覆盖用户同时复制的新内容。
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import struct
import time

import pythoncom
import win32clipboard

from voice2text.diagnostics import trace


_ole = ctypes.OleDLL("ole32", use_last_error=True)
_ole.OleInitialize.argtypes = [ctypes.c_void_p]
_ole.OleInitialize.restype = ctypes.c_long
_ole.OleUninitialize.argtypes = []
_ole.OleUninitialize.restype = None


_PRIVACY_FORMATS = {
    "ExcludeClipboardContentFromMonitorProcessing": 1,
    "CanIncludeInClipboardHistory": 0,
    "CanUploadToCloudClipboard": 0,
    "Clipboard Viewer Ignore": 1,
}


def _open(retries: int = 20) -> None:
    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(0.01)


def _publish(text: str) -> int:
    _open()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        for name, value in _PRIVACY_FORMATS.items():
            fmt = win32clipboard.RegisterClipboardFormat(name)
            win32clipboard.SetClipboardData(fmt, struct.pack("<I", value))
    finally:
        win32clipboard.CloseClipboard()
    return win32clipboard.GetClipboardSequenceNumber()


def _empty() -> None:
    _open()
    try:
        win32clipboard.EmptyClipboard()
    finally:
        win32clipboard.CloseClipboard()


def _initialize_ole() -> None:
    result = _ole.OleInitialize(None)
    if result not in (0, 1):  # S_OK / S_FALSE 都必须配对 OleUninitialize
        raise OSError(f"OleInitialize 失败：0x{result & 0xffffffff:08X}")


def _uninitialize_ole() -> None:
    _ole.OleUninitialize()


@contextmanager
def temporary_text(text: str):
    """发布临时文本，并在未发生外部剪贴板更新时恢复原始全部格式。"""
    _initialize_ole()
    original = None
    sequence = None
    try:
        try:
            original = pythoncom.OleGetClipboard()
        except pythoncom.com_error:
            original = None
        sequence = _publish(text)
        yield
    finally:
        try:
            if sequence is not None and win32clipboard.GetClipboardSequenceNumber() == sequence:
                if original is None:
                    _empty()
                else:
                    pythoncom.OleSetClipboard(original)
                    pythoncom.OleFlushClipboard()
        except Exception as exc:
            # 粘贴已经完成，恢复失败不应把屏幕状态误报为注入失败。
            trace("clipboard_restore_failed", detail=str(exc))
        finally:
            _uninitialize_ole()

"""光标处上屏：UIA 可编辑检测 + 剪贴板粘贴 + 已上屏记账。

设计（docs/overview.md「可编辑检测为什么用 UIAutomation」）：
- uiautomation 取焦点控件，ControlType ∈ {Edit, Document} 或 ValuePattern 可写 → 可输入
- 查不到控件（自绘 UI）或 UIA 异常 → 默认放行；config 黑名单按进程名关停
- 中文上屏走剪贴板 + Ctrl+V（模拟键击会被输入法拦截）；MVP 只保存/恢复文本剪贴板
- 记账：_current 跟踪当前句已上屏 partial，整句刷新 = 退格 len(_current) 次 + 粘贴新句
"""

from __future__ import annotations

import re

import keyboard  # type: ignore[import-untyped]
import pyperclip
import uiautomation  # type: ignore[import-untyped]

_EDITABLE_CONTROL_TYPES = {"EditControl", "DocumentControl"}
_ASCII_WORD_TAIL = re.compile(r"[A-Za-z0-9]$")


class TextInserter:
    """负责"光标处写入什么"的唯一记账者——校对替换（阶段 4）也必须经过本类。"""

    def __init__(self, process_blacklist: list[str] | None = None) -> None:
        self._blacklist = {self._norm_process(p) for p in (process_blacklist or [])}
        self._current = ""  # 当前句已上屏的 partial（含句间空格 prefix）
        self._committed = 0  # 已锁句的字符数（阶段 4 校对替换的定位基准）
        self._last_committed_tail = ""  # 上句结尾（决定句间是否补空格）
        self._detached = False  # 本句脱管：焦点离开编辑框后放弃本句剩余 partial，防止重复上屏
        self._saved_clipboard: str | None = None
        self._session_open = False

    @staticmethod
    def _norm_process(name: str) -> str:
        """黑名单进程名归一化：忽略大小写与 .exe 后缀（配置写 notepad 或 notepad.exe 均命中）。"""
        n = name.strip().lower()
        return n[:-4] if n.endswith(".exe") else n

    # ---- 会话生命周期 ----

    def begin_session(self) -> None:
        """保存用户文本剪贴板（非文本/空剪贴板不保存）。"""
        self._current = ""
        self._committed = 0
        self._last_committed_tail = ""
        self._detached = False
        self._session_open = True
        try:
            self._saved_clipboard = pyperclip.paste()
        except pyperclip.PyperclipException:
            self._saved_clipboard = None  # 剪贴板里有非文本内容（图片/文件），MVP 不动它

    def end_session(self) -> None:
        """关闭会话（此后所有写入 no-op）并恢复用户剪贴板文本。"""
        self._session_open = False
        if self._saved_clipboard is not None:
            try:
                if pyperclip.paste() != self._saved_clipboard:
                    pyperclip.copy(self._saved_clipboard)
            except pyperclip.PyperclipException:
                pass
        self._saved_clipboard = None

    # ---- 可编辑检测 ----

    def is_editable_focused(self) -> bool:
        try:
            ctrl = uiautomation.GetFocusedControl()
        except Exception:  # noqa: BLE001 —— UIA 不可用（会话/权限）时默认放行
            return True
        if ctrl is None:
            return True
        process = ""
        try:
            process = self._norm_process(ctrl.ProcessName or "")
        except Exception:  # noqa: BLE001
            pass
        if process in self._blacklist:
            return False
        if ctrl.ControlTypeName in _EDITABLE_CONTROL_TYPES:
            return True
        try:
            value = ctrl.GetValuePattern()
        except Exception:  # noqa: BLE001
            value = None
        if value is not None:
            try:
                return not value.IsReadOnly
            except Exception:  # noqa: BLE001
                return True
        return False

    # ---- 写入与记账 ----

    def replace_current(self, text: str) -> bool:
        """整句刷新当前 partial。

        不可编辑 / 会话已关闭 / 本句已脱管：不做任何操作并返回 False。
        本句脱管：焦点离开编辑框后屏幕状态不受控，放弃本句剩余 partial——
        否则焦点切回时会把整句重新粘贴一遍造成重复（取舍见 docs/pitfalls.md）。
        """
        if not self._session_open or self._detached:
            return False
        # 无变化时跳过——省掉最贵的 UIA 焦点查询，也让 commit 前的最终同步零开销
        prefix = " " if _ASCII_WORD_TAIL.match(self._last_committed_tail or " ") else ""
        target = prefix + text
        if target == self._current:
            return True
        if not self.is_editable_focused():
            self._detached = True
            self._current = ""
            return False
        for _ in range(len(self._current)):
            keyboard.press_and_release("backspace")
        try:
            self._paste(target)
        except pyperclip.PyperclipException:
            # 剪贴板被瞬态占用：旧 partial 已被退格删除、新文本没贴上——
            # 屏幕状态未知，本句脱管，下轮 partial 不会基于错误记账继续删字
            self._detached = True
            self._current = ""
            return False
        self._current = target
        return True

    def commit_current(self) -> str:
        """锁句：当前 partial 记入已提交，返回已上屏的句子文本（含句间空格）。

        脱管句 / 会话已关闭：返回空串（屏幕上没有本句的完整文本）。
        """
        if not self._session_open:
            self._current = ""
            return ""
        committed = self._current
        self._committed += len(committed)
        self._last_committed_tail = committed[-1:] if committed else ""
        self._current = ""
        self._detached = False
        return committed

    @property
    def committed_chars(self) -> int:
        """已锁句总字符数（含句间分隔空格）——阶段 4 校对替换的退格基准。"""
        return self._committed

    def _paste(self, text: str) -> None:
        pyperclip.copy(text)
        keyboard.press_and_release("ctrl+v")

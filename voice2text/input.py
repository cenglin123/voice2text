"""光标处上屏：UIA 可编辑检测 + 剪贴板粘贴 + 已上屏记账。

设计（docs/overview.md「可编辑检测为什么用 UIAutomation」）：
- uiautomation 取焦点控件，ControlType ∈ {Edit, Document} 或 ValuePattern 可写 → 可输入
- 查不到控件（自绘 UI）或 UIA 异常 → 默认放行；config 黑名单按进程名关停
- 中文上屏走剪贴板 + Ctrl+V（模拟键击会被输入法拦截）；MVP 只保存/恢复文本剪贴板
- 记账：_current 跟踪当前句已上屏 partial，整句刷新 = 退格 len(_current) 次 + 粘贴新句
"""

from __future__ import annotations

import re
import threading
import time

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
        self._committed_texts: list[str] = []  # 已锁句的屏幕文本（含 prefix），按句序
        self._last_committed_tail = ""  # 上句结尾（决定句间是否补空格）
        self._detached = False  # 本句脱管：焦点离开编辑框后放弃本句剩余 partial，防止重复上屏
        self.aborted = False  # 粘贴失败导致会话停写（主循环据此提示用户）
        self._saved_clipboard: str | None = None
        self._session_open = False
        self._lock = threading.RLock()  # 识别线程（partial/commit）与校对线程（replace_committed）并发写

    @property
    def committed_chars(self) -> int:
        """已锁句总字符数（含句间分隔空格）——当前光标位置的定位基准。"""
        with self._lock:
            return sum(len(t) for t in self._committed_texts)

    @property
    def sentence_count(self) -> int:
        with self._lock:
            return len(self._committed_texts)

    @staticmethod
    def _norm_process(name: str) -> str:
        """黑名单进程名归一化：忽略大小写与 .exe 后缀（配置写 notepad 或 notepad.exe 均命中）。"""
        n = name.strip().lower()
        return n[:-4] if n.endswith(".exe") else n

    # ---- 会话生命周期 ----

    def begin_session(self) -> None:
        """保存用户文本剪贴板（非文本/空剪贴板不保存）。"""
        with self._lock:
            self._current = ""
            self._committed_texts = []
            self._detached = False
            self._session_open = True
            # 注意：_last_committed_tail 不重置——同一文本框里跨会话延续句间空格逻辑
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
        with self._lock:
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
        with self._lock:
            if not self._session_open:
                self._current = ""
                return ""
            committed = self._current
            if committed:
                self._committed_texts.append(committed)
                self._last_committed_tail = committed[-1]
            self._current = ""
            self._detached = False
            return committed

    def replace_committed_range(self, start: int, end: int, new_text: str) -> bool:
        """用校对结果替换第 start..end 句（含）的已上屏文本（校对替换的唯一入口）。

        光标处只能"从后往前删"：替换中间句需要退格掉其后所有已上屏内容
        （后续句子 + 当前 partial），重粘"新文本 + 后续句子 + 当前 partial"。
        与识别线程的并发由 _lock 串行化。
        """
        with self._lock:
            if not self._session_open:
                return False
            if not (0 <= start <= end < len(self._committed_texts)):
                return False
            old_span = self._committed_texts[start : end + 1]
            if new_text.strip() == "".join(old_span).strip():
                return True  # 无实质变化，不动屏幕
            if not self.is_editable_focused():
                return False  # 不在编辑框：放弃本次替换（原文保留在屏上）
            suffix = "".join(self._committed_texts[end + 1 :]) + self._current
            # 句间空格边界：校对结果不应吞并原句的前缀空格
            prefix_space = old_span[0][:1] if old_span[0].startswith(" ") else ""
            replacement = prefix_space + new_text.strip()
            delete_count = len(suffix) + sum(len(t) for t in old_span)
            for _ in range(delete_count):
                keyboard.press_and_release("backspace")
            try:
                self._paste(replacement + suffix)
            except pyperclip.PyperclipException:
                # 已删除未重粘：后续句子记账与屏幕失配——为防止连锁错删，
                # 本会话后续替换一律放弃（比逐句恢复更安全）
                self._session_open = False
                self.aborted = True  # 主循环轮询后向用户解释
                return False
            is_last = end == len(self._committed_texts) - 1
            self._committed_texts[start : end + 1] = [replacement]
            if is_last:
                self._last_committed_tail = replacement[-1:] if replacement else ""
            return True

    def _paste(self, text: str) -> None:
        """剪贴板 + 合成 Ctrl+V。

        键间必须留间隔：ASR/校对推理占 CPU 时，IME 的异步键盘钩子可能把
        零间隔连发的 Ctrl 和 v 拆散——落单的 v 进入拼音组合框弹出 v 模式面板、
        粘贴失败而退格已生效（实测 bug）。粘贴前先补发一次 ctrl keyup，
        清掉任何可能卡住的修饰键状态。
        """
        pyperclip.copy(text)
        keyboard.release("ctrl")
        time.sleep(0.01)
        keyboard.press("ctrl")
        time.sleep(0.02)
        keyboard.press_and_release("v")
        time.sleep(0.02)
        keyboard.release("ctrl")

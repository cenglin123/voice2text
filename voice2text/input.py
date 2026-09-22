"""光标处上屏：UIA 可编辑检测 + 文本注入 + 已上屏记账。

设计（docs/overview.md「可编辑检测为什么用 UIAutomation」「为什么不用剪贴板」）：
- uiautomation 取焦点控件，ControlType ∈ {Edit, Document} 或 ValuePattern 可写 → 可输入
- 开始时锁定窗口/控件；已知终端允许原生焦点检测，其他 UIA 异常停止输入
- 默认用 SendInput Unicode 注入直接上屏；微信 Qt 输入框和显式兜底模式使用
  带历史/云同步排除标记、完成后恢复原内容的临时剪贴板事务
- 记账：_current 跟踪当前句已上屏 partial；刷新只替换最长公共前缀之后的变化尾部
"""

from __future__ import annotations

import re
import threading
import time
from time import perf_counter_ns

import keyboard  # type: ignore[import-untyped]  # 仅剪贴板兜底路径使用

from voice2text import keysender
from voice2text.clipboard_tx import temporary_text
from voice2text.target import InputTarget
from voice2text.diagnostics import trace

_ASCII_WORD_TAIL = re.compile(r"[A-Za-z0-9]$")
_TRAILING_PUNCTUATION = re.compile(r"[，。？！、；：,.!?;:\"'”’」』）)】]+$")
_INSERTABLE_PUNCTUATION = re.compile(r"[，。？！、；：,.!?;:]")
_CLIPBOARD_INPUT_APPS = {"weixin", "windowsterminal"}
_NO_PROOFREAD_REWRITE_APPS = {"weixin"}


def _semantic_tail(text: str) -> str:
    """返回句末标点之前的最后一个字符，用于判断英文句间空格。"""
    stripped = _TRAILING_PUNCTUATION.sub("", text.rstrip())
    return stripped[-1:] if stripped else ""


class TextInserter:
    """负责"光标处写入什么"的唯一记账者——校对替换也必须经过本类。"""

    def __init__(
        self,
        process_blacklist: list[str] | None = None,
        use_clipboard: bool = False,
        metrics=None,
    ) -> None:
        self._blacklist = {self._norm_process(p) for p in (process_blacklist or [])}
        self._use_clipboard = use_clipboard
        self._metrics = metrics
        self._current = ""  # 当前句已上屏的 partial（含句间空格 prefix）
        self._committed_texts: list[str] = []  # 已锁句的屏幕文本（含 prefix），按句序
        self._last_committed_tail = ""  # 上句结尾（决定句间是否补空格）
        self._detached = False  # 本句脱管：焦点离开编辑框后放弃本句剩余 partial，防止重复上屏
        self.aborted = False  # 注入失败导致会话停写（主循环据此提示用户）
        self._session_open = False
        self._generation = 0
        self._lock = threading.RLock()  # 识别线程（partial/commit）与校对（replace_committed_range）并发写
        self._target: InputTarget | None = None
        self.abort_reason = ""

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

    def begin_session(self, target: InputTarget) -> int:
        """开启会话。不经剪贴板，无保存/恢复动作。"""
        with self._lock:
            self._generation += 1
            self._current = ""
            self._committed_texts = []
            self._detached = False
            self.aborted = False
            self.abort_reason = ""
            self._target = target
            self._session_open = True
            self._last_committed_tail = ""  # 新会话的光标位置不一定与上次相同
            return self._generation

    def end_session(self, expected_generation: int | None = None) -> bool:
        """关闭会话（此后所有写入 no-op）。"""
        with self._lock:
            if expected_generation is not None and expected_generation != self._generation:
                return False
            self._session_open = False
            self._target = None
            return True

    def abort(self, reason: str) -> None:
        """立即关闭写入闸门；不等待持锁的注入批次。"""
        self._session_open = False
        self.aborted = True
        self.abort_reason = reason

    def capture_target(self) -> InputTarget:
        return InputTarget.capture(self._blacklist)

    def guard_focus(self) -> bool:
        """主循环维持原前台，覆盖停止后的校对阶段。"""
        if not self._session_open or self._target is None:
            return False
        started = perf_counter_ns()
        try:
            restored = self._target.restore()
        except Exception:
            trace("target_restore_exception", detail=__import__('traceback').format_exc())
            restored = False
        if self._metrics is not None:
            self._metrics.record("target_restore", perf_counter_ns() - started,
                                 "ok" if restored else "failed")
        if not restored:
            trace("target_restore_failed", snapshot=self._target.diagnostic_snapshot())
            self.abort("原输入窗口已关闭或焦点无法安全恢复，已停止上屏")
            return False
        return True

    def _check_batch(self) -> None:
        if not self._session_open or self._target is None or not self._target.focused():
            self.abort("输入期间焦点发生变化，已停止上屏，请回到原位置重新开始")
            raise OSError(self.abort_reason)

    # ---- 可编辑检测 ----

    def is_editable_focused(self) -> bool:
        return self.guard_focus()

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
            # sherpa partial 会修正尾部，但大部分前缀稳定。只替换分歧后的尾部，
            # 避免每 250ms 整句清空再重打造成闪烁，也显著降低长句注入延迟。
            common = 0
            common_limit = min(len(self._current), len(target))
            while common < common_limit and self._current[common] == target[common]:
                common += 1
            try:
                self._delete_chars(len(self._current) - common)
                self._insert_text(target[common:])
            except Exception as exc:  # noqa: BLE001 —— 注入失败：屏幕状态未知，本句脱管
                self._detached = True
                self._current = ""
                if isinstance(exc, OSError):
                    self._session_open = False
                    self.aborted = True  # 注入层系统性失败，主循环提示用户
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
                self._last_committed_tail = _semantic_tail(committed)
            self._current = ""
            self._detached = False
            return committed

    def punctuate_and_commit_current(self, text: str) -> str:
        """只移动光标并插入新增标点，然后锁句；不删除或重打已上屏汉字。"""
        with self._lock:
            if not self._session_open or self._detached:
                return ""
            prefix = " " if _ASCII_WORD_TAIL.match(self._last_committed_tail or " ") else ""
            target = prefix + text
            if target != self._current:
                additions = self._punctuation_insertions(self._current, target)
                if additions is None or not self.is_editable_focused():
                    return ""
                try:
                    self._insert_punctuation_only(len(self._current), additions, 0)
                except Exception as exc:  # noqa: BLE001
                    self._session_open = False
                    self.aborted = True
                    self.abort_reason = f"标点写入失败，已停止上屏：{exc}"
                    return ""
                self._current = target
            return self.commit_current()

    def replace_committed_range(
        self, start: int, end: int, new_text: str, expected_generation: int | None = None
    ) -> bool:
        """用校对结果替换第 start..end 句（含）的已上屏文本（校对替换的唯一入口）。

        光标处只能"从后往前删"：替换中间句需要退格掉其后所有已上屏内容
        （后续句子 + 当前 partial），重粘"新文本 + 后续句子 + 当前 partial"。
        与识别线程的并发由 _lock 串行化。
        """
        with self._lock:
            if expected_generation is not None and expected_generation != self._generation:
                return False
            if not self._session_open:
                return False
            if not (0 <= start <= end < len(self._committed_texts)):
                return False
            old_span = self._committed_texts[start : end + 1]
            if new_text.strip() == "".join(old_span).strip():
                self._committed_texts[start : end + 1] = ["".join(old_span)]
                return True  # 无实质变化，不动屏幕
            if not self.is_editable_focused():
                return False  # 不在编辑框：放弃本次替换（原文保留在屏上）
            suffix = "".join(self._committed_texts[end + 1 :]) + self._current
            # 句间空格边界：校对结果不应吞并原句的前缀空格
            prefix_space = old_span[0][:1] if old_span[0].startswith(" ") else ""
            replacement = prefix_space + new_text.strip()
            old_text = "".join(old_span)
            if self._target_process() in _NO_PROOFREAD_REWRITE_APPS:
                return False
            additions = self._punctuation_insertions(old_text, replacement)
            if additions is not None:
                try:
                    self._insert_punctuation_only(
                        len(old_text), additions, len(suffix)
                    )
                except Exception:  # noqa: BLE001
                    self._session_open = False
                    self.aborted = True
                    return False
                is_last = end == len(self._committed_texts) - 1
                self._committed_texts[start : end + 1] = [replacement]
                if is_last:
                    self._last_committed_tail = _semantic_tail(replacement)
                return True
            try:
                self._delete_chars(sum(len(t) for t in old_span) + len(suffix))
                self._insert_text(replacement + suffix)
            except Exception:  # noqa: BLE001
                # 已删除未重粘：后续句子记账与屏幕失配——为防止连锁错删，
                # 本会话后续写入一律放弃（比逐句恢复更安全）
                self._session_open = False
                self.aborted = True
                return False
            is_last = end == len(self._committed_texts) - 1
            self._committed_texts[start : end + 1] = [replacement]
            if is_last:
                self._last_committed_tail = _semantic_tail(replacement)
            return True

    def _target_process(self) -> str:
        return self._norm_process(self._target.process) if self._target is not None else ""

    @staticmethod
    def _punctuation_insertions(source: str, target: str) -> list[tuple[int, str]] | None:
        """若 target 仅在 source 中插入单个标点，返回各插入边界。"""
        additions: list[tuple[int, str]] = []
        source_index = 0
        for char in target:
            if source_index < len(source) and char == source[source_index]:
                source_index += 1
            elif _INSERTABLE_PUNCTUATION.fullmatch(char):
                if source_index == 0 or (additions and additions[-1][0] == source_index):
                    return None
                additions.append((source_index, char))
            else:
                return None
        if source_index != len(source):
            return None
        return additions

    def _insert_punctuation_only(
        self, source_length: int, additions: list[tuple[int, str]], trailing_chars: int
    ) -> None:
        """光标从整段末尾开始，自右向左插标点，最后恢复到段末。"""
        cursor = source_length + trailing_chars
        final_length = cursor + len(additions)
        for boundary, punctuation in reversed(additions):
            keysender.send_key_presses(
                keysender.VK_LEFT, cursor - boundary, guard=self._check_batch
            )
            self._insert_text(punctuation)
            cursor = boundary + 1
        keysender.send_key_presses(
            keysender.VK_RIGHT, final_length - cursor, guard=self._check_batch
        )

    # ---- 底层写入 ----

    def _delete_chars(self, n: int) -> None:
        self._check_batch()
        if self._uses_clipboard():
            for _ in range(n):
                self._check_batch()
                keyboard.press_and_release("backspace")
            time.sleep(0.01)
        else:
            keysender.send_backspaces(n, guard=self._check_batch)

    def _insert_text(self, text: str) -> None:
        self._check_batch()
        if self._uses_clipboard():
            self._paste_text(text)
        else:
            keysender.send_text(text, guard=self._check_batch)

    def _paste_text(self, text: str) -> None:
        """以不进入 Win+V/云同步的临时剪贴板事务粘贴，并恢复原始全部格式。"""
        self._check_batch()
        trace("injection", process=self._target_process(), text=text,
              transport="protected_clipboard")
        # Windows Terminal 提供专用的 Ctrl+Shift+V 粘贴绑定；真机已确认当前
        # Ctrl+V 路径会出现按键发送成功但没有文字。这里选用前者以避开终端配置
        # 或 shell/readline 对 Ctrl+V 的接管。微信等 GUI 输入框继续使用 Ctrl+V。
        modifiers = (
            ("ctrl", "shift")
            if self._target_process() == "windowsterminal"
            else ("ctrl",)
        )
        with temporary_text(text):
            # 键间必须留间隔：IME 的异步钩子可能把零间隔组合键拆散。
            for modifier in reversed(modifiers):
                keyboard.release(modifier)
            time.sleep(0.01)
            self._check_batch()
            for modifier in modifiers:
                keyboard.press(modifier)
            try:
                time.sleep(0.02)
                self._check_batch()
                keyboard.press_and_release("v")
                time.sleep(0.12)
            finally:
                for modifier in reversed(modifiers):
                    keyboard.release(modifier)

    def _uses_clipboard(self) -> bool:
        return self._use_clipboard or self._target_process() in _CLIPBOARD_INPUT_APPS

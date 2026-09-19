"""离线回归：模拟焦点与注入，不向用户窗口发送按键，不加载模型。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text import target, keysender
from voice2text.input import TextInserter
from voice2text.desktop import RuntimeOutput, SingleInstance
from voice2text.tray import build_tray, toggle_label
from pystray._util import win32
from voice2text.activity import InputActivityGuard
from voice2text.main import DictationApp
from voice2text.config import AppConfig, DEFAULTS


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.destination = Mock()
        self.destination.restore.return_value = True
        self.destination.focused.return_value = True
        self.inserter = TextInserter()
        self.inserter.begin_session(self.destination)
        self.screen = ""
        def text(value, guard):
            guard()
            self.screen += value
        def back(n, guard):
            guard()
            if n:
                self.screen = self.screen[:-n]
        self.enterContext(patch.object(keysender, "send_text", side_effect=text))
        self.enterContext(patch.object(keysender, "send_backspaces", side_effect=back))

    def test_restore_and_proofread(self):
        self.inserter.replace_current("测试")
        self.inserter.commit_current()
        self.assertTrue(self.inserter.replace_committed_range(0, 0, "测试。"))
        self.assertEqual(self.screen, "测试。")
        self.assertGreaterEqual(self.destination.restore.call_count, 2)

    def test_failed_restore_closes_all_following_writes(self):
        self.inserter.replace_current("原文")
        self.inserter.commit_current()
        self.destination.restore.return_value = False
        self.assertFalse(self.inserter.replace_committed_range(0, 0, "修改"))
        self.destination.restore.return_value = True
        self.assertFalse(self.inserter.replace_current("迟到"))
        self.assertEqual(self.screen, "原文")
        self.assertTrue(self.inserter.aborted)

    def test_mid_transaction_focus_change_stops(self):
        self.destination.focused.return_value = False
        self.assertFalse(self.inserter.replace_current("不得写入"))
        self.assertEqual(self.screen, "")
        self.assertTrue(self.inserter.aborted)

    def test_closed_session_rejects_late_output(self):
        self.inserter.end_session()
        self.assertFalse(self.inserter.replace_current("迟到"))
        self.assertFalse(self.inserter.replace_committed_range(0, 0, "迟到"))
        self.assertEqual(self.screen, "")

    def test_unchanged_chunk_still_merges_accounting(self):
        for value in ("第一句", "第二句", "第三句"):
            self.inserter.replace_current(value)
            self.inserter.commit_current()
        self.assertTrue(self.inserter.replace_committed_range(0, 1, "第一句第二句"))
        self.assertEqual(self.inserter.sentence_count, 2)
        self.assertTrue(self.inserter.replace_committed_range(1, 1, "第三句。"))
        self.assertEqual(self.screen, "第一句第二句第三句。")

    def test_tail_callback_before_generation_invalidated(self):
        app = DictationApp(AppConfig(**DEFAULTS))
        app._inserter = self.inserter
        app._capture = Mock()
        app._cfg.proofread_enabled = False
        app._cfg.sound_cue = False
        worker = Mock()
        worker.is_alive.return_value = False
        worker.join.side_effect = lambda **kwargs: app._on_sentence(0, "尾句")
        app._worker = worker
        app._stop_session()
        app._on_sentence(0, "迟到旧回调")
        self.assertEqual(self.screen, "尾句")


class TargetTests(unittest.TestCase):
    def capture(self, terminal=True, control=None):
        with patch.object(target, "foreground", return_value=123), \
             patch.object(target, "_identity", return_value=(45, 999999)), \
             patch.object(target, "_process_name", return_value="windowsterminal"), \
             patch.object(target, "_focus", return_value=124), \
             patch.object(target, "_class", return_value="CASCADIA_HOSTING_WINDOW_CLASS" if terminal else "unknown"), \
             patch.object(target.auto, "GetFocusedControl", return_value=control):
            return target.InputTarget.capture(set())

    def test_terminal_without_edit_pattern_or_uia(self):
        self.assertTrue(self.capture().terminal)
        ctrl = Mock(ControlTypeName="PaneControl")
        ctrl.GetRuntimeId.return_value = [1, 2]
        self.assertTrue(self.capture(control=ctrl).terminal)

    def test_unknown_uia_failure_rejected(self):
        with self.assertRaises(RuntimeError):
            self.capture(terminal=False)

    def test_same_window_different_control_not_restored(self):
        dest = self.capture()
        with patch.object(target.InputTarget, "focused", return_value=False), \
             patch.object(target.InputTarget, "valid", return_value=True), \
             patch.object(target, "foreground", return_value=123):
            self.assertFalse(dest.restore())

    def test_closed_target_not_restored(self):
        dest = self.capture()
        with patch.object(target.InputTarget, "focused", return_value=False), \
             patch.object(target.InputTarget, "valid", return_value=False):
            self.assertFalse(dest.restore())


class DesktopTests(unittest.TestCase):
    def test_output_bounded(self):
        output = RuntimeOutput()
        output.write("a" * 100000)
        output.write("b" * 100000)
        self.assertEqual(output.snapshot(), (2, "a" * 20000 + "b" * 100000))

    def test_single_instance(self):
        first = SingleInstance()
        second = SingleInstance()
        try:
            self.assertTrue(second.already_running)
        finally:
            second.close()
            first.close()

    def test_tray_toggle_shows_current_hotkey(self):
        app = Mock(active=False, widget_visible=True)
        app.hotkey.combo = "ctrl+alt+v"
        icon = build_tray(__import__("queue").Queue(), app)
        self.assertEqual(toggle_label(app), "开始听写（ctrl+alt+v）")
        self.assertIsNone(icon.menu)
        app.active = True
        self.assertEqual(toggle_label(app), "停止听写（ctrl+alt+v）")

    def test_tray_clicks_are_forwarded_to_custom_menu(self):
        import queue
        commands = queue.Queue()
        app = Mock(active=False, widget_visible=True)
        app.hotkey.combo = "alt+v"
        icon = build_tray(commands, app)
        icon._on_notify(0, win32.WM_LBUTTONUP)
        self.assertEqual(commands.get_nowait(), ("toggle", None))
        icon._on_notify(0, win32.WM_RBUTTONUP)
        command, point = commands.get_nowait()
        self.assertEqual(command, "tray_menu")
        self.assertEqual(len(point), 2)

    def test_stop_hotkey_is_not_treated_as_manual_edit(self):
        guard = InputActivityGuard.__new__(InputActivityGuard)
        guard._hotkey_groups = [{0xA4, 0xA5}, {0x56}]
        with patch("voice2text.activity._pressed", side_effect=lambda vk: vk == 0xA4):
            self.assertTrue(guard._is_hotkey(0x56))
            self.assertFalse(guard._is_hotkey(0x41))


if __name__ == "__main__":
    unittest.main()

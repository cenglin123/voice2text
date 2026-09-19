"""离线回归：模拟焦点与注入，不向用户窗口发送按键，不加载模型。"""
from pathlib import Path
import sys
import time
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
from voice2text.proofread import Proofreader
from voice2text.performance import PerformanceRecorder
from voice2text.punctuation import PunctuationRestorer
from voice2text.asr import ASRSessionWorker


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
        self.send_text = self.enterContext(patch.object(keysender, "send_text", side_effect=text))
        self.send_backspaces = self.enterContext(patch.object(keysender, "send_backspaces", side_effect=back))

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

    def test_partial_refresh_only_replaces_changed_suffix(self):
        self.inserter.replace_current("识别文字是不是实时")
        self.inserter.replace_current("识别文本是不是实时的")
        self.assertEqual(self.screen, "识别文本是不是实时的")
        self.assertEqual(self.send_backspaces.call_args.args[0], 6)
        self.assertEqual(self.send_text.call_args.args[0], "本是不是实时的")

    def test_english_sentence_keeps_space_after_punctuation(self):
        self.inserter.replace_current("hello world。")
        self.inserter.commit_current()
        self.inserter.replace_current("next sentence")
        self.assertEqual(self.screen, "hello world。 next sentence")

    def test_empty_commit_keeps_previous_english_separator(self):
        self.inserter.replace_current("hello world。")
        self.inserter.commit_current()
        self.inserter.commit_current()
        self.inserter.replace_current("next")
        self.assertEqual(self.screen, "hello world。 next")

    def test_slow_proofread_result_is_still_applied(self):
        self.inserter.replace_current("测试文本")
        self.inserter.commit_current()
        app = DictationApp(AppConfig(**DEFAULTS))
        app._inserter = self.inserter
        app._input_session = 1
        app._locked_sentences = ["测试文本"]
        app._proofreader = Mock()
        app._proofreader.proofread.return_value = "测试文本。"
        with patch("voice2text.main.time.monotonic", side_effect=[0.0, 11.0]):
            app._finalize_proofread(1)
        self.assertEqual(self.screen, "测试文本。")

    def test_tail_callback_before_generation_invalidated(self):
        app = DictationApp(AppConfig(**DEFAULTS))
        app._inserter = self.inserter
        app._input_session = 1
        app._capture = Mock()
        app._cfg.proofread_enabled = False
        app._cfg.sound_cue = False
        worker = Mock()
        worker.is_alive.return_value = False
        worker.join.side_effect = lambda **kwargs: app._on_sentence(0, "尾句")
        app._worker = worker
        app._stop_session(1)
        app._on_sentence(0, "迟到旧回调")
        self.assertEqual(self.screen, "尾句")

    def test_hard_timeout_closes_old_input_generation_and_blocks_late_replacement(self):
        self.inserter.replace_current("旧会话")
        self.inserter.commit_current()
        app = DictationApp(AppConfig(**DEFAULTS))
        app._inserter = self.inserter
        app._input_session = 1
        app._active = True
        app._busy = True
        app._cancel_stalled_proofread(1, 1)
        self.assertFalse(app._active)
        self.assertFalse(app._busy)
        self.assertFalse(self.inserter.replace_committed_range(0, 0, "错误写入", 1))
        next_generation = self.inserter.begin_session(self.destination)
        self.assertNotEqual(next_generation, 1)
        self.assertFalse(self.inserter.replace_committed_range(0, 0, "迟到结果", 1))

    def test_hanging_proofread_timer_releases_focus_and_discards_late_result(self):
        self.inserter.replace_current("等待校对")
        self.inserter.commit_current()
        app = DictationApp(AppConfig(**DEFAULTS))
        app._inserter = self.inserter
        app._input_session = 1
        app._locked_sentences = ["等待校对"]
        app._cfg.proofread_hard_timeout_seconds = 0.01
        app._active = True
        app._busy = True
        app._proofreader = Mock()
        app._proofreader.proofread.side_effect = lambda _: (time.sleep(0.03), "错误迟到结果")[1]
        app._finalize_proofread(1)
        self.assertTrue(self.inserter.replace_current("" ) is False)
        self.assertEqual(self.screen, "等待校对")
        self.assertFalse(app._active)
        self.assertFalse(app._busy)


class TargetTests(unittest.TestCase):
    def capture(self, terminal=True, control=None, process="windowsterminal", window_class=None):
        class_name = window_class or ("CASCADIA_HOSTING_WINDOW_CLASS" if terminal else "unknown")
        with patch.object(target, "foreground", return_value=123), \
             patch.object(target, "_identity", return_value=(45, 999999)), \
             patch.object(target, "_process_name", return_value=process), \
             patch.object(target, "_focus", return_value=124), \
             patch.object(target, "_class", return_value=class_name), \
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

    def test_chatgpt_webview_uses_stable_native_focus_after_initial_editable_check(self):
        ctrl = Mock(ControlTypeName="EditControl")
        ctrl.GetRuntimeId.return_value = [1, 2]
        ctrl.GetValuePattern.return_value = None
        dest = self.capture(terminal=False, control=ctrl, process="chatgpt",
                            window_class="Chrome_WidgetWin_1")
        self.assertEqual(dest.runtime_id, ())
        self.assertFalse(dest.terminal)

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


class ProofreadTests(unittest.TestCase):
    def test_cleanup_failure_falls_back_to_punctuation_task(self):
        proofreader = Proofreader.__new__(Proofreader)
        proofreader._generate = Mock(side_effect=[None, "这是测试。"])
        self.assertEqual(proofreader.proofread("这是测试"), "这是测试。")

    def test_model_failure_still_adds_terminal_punctuation(self):
        proofreader = Proofreader.__new__(Proofreader)
        proofreader._generate = Mock(side_effect=[None, None])
        self.assertEqual(proofreader.proofread("这是测试"), "这是测试。")
        self.assertEqual(proofreader.last_outcome, "terminal_fallback")

    def test_result_with_only_internal_punctuation_gets_terminal_mark(self):
        proofreader = Proofreader.__new__(Proofreader)
        proofreader._generate = Mock(return_value="这是测试，继续")
        self.assertEqual(proofreader.proofread("这是测试继续"), "这是测试，继续。")

    def test_terminal_fallback_never_punctuates_number_url_or_path(self):
        for value in ("20260919", "https://example.com/a", r"C:\\temp\\note.txt"):
            proofreader = Proofreader.__new__(Proofreader)
            proofreader._generate = Mock(side_effect=[None, None])
            self.assertEqual(proofreader.proofread(value), value)


class PunctuationTests(unittest.TestCase):
    def restorer(self, result):
        restorer = PunctuationRestorer.__new__(PunctuationRestorer)
        restorer._engine = Mock()
        restorer._engine.add_punctuation.return_value = result
        return restorer

    def test_accepts_punctuation_only_change(self):
        result, outcome = self.restorer("现在是什么情况，标点去哪儿了？").restore(
            "现在是什么情况标点去哪儿了"
        )
        self.assertEqual(result, "现在是什么情况，标点去哪儿了？")
        self.assertEqual(outcome, "applied")

    def test_rejects_any_recognition_text_change(self):
        original = "准确的识别"
        result, outcome = self.restorer("准确地识别。").restore(original)
        self.assertEqual(result, original)
        self.assertEqual(outcome, "unsafe_change")

    def test_rejects_replacing_existing_punctuation(self):
        original = "第一句，第二句"
        result, outcome = self.restorer("第一句。第二句。").restore(original)
        self.assertEqual(result, original)
        self.assertEqual(outcome, "unsafe_change")

    def test_projects_english_punctuation_without_removing_source_space(self):
        original = "hello world this is a test"
        result, outcome = self.restorer("hello world，this is a test。").restore(original)
        self.assertEqual(result, "hello world， this is a test。")
        self.assertEqual(outcome, "applied")

    def test_model_whitespace_does_not_change_decimal_spacing(self):
        original = "version 1.2 is ready"
        result, outcome = self.restorer("version 1 . 2 is ready。").restore(original)
        self.assertEqual(result, "version 1.2 is ready。")
        self.assertEqual(outcome, "applied")

    def test_worker_records_punctuation_latency_and_result(self):
        punctuator = Mock()
        punctuator.restore.return_value = ("测试。", "applied")
        metrics = PerformanceRecorder()
        worker = ASRSessionWorker(Mock(), Mock(), 16000, Mock(), Mock(), punctuator, metrics)
        self.assertEqual(worker._restore_punctuation("测试"), "测试。")
        self.assertEqual(
            metrics.summary()["punctuation_restore"]["results"], {"applied": 1}
        )

    def test_worker_displays_raw_text_then_commits_punctuated_sentence(self):
        events = []
        punctuator = Mock()
        punctuator.restore.return_value = ("这是测试。", "applied")
        worker = ASRSessionWorker(
            Mock(), Mock(), 16000,
            lambda text: events.append(("partial", text)),
            lambda text: events.append(("sentence", text)),
            punctuator,
        )
        worker._deliver_sentence("这是测试")
        self.assertEqual(events, [("partial", "这是测试"), ("sentence", "这是测试。")])


class PerformanceTests(unittest.TestCase):
    def test_cancelled_inference_keeps_timing_and_reason(self):
        import io
        from contextlib import redirect_stdout
        app = DictationApp(AppConfig(**DEFAULTS))
        app._input_session = 1
        app._locked_sentences = ['测试']
        app._proofreader = Mock()
        def inference(text):
            app._inserter.abort('测试手动编辑')
            return '测试。'
        app._proofreader.proofread.side_effect = inference
        output = io.StringIO()
        with redirect_stdout(output):
            app._finalize_proofread(1)
        self.assertIn('推理后', output.getvalue())
        self.assertIn('测试手动编辑', output.getvalue())
        self.assertEqual(app._metrics.summary()['proofread_generate']['results'], {'cancelled': 1})

    def test_summary_groups_result_codes_and_hides_small_sample_p95(self):
        recorder = PerformanceRecorder(capacity=3)
        recorder.record("partial_write", 2_000_000, "ok")
        recorder.record("partial_write", 4_000_000, "failed")
        report = recorder.summary()["partial_write"]
        self.assertEqual(report["count"], 2)
        self.assertEqual(report["p95_ms"], -1.0)
        self.assertEqual(report["results"], {"ok": 1, "failed": 1})

    def test_ring_buffer_discards_oldest_events(self):
        recorder = PerformanceRecorder(capacity=2)
        recorder.record("old", 1)
        recorder.record("new", 1)
        recorder.record("new", 1)
        self.assertNotIn("old", recorder.summary())
        self.assertIn("覆盖 1 条", recorder.format_summary())

class DesktopTests(unittest.TestCase):
    def test_hotkey_event_sequence_survives_stale_async_state(self):
        import ctypes
        from voice2text.activity import _Key
        guard = InputActivityGuard.__new__(InputActivityGuard)
        guard._hotkey_groups = [{0xA4, 0xA5}, {0x56}]
        guard._down = set()
        guard.inserter = Mock(_session_open=True)
        def emit(vk, message):
            key = _Key(vk=vk)
            guard._key(0, message, ctypes.addressof(key))
        with patch('voice2text.activity._pressed', return_value=False), \
             patch('voice2text.activity._user.CallNextHookEx', return_value=0):
            emit(0xA4, 0x104)
            emit(0x56, 0x104)
            guard.inserter.abort.assert_not_called()
            emit(0x56, 0x105)
            emit(0xA4, 0x105)
            emit(0x56, 0x100)
            guard.inserter.abort.assert_called_once()

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
        guard._down = {0xA4}
        with patch("voice2text.activity._pressed", side_effect=lambda vk: vk == 0xA4):
            self.assertTrue(guard._is_hotkey(0x56))
            self.assertFalse(guard._is_hotkey(0x41))


if __name__ == "__main__":
    unittest.main()

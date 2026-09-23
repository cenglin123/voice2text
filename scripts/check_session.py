"""离线回归：模拟焦点与注入，不向用户窗口发送按键，不加载模型。"""
from pathlib import Path
import queue
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

import keyboard

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text import target, keysender, clipboard_tx, capture
from voice2text.input import TextInserter
from voice2text.desktop import RuntimeOutput, SingleInstance
from voice2text.tray import build_tray, toggle_label
from pystray._util import win32
from voice2text.activity import InputActivityGuard
from voice2text.main import DictationApp, UI_POLL_MS, resolve_help_document
from voice2text.config import AppConfig, DEFAULTS
from voice2text.proofread import Proofreader
from voice2text.performance import PerformanceRecorder
from voice2text.punctuation import PunctuationRestorer
from voice2text.asr import ASRSessionWorker
from voice2text.hotkey import HotkeyListener


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.destination = Mock()
        self.destination.process = "notepad"
        self.destination.restore.return_value = True
        self.destination.focused.return_value = True
        self.inserter = TextInserter()
        self.inserter.begin_session(self.destination)
        self.screen = ""
        self.cursor = 0
        def text(value, guard):
            guard()
            self.screen = self.screen[:self.cursor] + value + self.screen[self.cursor:]
            self.cursor += len(value)
        def back(n, guard):
            guard()
            if n:
                start = max(0, self.cursor - n)
                self.screen = self.screen[:start] + self.screen[self.cursor:]
                self.cursor = start
        def navigate(vk, n, guard):
            guard()
            if vk == keysender.VK_LEFT:
                self.cursor = max(0, self.cursor - n)
            elif vk == keysender.VK_RIGHT:
                self.cursor = min(len(self.screen), self.cursor + n)
        self.send_text = self.enterContext(patch.object(keysender, "send_text", side_effect=text))
        self.send_text_slow = self.enterContext(
            patch.object(keysender, "send_text_slow", side_effect=text)
        )
        self.send_backspaces = self.enterContext(patch.object(keysender, "send_backspaces", side_effect=back))
        self.send_key_presses = self.enterContext(
            patch.object(keysender, "send_key_presses", side_effect=navigate)
        )
        self.paste_text = self.enterContext(
            patch.object(
                self.inserter,
                "_paste_text",
                side_effect=lambda value: text(value, self.inserter._check_batch),
            )
        )

    def test_elevated_target_displays_actionable_notice(self):
        app = DictationApp(AppConfig(**DEFAULTS))
        app._models_ready.set()
        reason = "目标以管理员权限运行，请以管理员身份重新启动本软件。"
        with patch.object(app._inserter, "capture_target", side_effect=target.ElevatedTargetError(reason)):
            app.request_toggle()
        self.assertEqual(app.cmd_queue.get_nowait(), ("elevation_notice", reason))
        self.assertEqual(app.ui_queue.get_nowait(), ("state", "error"))
        self.assertFalse(app.active)

    def test_help_document_prefers_packaged_install_guide(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            readme = root / "README.md"
            guide = root / "安装说明.txt"
            readme.write_text("source help", encoding="utf-8")
            self.assertEqual(resolve_help_document(root), readme)
            guide.write_text("release help", encoding="utf-8")
            self.assertEqual(resolve_help_document(root), guide)

    def test_debug_audio_is_removed_on_startup_and_cleanup(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            debug_path = Path(tmp) / "debug_capture.wav"
            debug_path.write_bytes(b"stale microphone data")
            with patch.object(capture, "DEBUG_CAPTURE_PATH", debug_path):
                recorder = capture.MicrophoneCapture(debug_dump_wav=True)
                self.assertFalse(debug_path.exists())
                debug_path.write_bytes(b"current microphone data")
                recorder.cleanup_debug_dump()
                self.assertFalse(debug_path.exists())

    def test_selected_input_device_resolves_by_name_and_host_api(self):
        devices = [
            {"name": "Array Mic", "max_input_channels": 1, "default_samplerate": 48000, "hostapi": 0},
            {"name": "Array Mic", "max_input_channels": 1, "default_samplerate": 44100, "hostapi": 1},
            {"name": "Speakers", "max_input_channels": 0, "default_samplerate": 48000, "hostapi": 0},
        ]
        with patch.object(capture.sd, "query_devices", return_value=devices), \
             patch.object(capture.sd, "query_hostapis", return_value=[{"name": "MME"}, {"name": "WASAPI"}]):
            self.assertEqual(capture.resolve_input_device("WASAPI::Array Mic"), 1)
            self.assertEqual(capture.list_input_device_choices(), [
                ("Array Mic · MME", "MME::Array Mic"),
                ("Array Mic · WASAPI", "WASAPI::Array Mic"),
            ])
            with self.assertRaisesRegex(capture.CaptureError, "不可用"):
                capture.resolve_input_device("WASAPI::Missing Mic")
            with self.assertRaisesRegex(capture.CaptureError, "歧义"):
                capture.resolve_input_device("Array Mic")

    def test_windows_terminal_uses_protected_clipboard_transport(self):
        self.destination.process = "windowsterminal"
        self.send_text.reset_mock()
        self.assertTrue(self.inserter.replace_current("终端输入"))
        self.paste_text.assert_called_once_with("终端输入")
        self.send_text.assert_not_called()

    def test_clipboard_system_error_aborts_session_with_actionable_reason(self):
        self.destination.process = "windowsterminal"
        self.paste_text.side_effect = OSError("无法备份当前剪贴板，已取消本次文字输入")
        self.assertFalse(self.inserter.replace_current("终端输入"))
        self.assertTrue(self.inserter.aborted)
        self.assertIn("无法备份当前剪贴板", self.inserter.abort_reason)

    def test_clipboard_refresh_preflight_failure_preserves_existing_text(self):
        self.destination.process = "windowsterminal"
        self.screen = "原有识别文字"
        self.cursor = len(self.screen)
        self.inserter._current = self.screen
        with patch(
            "voice2text.input.temporary_text",
            side_effect=OSError("无法备份当前剪贴板，已取消本次文字输入"),
        ), patch("voice2text.input.keyboard.press_and_release") as press:
            self.assertFalse(self.inserter.replace_current("原有修正文字"))
        self.assertEqual(self.screen, "原有识别文字")
        press.assert_not_called()

    def test_restore_and_proofread(self):
        self.inserter.replace_current("测试")
        self.inserter.commit_current()
        self.assertTrue(self.inserter.replace_committed_range(0, 0, "测试。"))
        self.assertEqual(self.screen, "测试。")
        self.assertGreaterEqual(self.destination.restore.call_count, 2)

    def test_endpoint_punctuation_never_deletes_or_retypes_source_text(self):
        raw = "锄禾日当午汗滴禾下土谁知盘中餐粒粒皆辛苦"
        punctuated = "锄禾日当午，汗滴禾下土，谁知盘中餐，粒粒皆辛苦。"
        self.assertTrue(self.inserter.replace_current(raw))
        self.send_text.reset_mock()
        self.send_backspaces.reset_mock()
        committed = self.inserter.punctuate_and_commit_current(punctuated)
        self.assertEqual(committed, punctuated)
        self.assertEqual(self.screen, punctuated)
        self.send_backspaces.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in self.send_text.call_args_list],
            ["。", "，", "，", "，"],
        )

    def test_weixin_streams_partial_with_protected_paste_then_inserts_punctuation(self):
        self.destination.process = "weixin"
        raw = "锄禾日当午汗滴禾下土谁知盘中餐粒粒皆辛苦"
        punctuated = "锄禾日当午，汗滴禾下土，谁知盘中餐，粒粒皆辛苦。"
        self.assertTrue(self.inserter.replace_current(raw))
        self.assertEqual(self.screen, raw)
        self.paste_text.assert_called_once_with(raw)
        self.paste_text.reset_mock()
        self.send_text.reset_mock()
        self.send_backspaces.reset_mock()
        self.send_key_presses.reset_mock()
        committed = self.inserter.punctuate_and_commit_current(punctuated)
        self.assertEqual(committed, punctuated)
        self.assertEqual(self.screen, punctuated)
        self.send_backspaces.assert_not_called()
        self.send_text.assert_not_called()
        self.send_text_slow.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in self.paste_text.call_args_list],
            ["。", "，", "，", "，"],
        )

    def test_weixin_rejects_destructive_proofread_replacement(self):
        self.destination.process = "weixin"
        self.inserter.replace_current("原始文字。")
        self.inserter.punctuate_and_commit_current("原始文字。")
        self.send_backspaces.reset_mock()
        self.assertFalse(self.inserter.replace_committed_range(0, 0, "修改文字。"))
        self.assertEqual(self.screen, "原始文字。")
        self.send_backspaces.assert_not_called()

    def test_proofread_punctuation_only_preserves_following_text(self):
        for value in ("第一句", "第二句"):
            self.inserter.replace_current(value)
            self.inserter.commit_current()
        self.send_backspaces.reset_mock()
        self.assertTrue(self.inserter.replace_committed_range(0, 0, "第一句。"))
        self.assertEqual(self.screen, "第一句。第二句")
        self.send_backspaces.assert_not_called()

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
        worker.join.side_effect = lambda **kwargs: (
            app._on_partial(0, "尾句"), app._on_sentence(0, "尾句")
        )
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

    def test_windows_terminal_process_is_terminal_when_host_class_changes(self):
        dest = self.capture(terminal=False, control=None, process="windowsterminal",
                            window_class="ApplicationFrameWindow")
        self.assertTrue(dest.terminal)
        self.assertEqual(dest.runtime_id, ())

    def test_unknown_uia_failure_rejected(self):
        with self.assertRaises(RuntimeError):
            self.capture(terminal=False, process="unknownapp")

    def test_chatgpt_webview_uses_stable_native_focus_after_initial_editable_check(self):
        ctrl = Mock(ControlTypeName="EditControl")
        ctrl.GetRuntimeId.return_value = [1, 2]
        ctrl.GetPattern.return_value = None
        dest = self.capture(terminal=False, control=ctrl, process="chatgpt",
                            window_class="Chrome_WidgetWin_1")
        self.assertEqual(dest.runtime_id, ())
        self.assertFalse(dest.terminal)

    def test_weixin_webview_uses_stable_native_focus_after_initial_editable_check(self):
        ctrl = Mock(ControlTypeName="EditControl")
        ctrl.GetRuntimeId.return_value = [1, 2]
        ctrl.GetPattern.return_value = None
        dest = self.capture(terminal=False, control=ctrl, process="weixin",
                            window_class="Chrome_WidgetWin_1")
        self.assertEqual(dest.runtime_id, ())
        self.assertFalse(dest.terminal)

    def test_weixin_window_control_without_value_pattern_is_accepted(self):
        # UIA may surface the WebView input area as WindowControl, which does not
        # expose GetValuePattern; volatile WebView targets use native focus guards.
        ctrl = Mock(ControlTypeName="WindowControl")
        ctrl.GetRuntimeId.return_value = [1, 2]
        dest = self.capture(terminal=False, control=ctrl, process="weixin",
                            window_class="Chrome_WidgetWin_1")
        self.assertEqual(dest.runtime_id, ())
        ctrl.GetPattern.assert_not_called()

    def test_uia_validation_preserves_reason_and_unexpected_detail(self):
        with patch.object(target, "foreground", return_value=123), \
             patch.object(target, "_identity", return_value=(45, 999999)), \
             patch.object(target, "_process_name", return_value="ordinaryapp"), \
             patch.object(target, "_focus", return_value=124), \
             patch.object(target, "_class", return_value="MainWindow"), \
             patch.object(target.auto, "GetFocusedControl", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "无法读取目标输入控件"):
                target.InputTarget.capture(set())
        with patch.object(target, "foreground", return_value=123), \
             patch.object(target, "_identity", return_value=(45, 999999)), \
             patch.object(target, "_process_name", return_value="ordinaryapp"), \
             patch.object(target, "_focus", return_value=124), \
             patch.object(target, "_class", return_value="MainWindow"), \
             patch.object(target.auto, "GetFocusedControl", side_effect=AttributeError("UIA detail")):
            with self.assertRaisesRegex(RuntimeError, "UIA detail"):
                target.InputTarget.capture(set())

    def test_wps_apps_allow_stable_native_focus_when_uia_is_custom_drawn(self):
        for process in ("wps", "et", "wpp"):
            with self.subTest(process=process):
                dest = self.capture(terminal=False, control=None, process=process,
                                    window_class="WPSMainWindow")
                self.assertEqual(dest.runtime_id, ())
                self.assertFalse(dest.terminal)

    def test_wps_cell_editor_focus_may_change_inside_same_process(self):
        dest = self.capture(terminal=False, control=None, process="wps",
                            window_class="WPSMainWindow")
        with patch.object(target, "foreground", return_value=dest.hwnd), \
             patch.object(target, "_focus", side_effect=lambda tid: 777 if tid == 0 else 0), \
             patch.object(target, "_identity", side_effect=lambda hwnd: (
                 (dest.tid, dest.pid) if hwnd in (dest.hwnd, 777) else (0, 0)
             )), patch.object(target._user, "IsWindow", return_value=True):
            self.assertTrue(dest.focused())
            self.assertTrue(dest.restore())

    def test_wps_accepts_same_process_foreground_when_focus_is_temporarily_empty(self):
        dest = self.capture(terminal=False, control=None, process="wps",
                            window_class="WPSMainWindow")
        with patch.object(target, "foreground", return_value=888), \
             patch.object(target, "_focus", return_value=0), \
             patch.object(target, "_identity", side_effect=lambda hwnd: (
                 (dest.tid, dest.pid) if hwnd in (dest.hwnd, 888) else (0, 0)
             )), patch.object(target._user, "IsWindow", return_value=True):
            self.assertTrue(dest.focused())

    def test_wps_accepts_recreated_top_window_in_same_locked_process(self):
        dest = self.capture(terminal=False, control=None, process="wps",
                            window_class="WPSMainWindow")
        with patch.object(target, "foreground", return_value=888), \
             patch.object(target, "_focus", return_value=999), \
             patch.object(target, "_identity", side_effect=lambda hwnd: (
                 (dest.tid, dest.pid) if hwnd in (888, 999) else (0, 0)
             )), patch.object(target._user, "IsWindow", return_value=False):
            self.assertTrue(dest.valid())
            self.assertTrue(dest.focused())

    def test_wps_accepts_captured_editor_hosted_by_companion_process(self):
        identities = {
            123: (45, 999999),
            124: (46, 888888),
        }
        with patch.object(target, "foreground", return_value=123), \
             patch.object(target, "_identity", side_effect=lambda hwnd: identities.get(hwnd, (0, 0))), \
             patch.object(target, "_process_name", return_value="wps"), \
             patch.object(target, "_focus", return_value=124), \
             patch.object(target, "_class", return_value="OpusApp"), \
             patch.object(target.auto, "GetFocusedControl", return_value=None):
            dest = target.InputTarget.capture(set())
        self.assertEqual((dest.focus_tid, dest.focus_pid), (46, 888888))
        with patch.object(target, "foreground", return_value=123), \
             patch.object(target, "_focus", return_value=124), \
             patch.object(target, "_identity", side_effect=lambda hwnd: identities.get(hwnd, (0, 0))), \
             patch.object(target._user, "IsWindow", return_value=True):
            self.assertTrue(dest.focused())
            self.assertTrue(dest.restore())

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

    def test_rejects_leading_or_duplicate_inserted_punctuation(self):
        original = "锄禾日当午汗滴禾下土"
        for unsafe in ("？锄禾日当午，汗滴禾下土。", "锄禾日当午，，汗滴禾下土。"):
            with self.subTest(unsafe=unsafe):
                result, outcome = self.restorer(unsafe).restore(original)
                self.assertEqual(result, original)
                self.assertEqual(outcome, "unsafe_change")

    def test_worker_records_punctuation_latency_and_result(self):
        punctuator = Mock()
        punctuator.restore.return_value = ("测试。", "applied")
        metrics = PerformanceRecorder()
        worker = ASRSessionWorker(Mock(), Mock(), 16000, Mock(), Mock(), punctuator, metrics)
        self.assertEqual(worker._restore_punctuation("测试"), "测试。")
        self.assertEqual(
            metrics.summary()["punctuation_restore"]["results"], {"applied": 1}
        )

    def test_worker_reports_ready_only_after_recognition_stream_exists(self):
        allow_stream = threading.Event()
        recognizer = Mock()
        stream = Mock()

        def create_stream():
            allow_stream.wait(1.0)
            return stream

        recognizer.create_stream.side_effect = create_stream
        recognizer.is_ready.return_value = False
        recognizer.is_endpoint.return_value = False
        asr = Mock(recognizer=recognizer)
        asr.decode.return_value = ""
        audio_queue = queue.Queue()
        audio_queue.put(None)
        worker = ASRSessionWorker(asr, audio_queue, 16000, Mock(), Mock())
        worker.start()
        self.assertFalse(worker.wait_until_ready(0.02))
        allow_stream.set()
        self.assertTrue(worker.wait_until_ready(1.0))
        worker.join(1.0)
        self.assertFalse(worker.is_alive())

    def test_worker_readiness_surfaces_stream_creation_failure(self):
        recognizer = Mock()
        recognizer.create_stream.side_effect = RuntimeError("stream init failed")
        asr = Mock(recognizer=recognizer)
        worker = ASRSessionWorker(asr, queue.Queue(), 16000, Mock(), Mock())
        worker.start()
        self.assertFalse(worker.wait_until_ready(1.0))
        worker.join(1.0)
        self.assertIn("stream init failed", worker.error)

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

    def test_worker_does_not_apply_punctuation_after_raw_sync_failure(self):
        events = []
        punctuator = Mock()
        punctuator.restore.return_value = ("锄禾日当午，汗滴禾下土。", "applied")
        worker = ASRSessionWorker(
            Mock(), Mock(), 16000,
            lambda text: events.append(("partial", text)) or False,
            lambda text: events.append(("sentence", text)),
            punctuator,
        )
        worker._deliver_sentence("锄禾日当午汗滴禾下土")
        self.assertEqual(events, [("partial", "锄禾日当午汗滴禾下土")])

    def test_reported_weixin_punctuation_rewrite_is_rejected(self):
        original = "锄禾日当午汗滴禾下土谁知盘中餐粒粒皆辛苦"
        rewritten = "。禾日当午，，地禾下土，，知盘中餐，，粒皆辛苦。"
        result, outcome = self.restorer(rewritten).restore(original)
        self.assertEqual(result, original)
        self.assertEqual(outcome, "unsafe_change")

    def test_endpoint_final_cannot_replace_or_delete_last_displayed_partial(self):
        events = []
        original = "锄禾日当午汗滴禾下土谁知盘中餐粒粒皆辛苦"
        lossy_final = "禾日当午滴禾下土知盘中餐粒皆辛苦"
        punctuator = self.restorer("锄禾日当午，汗滴禾下土，谁知盘中餐，粒粒皆辛苦。")
        worker = ASRSessionWorker(
            Mock(), Mock(), 16000,
            lambda text: events.append(("partial", text)),
            lambda text: events.append(("sentence", text)),
            punctuator,
        )
        worker._last_partial = original
        worker._deliver_sentence(lossy_final)
        self.assertEqual(events, [
            ("partial", original),
            ("sentence", "锄禾日当午，汗滴禾下土，谁知盘中餐，粒粒皆辛苦。"),
        ])


class PerformanceTests(unittest.TestCase):
    def test_session_becomes_active_only_after_worker_is_ready(self):
        values = dict(DEFAULTS)
        values.update(proofread_enabled=False, punctuation_enabled=False)
        app = DictationApp(AppConfig(**values))
        order = []
        app._asr = Mock()
        app._capture = Mock(queue=queue.Queue())
        app._capture.start.side_effect = lambda: order.append("capture")
        app._inserter = Mock(aborted=False)
        app._inserter.guard_focus.return_value = True
        worker = Mock(error=None)
        worker.start.side_effect = lambda: order.append("worker")
        worker.wait_until_ready.side_effect = lambda timeout: order.append("ready") or True
        with patch("voice2text.main.ASRSessionWorker", return_value=worker), \
             patch.object(app, "_cue", side_effect=lambda name: order.append(name)):
            app._start_session()
        self.assertTrue(app.active)
        self.assertEqual(order, ["capture", "worker", "ready", "start"])

    def test_session_does_not_claim_listening_when_worker_never_becomes_ready(self):
        values = dict(DEFAULTS)
        values.update(proofread_enabled=False, punctuation_enabled=False)
        app = DictationApp(AppConfig(**values))
        app._asr = Mock()
        app._capture = Mock(queue=queue.Queue())
        app._inserter = Mock(aborted=False)
        app._inserter.guard_focus.return_value = True
        worker = Mock(error="识别流创建失败")
        worker.wait_until_ready.return_value = False
        with patch("voice2text.main.ASRSessionWorker", return_value=worker), \
             self.assertRaisesRegex(RuntimeError, "识别流创建失败"):
            app._start_session()
        self.assertFalse(app.active)
        self.assertEqual(app._session_gen, 2)
        app._capture.stop.assert_called_once()

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
    def test_hotkey_poll_interval_stays_below_perceptible_delay(self):
        self.assertLessEqual(UI_POLL_MS, 30)

    def test_windows_terminal_pastes_with_ctrl_shift_v(self):
        destination = Mock(process="windowsterminal")
        destination.focused.return_value = True
        inserter = TextInserter()
        inserter.begin_session(destination)
        with patch("voice2text.input.temporary_text") as temporary, \
             patch("voice2text.input.time.sleep"), \
             patch("voice2text.input.keyboard.press") as press, \
             patch("voice2text.input.keyboard.press_and_release") as press_release, \
             patch("voice2text.input.keyboard.release") as release:
            inserter._paste_text("终端输入")
        temporary.assert_called_once_with("终端输入")
        self.assertEqual([call.args[0] for call in press.call_args_list], ["ctrl", "shift"])
        press_release.assert_called_once_with("v")
        self.assertEqual(
            [call.args[0] for call in release.call_args_list],
            ["shift", "ctrl", "shift", "ctrl"],
        )

    def test_protected_clipboard_marks_temporary_text_private_and_restores(self):
        original = Mock()
        formats = {}
        with patch.object(clipboard_tx, "_initialize_ole") as initialize, \
             patch.object(clipboard_tx, "_uninitialize_ole") as uninitialize, \
             patch.object(clipboard_tx.pythoncom, "OleGetClipboard", return_value=original), \
             patch.object(clipboard_tx.pythoncom, "OleSetClipboard") as restore, \
             patch.object(clipboard_tx.win32clipboard, "OpenClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CloseClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CountClipboardFormats", return_value=1), \
             patch.object(clipboard_tx.win32clipboard, "EmptyClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "SetClipboardText"), \
             patch.object(
                 clipboard_tx.win32clipboard,
                 "RegisterClipboardFormat",
                 side_effect=lambda name: formats.setdefault(name, len(formats) + 100),
             ), \
             patch.object(clipboard_tx.win32clipboard, "SetClipboardData") as set_data, \
             patch.object(
                 clipboard_tx.win32clipboard,
                 "GetClipboardSequenceNumber",
                 return_value=7,
             ):
            with clipboard_tx.temporary_text("测试"):
                pass
        self.assertEqual(set(formats), set(clipboard_tx._PRIVACY_FORMATS))
        self.assertEqual(set_data.call_count, len(clipboard_tx._PRIVACY_FORMATS))
        initialize.assert_called_once()
        uninitialize.assert_called_once()
        restore.assert_called_once_with(original)

    def test_clipboard_restore_failure_does_not_report_successful_paste_as_failed(self):
        with patch.object(clipboard_tx, "_initialize_ole"), \
             patch.object(clipboard_tx, "_uninitialize_ole"), \
             patch.object(clipboard_tx.win32clipboard, "OpenClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CloseClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CountClipboardFormats", return_value=1), \
             patch.object(clipboard_tx.pythoncom, "OleGetClipboard", return_value=Mock()), \
             patch.object(clipboard_tx, "_publish", return_value=7), \
             patch.object(clipboard_tx.win32clipboard, "GetClipboardSequenceNumber", return_value=7), \
             patch.object(clipboard_tx.pythoncom, "OleSetClipboard", side_effect=RuntimeError("restore")), \
             patch.object(clipboard_tx, "trace") as trace:
            with clipboard_tx.temporary_text("测试"):
                pass
        trace.assert_called_once_with("clipboard_restore_failed", detail="restore")

    def test_clipboard_snapshot_failure_never_overwrites_or_clears_user_clipboard(self):
        with patch.object(clipboard_tx, "_initialize_ole"), \
             patch.object(clipboard_tx, "_uninitialize_ole"), \
             patch.object(clipboard_tx.win32clipboard, "OpenClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CloseClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CountClipboardFormats", return_value=1), \
             patch.object(clipboard_tx.win32clipboard, "GetClipboardSequenceNumber", return_value=7), \
             patch.object(
                 clipboard_tx.pythoncom,
                 "OleGetClipboard",
                 side_effect=clipboard_tx.pythoncom.com_error(
                     -2147221040, "clipboard busy", None, None
                 ),
             ), patch.object(clipboard_tx, "_publish") as publish, \
             patch.object(clipboard_tx, "_empty") as empty, \
             patch.object(clipboard_tx.time, "sleep"):
            with self.assertRaisesRegex(OSError, "无法备份"):
                with clipboard_tx.temporary_text("测试"):
                    pass
        publish.assert_not_called()
        empty.assert_not_called()

    def test_clipboard_change_between_snapshot_and_publish_never_overwrites_new_copy(self):
        original = Mock()
        with patch.object(clipboard_tx, "_initialize_ole"), \
             patch.object(clipboard_tx, "_uninitialize_ole"), \
             patch.object(clipboard_tx, "_snapshot", return_value=(original, 7)), \
             patch.object(clipboard_tx.win32clipboard, "OpenClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CloseClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "GetClipboardSequenceNumber", return_value=8), \
             patch.object(clipboard_tx.win32clipboard, "EmptyClipboard") as empty:
            with self.assertRaisesRegex(OSError, "发生变化"):
                with clipboard_tx.temporary_text("测试"):
                    pass
        empty.assert_not_called()

    def test_partial_clipboard_publish_failure_restores_original(self):
        original = Mock()
        with patch.object(clipboard_tx, "_initialize_ole"), \
             patch.object(clipboard_tx, "_uninitialize_ole"), \
             patch.object(clipboard_tx, "_snapshot", return_value=(original, 7)), \
             patch.object(clipboard_tx.win32clipboard, "OpenClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CloseClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "GetClipboardSequenceNumber", side_effect=[7, 8, 8]), \
             patch.object(clipboard_tx.win32clipboard, "EmptyClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "SetClipboardText", side_effect=RuntimeError("publish")), \
             patch.object(clipboard_tx.pythoncom, "OleSetClipboard") as restore:
            with self.assertRaisesRegex(OSError, "发布临时剪贴板文本失败"):
                with clipboard_tx.temporary_text("测试"):
                    pass
        restore.assert_called_once_with(original)

    def test_partial_publish_restore_failure_still_reports_actionable_input_error(self):
        original = Mock()
        failure = clipboard_tx._PublishError("publish", 8)
        def fail_restore(_original, sequence):
            if sequence is not None:
                raise RuntimeError("restore")
        with patch.object(clipboard_tx, "_initialize_ole"), \
             patch.object(clipboard_tx, "_uninitialize_ole"), \
             patch.object(clipboard_tx, "_snapshot", return_value=(original, 7)), \
             patch.object(clipboard_tx, "_publish", side_effect=failure), \
             patch.object(
                 clipboard_tx, "_restore_if_unchanged",
                 side_effect=fail_restore,
             ), \
             patch.object(clipboard_tx, "trace") as trace:
            with self.assertRaisesRegex(OSError, "发布临时剪贴板文本失败"):
                with clipboard_tx.temporary_text("测试"):
                    pass
        trace.assert_called_once_with("clipboard_restore_failed", detail="restore")

    def test_external_copy_after_publish_is_never_replaced_by_old_snapshot(self):
        original = Mock()
        with patch.object(clipboard_tx, "_initialize_ole"), \
             patch.object(clipboard_tx, "_uninitialize_ole"), \
             patch.object(clipboard_tx, "_snapshot", return_value=(original, 7)), \
             patch.object(clipboard_tx, "_publish", return_value=8), \
             patch.object(clipboard_tx.win32clipboard, "GetClipboardSequenceNumber", return_value=9), \
             patch.object(clipboard_tx.pythoncom, "OleSetClipboard") as restore:
            with clipboard_tx.temporary_text("测试"):
                pass
        restore.assert_not_called()

    def test_empty_clipboard_can_be_used_and_is_restored_empty(self):
        with patch.object(clipboard_tx, "_initialize_ole"), \
             patch.object(clipboard_tx, "_uninitialize_ole"), \
             patch.object(clipboard_tx.win32clipboard, "OpenClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CloseClipboard"), \
             patch.object(clipboard_tx.win32clipboard, "CountClipboardFormats", return_value=0), \
             patch.object(clipboard_tx.pythoncom, "OleGetClipboard") as snapshot, \
             patch.object(clipboard_tx, "_publish", return_value=7), \
             patch.object(clipboard_tx.win32clipboard, "GetClipboardSequenceNumber", return_value=7), \
             patch.object(clipboard_tx, "_empty") as empty:
            with clipboard_tx.temporary_text("测试"):
                pass
        snapshot.assert_not_called()
        empty.assert_called_once()

    def test_hotkey_blocks_main_key_until_release_without_leaking_to_terminal(self):
        callbacks = []
        remove = Mock()
        with patch(
            "voice2text.hotkey.keyboard.parse_hotkey_combinations",
            return_value=(((56, 47),),),
        ), patch(
            "voice2text.hotkey.keyboard.is_modifier",
            side_effect=lambda code: code == 56,
        ), patch(
            "voice2text.hotkey.keyboard.hook",
            side_effect=lambda callback, suppress: callbacks.append((callback, suppress)) or remove,
        ):
            listener = HotkeyListener("alt+v")
        callback, suppress = callbacks[0]
        self.assertTrue(suppress)
        self.assertTrue(callback(Mock(scan_code=56, event_type=keyboard.KEY_DOWN)))
        self.assertFalse(callback(Mock(scan_code=47, event_type=keyboard.KEY_DOWN)))
        self.assertFalse(listener.toggle_event.is_set())
        self.assertFalse(callback(Mock(scan_code=47, event_type=keyboard.KEY_UP)))
        self.assertTrue(listener.toggle_event.is_set())
        self.assertTrue(callback(Mock(scan_code=56, event_type=keyboard.KEY_UP)))

    def test_hotkey_main_key_without_modifier_passes_through(self):
        callbacks = []
        with patch(
            "voice2text.hotkey.keyboard.parse_hotkey_combinations",
            return_value=(((56, 47),),),
        ), patch(
            "voice2text.hotkey.keyboard.is_modifier",
            side_effect=lambda code: code == 56,
        ), patch(
            "voice2text.hotkey.keyboard.hook",
            side_effect=lambda callback, suppress: callbacks.append(callback) or Mock(),
        ):
            listener = HotkeyListener("alt+v")
        callback = callbacks[0]
        self.assertTrue(callback(Mock(scan_code=47, event_type=keyboard.KEY_DOWN)))
        self.assertTrue(callback(Mock(scan_code=47, event_type=keyboard.KEY_UP)))
        self.assertFalse(listener.toggle_event.is_set())

    def test_hotkey_repeat_stays_blocked_after_modifier_is_released(self):
        callbacks = []
        with patch(
            "voice2text.hotkey.keyboard.parse_hotkey_combinations",
            return_value=(((56, 47),),),
        ), patch(
            "voice2text.hotkey.keyboard.is_modifier",
            side_effect=lambda code: code == 56,
        ), patch(
            "voice2text.hotkey.keyboard.hook",
            side_effect=lambda callback, suppress: callbacks.append(callback) or Mock(),
        ):
            listener = HotkeyListener("alt+v")
        callback = callbacks[0]
        self.assertTrue(callback(Mock(scan_code=56, event_type=keyboard.KEY_DOWN)))
        self.assertFalse(callback(Mock(scan_code=47, event_type=keyboard.KEY_DOWN)))
        self.assertTrue(callback(Mock(scan_code=56, event_type=keyboard.KEY_UP)))
        self.assertFalse(callback(Mock(scan_code=47, event_type=keyboard.KEY_DOWN)))
        self.assertFalse(callback(Mock(scan_code=47, event_type=keyboard.KEY_UP)))
        self.assertTrue(listener.toggle_event.is_set())

    def test_slow_unicode_input_holds_each_code_unit_before_keyup(self):
        with patch.object(keysender, "_flush") as flush, \
             patch.object(keysender.time, "sleep") as sleep:
            keysender.send_text_slow("甲", interval=0.02, key_down_delay=0.01)
        self.assertEqual(flush.call_count, 2)
        down = flush.call_args_list[0].args[0][0]
        up = flush.call_args_list[1].args[0][0]
        self.assertEqual(down.ki.dwFlags, keysender.KEYEVENTF_UNICODE)
        self.assertEqual(
            up.ki.dwFlags, keysender.KEYEVENTF_UNICODE | keysender.KEYEVENTF_KEYUP
        )
        sleep.assert_called_once_with(0.01)

    def test_hotkey_clear_releases_only_latched_alt(self):
        listener = HotkeyListener.__new__(HotkeyListener)
        listener._toggle_event = __import__("threading").Event()
        listener._toggle_event.set()
        with patch("voice2text.hotkey._pressed", side_effect=lambda vk: vk == 0xA4), \
             patch("voice2text.hotkey._user.keybd_event") as release:
            listener.clear_toggle()
        self.assertFalse(listener.toggle_event.is_set())
        release.assert_called_once_with(0xA4, 0, 0x0002, 0)

    def test_hotkey_clear_does_not_inject_after_normal_alt_release(self):
        listener = HotkeyListener.__new__(HotkeyListener)
        listener._toggle_event = __import__("threading").Event()
        listener._toggle_event.set()
        with patch("voice2text.hotkey._pressed", return_value=False), \
             patch("voice2text.hotkey._user.keybd_event") as release:
            listener.clear_toggle()
        release.assert_not_called()

    def test_hotkey_clear_reports_dispatch_latency(self):
        listener = HotkeyListener.__new__(HotkeyListener)
        listener._toggle_event = __import__("threading").Event()
        listener._toggle_event.set()
        listener._last_trigger_ns = 1_000_000_000
        with patch("voice2text.hotkey._release_latched_alt"), \
             patch("voice2text.hotkey.perf_counter_ns", return_value=1_025_000_000):
            self.assertEqual(listener.clear_toggle(), 25.0)

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

    def test_activity_guard_accepts_hotkey_repeat_after_modifier_release(self):
        import ctypes
        from voice2text.activity import _Key
        guard = InputActivityGuard.__new__(InputActivityGuard)
        guard._hotkey_groups = [{0xA4, 0xA5}, {0x56}]
        guard._down = set()
        guard._hotkey_armed = set()
        guard.inserter = Mock(_session_open=True)

        def emit(vk, message):
            key = _Key(vk=vk)
            guard._key(0, message, ctypes.addressof(key))

        with patch("voice2text.activity._pressed", return_value=False), \
             patch("voice2text.activity._user.CallNextHookEx", return_value=0):
            emit(0xA4, 0x104)
            emit(0x56, 0x104)
            emit(0xA4, 0x105)
            emit(0x56, 0x100)
            guard.inserter.abort.assert_not_called()
            emit(0x56, 0x101)
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

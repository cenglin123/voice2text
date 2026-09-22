"""离线回归：目标提权失配检测（UIPI 拦截）。

模拟焦点与令牌，不向用户窗口发送按键，不加载模型：
- 自己非提权 + 目标提权 → capture 拒绝并给出管理员指引（修复"识别/注入
  全部 [ok] 但终端无文字"的静默失败）；
- 其余组合（双方同权、自己提权、目标权限未知）→ 放行，不扩大拦截面。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text import target


def _capture_stubbed(process: str = "windowsterminal", focus_identity=(45, 999999)):
    """复用 check_session.TargetTests 的桩思路：只开 Win32 身份，绕过真实桌面。"""
    ctrl = Mock(ControlTypeName="EditControl")
    ctrl.GetRuntimeId.return_value = [1, 2]
    ctrl.GetValuePattern.return_value = None
    with patch.object(target, "foreground", return_value=123), \
         patch.object(
             target, "_identity",
             side_effect=lambda hwnd: focus_identity if hwnd == 124 else (45, 999999),
         ), \
         patch.object(target, "_process_name", return_value=process), \
         patch.object(target, "_focus", return_value=124), \
         patch.object(target, "_class", return_value="CASCADIA_HOSTING_WINDOW_CLASS"), \
         patch.object(target.auto, "GetFocusedControl", return_value=ctrl):
        return target.InputTarget.capture(set())


class ElevationGuardTests(unittest.TestCase):
    def test_elevated_target_rejected_for_non_elevated_app(self):
        with patch.object(target, "process_elevated", return_value=True), \
             patch.object(target, "self_elevated", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                _capture_stubbed()
            message = str(ctx.exception)
            self.assertIn("管理员", message)
            self.assertIn("无法向它输入", message)

    def test_same_elevation_allowed(self):
        with patch.object(target, "process_elevated", return_value=False), \
             patch.object(target, "self_elevated", return_value=False):
            self.assertTrue(_capture_stubbed().terminal)

    def test_elevated_app_allowed_for_any_target(self):
        with patch.object(target, "process_elevated", return_value=True), \
             patch.object(target, "self_elevated", return_value=True):
            self.assertTrue(_capture_stubbed().terminal)

    def test_unknown_target_elevation_fails_open(self):
        with patch.object(target, "process_elevated", return_value=None), \
             patch.object(target, "self_elevated", return_value=False):
            self.assertTrue(_capture_stubbed().terminal)

    def test_elevated_cross_process_focus_is_rejected(self):
        with patch.object(
            target, "process_elevated", side_effect=lambda pid: pid == 888888
        ), patch.object(target, "self_elevated", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "管理员"):
                _capture_stubbed("wps", focus_identity=(44, 888888))

    def test_process_elevation_open_process_failure_is_unknown(self):
        with patch.object(target._kernel, "OpenProcess", return_value=0), \
             patch.object(target.ctypes, "get_last_error", return_value=6):
            self.assertIsNone(target.process_elevated(1))

    def test_process_elevation_token_denied_means_higher_privilege(self):
        process_handle = 4321
        error = OSError("denied")
        error.winerror = 5
        with patch.object(target._kernel, "OpenProcess", return_value=process_handle), \
             patch.object(target, "_token_elevation", side_effect=error), \
             patch.object(target._kernel, "CloseHandle") as close_handle:
            self.assertIs(True, target.process_elevated(1))
        close_handle.assert_called_once_with(process_handle)

    def test_process_elevation_non_access_error_is_unknown(self):
        process_handle = 4321
        error = OSError("invalid handle")
        error.winerror = 6
        with patch.object(target._kernel, "OpenProcess", return_value=process_handle), \
             patch.object(target, "_token_elevation", side_effect=error), \
             patch.object(target._kernel, "CloseHandle") as close_handle:
            self.assertIsNone(target.process_elevated(1))
        close_handle.assert_called_once_with(process_handle)

    def test_self_elevation_closes_token_not_pseudo_process(self):
        def open_token(_process, _access, token):
            token._obj.value = 9876
            return 1

        def token_info(_token, _kind, value, _size, _got):
            value._obj.value = 1
            return 1

        with patch.object(target._kernel, "GetCurrentProcess", return_value=-1), \
             patch.object(target._advapi, "OpenProcessToken", side_effect=open_token), \
             patch.object(target._advapi, "GetTokenInformation", side_effect=token_info), \
             patch.object(target._kernel, "CloseHandle") as close_handle:
            self.assertIs(True, target.self_elevated())
        self.assertEqual(close_handle.call_count, 1)
        self.assertEqual(close_handle.call_args.args[0].value, 9876)

    def test_live_self_elevation_matches_probe_result(self):
        """真实进程自检：本脚本进程总能查到自己的提权状态。"""
        import ctypes
        is_elevated = ctypes.windll.shell32.IsUserAnAdmin()
        result = target.self_elevated()
        self.assertIs(result, bool(is_elevated))


if __name__ == "__main__":
    unittest.main(verbosity=2)

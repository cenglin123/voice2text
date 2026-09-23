#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发行脚本回归：白名单内容、默认配置和压缩包根目录。"""
from __future__ import annotations

import json
import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from build_release import build_release, _default_config, _version
from create_shortcut import create_shortcut, shortcut_spec
from download_models import ASR_NAME, ASR_REQUIRED, PUNCT_NAME


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="voice2text-release-check-") as tmp:
        root = Path(tmp)
        wheel = root / "llama_cpp_python-0.3.35-py3-none-win_amd64.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("llama_cpp_python-0.3.35.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-win_amd64\n")
        zip_path, sha_path = build_release(root / "out", wheel)
        assert zip_path.is_file() and sha_path.is_file()
        assert (root / "out/安装说明.txt").is_file()
        original = zip_path.read_bytes()
        assert sha_path.read_text().split()[0] == hashlib.sha256(original).hexdigest()
        build_release(root / "out", wheel)
        assert zip_path.read_bytes() == original
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            prefix = f"voice2text-v{_version()}-windows-x64/"
            assert prefix + "install.bat" in names
            assert prefix + "安装程序.bat" in names
            assert prefix + "启动程序.bat" in names
            assert prefix + "voice2text.ico" in names
            assert prefix + "scripts/create_shortcut.py" in names
            assert b"run.bat" in archive.read(prefix + "启动程序.bat")
            assert b"install.bat" in archive.read(prefix + "安装程序.bat")
            assert archive.read(prefix + "voice2text.ico").startswith(b"\x00\x00\x01\x00")
            assert prefix + "voice2text/main.py" in names
            assert prefix + "scripts/apply_update.ps1" in names
            assert prefix + "scripts/export_feedback.py" in names
            assert prefix + "AGENTS.md" in names
            assert prefix + "source-baseline.zip" in names
            guide_agent = archive.read(prefix + "AGENTS.md").decode("utf-8")
            assert "source-baseline.zip" in guide_agent and "export_feedback.py" in guide_agent
            with zipfile.ZipFile(io.BytesIO(archive.read(prefix + "source-baseline.zip"))) as baseline:
                source_paths = baseline.namelist()
                assert "voice2text/target.py" in source_paths
                assert "scripts/export_feedback.py" in source_paths
                assert "AGENTS.md" in source_paths
                assert not any(path.startswith(("models/", "runtime/")) or path == "config.json"
                               for path in source_paths)
                assert baseline.testzip() is None
            source_modules = {
                path.name for path in (Path(__file__).resolve().parent.parent / "voice2text").glob("*.py")
            }
            archived_modules = {
                Path(name).name for name in names if name.startswith(prefix + "voice2text/")
            }
            assert archived_modules == source_modules, (
                f"发行模块不完整：缺少 {source_modules - archived_modules}，"
                f"多出 {archived_modules - source_modules}"
            )
            assert prefix + "vendor/" + wheel.name in names
            assert not any("/.venv/" in name or "/models/" in name or "/runtime/" in name for name in names)
            config = json.loads(archive.read(prefix + "config.json"))
            assert config == _default_config()
            guide = archive.read(prefix + "安装说明.txt").decode("utf-8")
            assert "https://github.com/cenglin123/voice2text/issues" in guide
            assert "【首次使用】" in guide and "【检查更新】" in guide
            assert "【Agent 排查】" in guide
            assert archive.testzip() is None
            archive.extractall(root / "installed")
        install = root / "installed" / prefix
        target_file = install / "voice2text/target.py"
        target_file.write_text(target_file.read_text(encoding="utf-8") + "\n# local fix\n", encoding="utf-8")
        (install / "config.json").write_text('{"private":"keep-out"}', encoding="utf-8")
        feedback = root / "feedback"
        subprocess.run(
            [sys.executable, str(install / "scripts/export_feedback.py"),
             "--output-dir", str(feedback), "--summary", "目标验证异常"],
            check=True, capture_output=True, text=True,
        )
        diff_text = (feedback / "修复.diff").read_text(encoding="utf-8")
        report_text = (feedback / "反馈.md").read_text(encoding="utf-8")
        assert "diff --git a/voice2text/target.py b/voice2text/target.py" in diff_text
        assert "# local fix" in diff_text and "目标验证异常" in report_text
        assert "keep-out" not in diff_text + report_text
        spec = shortcut_spec(root, root / "runtime/python/python.exe")
        assert spec["target"].endswith("runtime\\python\\pythonw.exe")
        assert spec["arguments"].endswith('run_gui.pyw"')
        assert spec["icon"].endswith("voice2text.ico,0")
        shortcut_root = root / "shortcut"
        shortcut_python = shortcut_root / "runtime/python/python.exe"
        shortcut_python.parent.mkdir(parents=True)
        shortcut_python.write_bytes(b"fixture")
        shortcut_python.with_name("pythonw.exe").write_bytes(b"fixture")
        (shortcut_root / "run_gui.pyw").write_text("", encoding="utf-8")
        shutil.copy2(Path(__file__).resolve().parent.parent / "voice2text.ico",
                     shortcut_root / "voice2text.ico")
        shortcut_values = shortcut_spec(shortcut_root, shortcut_python)
        shortcut = create_shortcut(shortcut_root, shortcut_python)
        assert shortcut.is_file() and shortcut.name == "启动 voice2text.lnk"
        import win32com.client
        saved = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(shortcut))
        assert Path(saved.TargetPath).resolve() == shortcut_python.with_name("pythonw.exe").resolve()
        assert saved.Arguments == shortcut_values["arguments"]
        assert saved.IconLocation == shortcut_values["icon"]
        runtime = root / "runtime"
        runtime.mkdir()
        for name in ("python.exe", "pythonw.exe"):
            (runtime / name).write_bytes(b"test-fixture")
        models = root / "models"
        for rel in [*(f"asr/{ASR_NAME}/{name}" for name in ASR_REQUIRED),
                    f"punctuation/{PUNCT_NAME}/model.int8.onnx"]:
            path = models / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"model-test-fixture")
        private = models / "llm/private.gguf"
        private.parent.mkdir()
        private.write_bytes(b"must not ship")
        zip_path, _ = build_release(root / "offline", wheel, runtime, models)
        assert "离线自包含版" in (root / "offline/安装说明.txt").read_text(encoding="utf-8")
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            assert prefix + "offline-bundle.txt" in names
            assert prefix + "AGENTS.md" in names and prefix + "source-baseline.zip" in names
            assert prefix + "runtime/python/python.exe" in names
            assert prefix + f"models/punctuation/{PUNCT_NAME}/model.int8.onnx" in names
            assert not any("/llm/" in name or "/vendor/" in name for name in names)
            assert json.loads(archive.read(prefix + "config.json"))["proofread_enabled"] is False
            guide = archive.read(prefix + "安装说明.txt").decode("utf-8")
            assert "https://github.com/cenglin123/voice2text/issues" in guide
    print("PASS release allowlist, default config, bundled wheel and archive layout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

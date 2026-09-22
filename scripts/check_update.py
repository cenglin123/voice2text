#!/usr/bin/env python
"""一键更新回归：版本、固定资产、摘要和 ZIP 安全边界。"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text.update import (
    UpdateManager, file_sha256, select_assets, validate_archive, version_tuple,
)


def _archive(path: Path, version: str, malicious: bool = False) -> None:
    prefix = f"voice2text-v{version}-windows-x64/"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(prefix + "offline-bundle.txt", "offline")
        archive.writestr(prefix + "run.bat", "@echo off")
        archive.writestr(prefix + "voice2text/__init__.py", f'__version__ = "{version}"')
        archive.writestr(prefix + "runtime/python/python.exe", b"fixture")
        if malicious:
            archive.writestr(prefix + "../escape.txt", "bad")


def main() -> int:
    assert version_tuple("v0.1.10") > version_tuple("0.1.3")
    release = {
        "tag_name": "v0.1.5",
        "assets": [
            {"name": "voice2text-v0.1.5-windows-x64.zip",
             "browser_download_url": "https://github.com/cenglin123/voice2text/releases/download/v0.1.5/voice2text-v0.1.5-windows-x64.zip"},
            {"name": "voice2text-v0.1.5-windows-x64.zip.sha256",
             "browser_download_url": "https://github.com/cenglin123/voice2text/releases/download/v0.1.5/voice2text-v0.1.5-windows-x64.zip.sha256"},
        ],
    }
    version, zip_url, sha_url = select_assets(release)
    assert version == "0.1.5" and zip_url.endswith(".zip") and sha_url.endswith(".sha256")
    with tempfile.TemporaryDirectory(prefix="voice2text-update-check-") as tmp:
        root = Path(tmp)
        good = root / "good.zip"
        _archive(good, "0.1.5")
        validate_archive(good, "0.1.5")
        assert file_sha256(good) == hashlib.sha256(good.read_bytes()).hexdigest()
        bad = root / "bad.zip"
        _archive(bad, "0.1.5", malicious=True)
        try:
            validate_archive(bad, "0.1.5")
        except ValueError:
            pass
        else:
            raise AssertionError("路径穿越未被拒绝")
        install = root / "install"
        install.mkdir()
        (install / "offline-bundle.txt").write_text("old", encoding="ascii")
        (install / "config.json").write_text('{"hotkey":"ctrl+v"}', encoding="utf-8")
        llm = install / "models" / "llm" / "optional.gguf"
        llm.parent.mkdir(parents=True)
        llm.write_bytes(b"optional-model")
        payload = root / "payload.zip"
        prefix = "voice2text-v0.1.5-windows-x64/"
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr(prefix + "offline-bundle.txt", "new")
            archive.writestr(prefix + "config.json", '{"hotkey":"alt+v"}')
            archive.writestr(prefix + "run.bat", "@echo off")
            archive.writestr(prefix + "updated.txt", "updated")
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        script = Path(__file__).with_name("apply_update.ps1")
        test_env = os.environ.copy()
        test_env["LOCALAPPDATA"] = str(root / "local-app-data")
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-Archive", str(payload), "-InstallDir", str(install), "-ProcessId", "999999",
             "-Version", "0.1.5", "-NoRestart", "-KeepScript"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            env=test_env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads((install / "config.json").read_text(encoding="utf-8"))["hotkey"] == "ctrl+v"
        assert llm.read_bytes() == b"optional-model"
        assert (install / "updated.txt").read_text(encoding="utf-8") == "updated"
        manager = UpdateManager(root)
        older = io.BytesIO(json.dumps({"tag_name": "v0.1.1", "assets": []}).encode("utf-8"))
        with patch.object(manager, "_open", return_value=older):
            manager._run()
        assert manager.snapshot().state == "current"
    print("PASS version comparison, pinned assets, checksum and archive validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

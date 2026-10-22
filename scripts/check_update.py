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
    API_URL,
    AUTO_CHECK_INTERVAL,
    UpdateManager,
    UpdateSnapshot,
    file_sha256,
    launch_installer,
    select_assets,
    validate_archive,
    version_tuple,
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


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, headers=None):
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _check_scheduler(root: Path) -> None:
    install = root / "bundle"
    install.mkdir()
    (install / "offline-bundle.txt").write_text("bundle", encoding="ascii")
    local = root / "local"
    with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
        starts = []

        class FakeThread:
            def __init__(self, *, target, daemon):
                starts.append((target, daemon))

            def start(self):
                pass

        with patch("voice2text.update.threading.Thread", FakeThread):
            manager = UpdateManager(install)
            assert manager.tick_auto(True, False, now=1000) is None
            assert len(starts) == 1 and manager.snapshot().state == "checking"
            second = UpdateManager(install)
            assert second.tick_auto(True, False, now=1000 + AUTO_CHECK_INTERVAL - 1) is None
            assert len(starts) == 1
            assert second.tick_auto(True, False, now=1000 + AUTO_CHECK_INTERVAL) is None
            assert len(starts) == 2
            assert second.tick_auto(True, True, now=200000) is None
            assert second.tick_auto(False, False, now=200000) is None
            assert len(starts) == 2
            rollback = UpdateManager(install)
            assert rollback.tick_auto(True, False, now=100) is None  # clock rollback retries
            assert len(starts) == 3

            busy_install = root / "busy-bundle"
            busy_install.mkdir()
            (busy_install / "offline-bundle.txt").write_text("bundle", encoding="ascii")
            busy_manager = UpdateManager(busy_install)
            assert busy_manager.tick_auto(True, True, now=1) is None
            assert len(starts) == 4 and busy_manager.snapshot().state == "checking"

            cached = UpdateManager(root / "cached-bundle")
            (cached.project_root).mkdir()
            (cached.project_root / "offline-bundle.txt").write_text("bundle", encoding="ascii")
            with patch.object(cached, "_read_last_attempt", wraps=cached._read_last_attempt) as read_attempt:
                assert cached.tick_auto(True, False, now=1) is None
                cached._active = False
                assert cached.tick_auto(True, False, now=2) is None
                assert read_attempt.call_count == 1

            manual = UpdateManager(install)
            assert manual.start() is True
            assert len(starts) == 6
            # Manual checks also throttle the next automatic check across instances.
            cross_instance = UpdateManager(install)
            assert cross_instance.tick_auto(True, False) is None
            assert len(starts) == 6

            unsupported = UpdateManager(root / "source")
            assert unsupported.tick_auto(True, False, now=1) is None
            assert len(starts) == 6

            ready = UpdateManager(install)
            archive = root / "ready.zip"
            ready._automatic = True
            ready._snapshot = UpdateSnapshot("ready", "ready", "0.1.5", archive)
            assert ready.tick_auto(False, False, now=500000) is None
            assert ready.tick_auto(True, True, now=500000) is None
            assert ready.tick_auto(True, False, now=500000).state == "ready"
            assert ready.tick_auto(True, False, now=500000).state == "ready"
            archive.write_bytes(b"validated archive")
            stat = archive.stat()
            ready._ready_fingerprint = (stat.st_size, stat.st_mtime_ns)
            assert ready.begin_install(archive, "0.1.5")
            assert ready.snapshot().state == "installing"
            assert not ready.begin_install(archive, "0.1.5")
            assert not ready.start()
            ready.install_failed(RuntimeError("fixture"))
            assert ready.snapshot().state == "error"
            assert not ready._installing

            changed = UpdateManager(install)
            changed_archive = root / "changed.zip"
            changed_archive.write_bytes(b"original")
            changed_stat = changed_archive.stat()
            changed._snapshot = UpdateSnapshot("ready", "ready", "0.1.5", changed_archive)
            changed._ready_fingerprint = (changed_stat.st_size, changed_stat.st_mtime_ns)
            changed_archive.write_bytes(b"replaced with different size")
            assert not changed.begin_install(changed_archive, "0.1.5")
            assert changed.snapshot().state == "error"

            (install / "scripts").mkdir()
            (install / "scripts" / "apply_update.ps1").write_text("fixture", encoding="ascii")
            with patch("voice2text.update.PROJECT_ROOT", install), \
                    patch("voice2text.update.validate_archive") as validate, \
                    patch("voice2text.update.subprocess.Popen") as popen:
                launch_installer(archive, "0.1.5", 123)
                validate.assert_called_once_with(archive, "0.1.5")
                validate.reset_mock()
                launch_installer(archive, "0.1.5", 123, prevalidated=True)
                validate.assert_not_called()
                assert popen.call_count == 2

            closing = UpdateManager(install)
            closing._active = True
            closing._automatic = True
            closing.close()
            closing._run()
            assert closing.snapshot().state == "idle"
            assert closing.tick_auto(True, False, now=999999) is None

        # Drafts and prereleases are rejected before asset selection/download.
        for flag in ("draft", "prerelease"):
            rejected = UpdateManager(install)
            with patch.object(rejected, "_open", return_value=_Response(json.dumps({
                "tag_name": "v9.9.9", flag: True,
            }).encode())):
                rejected._run()
            assert rejected.snapshot().state == "error"
            assert "草稿版或预发行版" in rejected.snapshot().message


def _check_real_manager_flow(root: Path) -> None:
    install = root / "flow-bundle"
    install.mkdir()
    (install / "offline-bundle.txt").write_text("bundle", encoding="ascii")
    local = root / "flow-local"
    version = "9.9.9"
    zip_name = f"voice2text-v{version}-windows-x64.zip"
    zip_url = f"https://github.com/cenglin123/voice2text/releases/download/v{version}/{zip_name}"
    sha_url = zip_url + ".sha256"
    release = {
        "tag_name": f"v{version}",
        "assets": [
            {"name": zip_name, "browser_download_url": zip_url},
            {"name": zip_name + ".sha256", "browser_download_url": sha_url},
        ],
    }
    archive_path = root / "release.zip"
    _archive(archive_path, version)
    archive_bytes = archive_path.read_bytes()
    responses = {
        API_URL: json.dumps(release).encode("utf-8"),
        zip_url: archive_bytes,
        sha_url: (hashlib.sha256(archive_bytes).hexdigest() + "  " + zip_name).encode("ascii"),
    }
    tasks = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            tasks.append(target)

        def start(self):
            pass

    with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), \
            patch("voice2text.update.threading.Thread", FakeThread):
        manager = UpdateManager(install)
        with patch.object(manager, "_open", side_effect=lambda url: _Response(
            responses[url], {"Content-Length": str(len(responses[url]))} if url == zip_url else {},
        )):
            assert manager.tick_auto(True, False, now=100) is None
            assert len(tasks) == 1
            tasks.pop(0)()
            snapshot = manager.snapshot()
            assert snapshot.state == "ready" and snapshot.version == version
            assert snapshot.archive is not None and snapshot.archive.is_file()
            assert manager.tick_auto(True, True, now=101) is None
            assert manager.tick_auto(False, False, now=101) is None
            assert manager.tick_auto(True, False, now=101) == snapshot
            assert manager.begin_install(snapshot.archive, version)
            assert not manager.begin_install(snapshot.archive, version)

        bad_install = root / "bad-sha-bundle"
        bad_install.mkdir()
        (bad_install / "offline-bundle.txt").write_text("bundle", encoding="ascii")
        bad = UpdateManager(bad_install)
        broken_responses = dict(responses)
        broken_responses[sha_url] = ("0" * 64 + "  " + zip_name).encode("ascii")
        with patch.object(bad, "_open", side_effect=lambda url: _Response(
            broken_responses[url], {"Content-Length": str(len(broken_responses[url]))} if url == zip_url else {},
        )):
            assert bad.tick_auto(True, False, now=500) is None
            assert len(tasks) == 1
            tasks.pop(0)()
            assert bad.snapshot().state == "error"
            assert bad.tick_auto(True, False, now=500 + AUTO_CHECK_INTERVAL - 1) is None
            assert not tasks
            assert bad.tick_auto(True, False, now=500 + AUTO_CHECK_INTERVAL) is None
            assert len(tasks) == 1


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
        _check_scheduler(root)
        _check_real_manager_flow(root)
    print("PASS version comparison, pinned assets, checksum and archive validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发行脚本回归：白名单内容、默认配置和压缩包根目录。"""
from __future__ import annotations

import json
import hashlib
import tempfile
import zipfile
from pathlib import Path

from build_release import build_release, _default_config, _version
from download_models import ASR_NAME, ASR_REQUIRED, PUNCT_NAME


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="voice2text-release-check-") as tmp:
        root = Path(tmp)
        wheel = root / "llama_cpp_python-0.3.35-py3-none-win_amd64.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("llama_cpp_python-0.3.35.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-win_amd64\n")
        zip_path, sha_path = build_release(root / "out", wheel)
        assert zip_path.is_file() and sha_path.is_file()
        original = zip_path.read_bytes()
        assert sha_path.read_text().split()[0] == hashlib.sha256(original).hexdigest()
        build_release(root / "out", wheel)
        assert zip_path.read_bytes() == original
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            prefix = f"voice2text-v{_version()}-windows-x64/"
            assert prefix + "install.bat" in names
            assert prefix + "voice2text/main.py" in names
            assert prefix + "vendor/" + wheel.name in names
            assert not any("/.venv/" in name or "/models/" in name or "/runtime/" in name for name in names)
            config = json.loads(archive.read(prefix + "config.json"))
            assert config == _default_config()
            assert archive.testzip() is None
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
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            assert prefix + "offline-bundle.txt" in names
            assert prefix + "runtime/python/python.exe" in names
            assert prefix + f"models/punctuation/{PUNCT_NAME}/model.int8.onnx" in names
            assert not any("/llm/" in name or "/vendor/" in name for name in names)
            assert json.loads(archive.read(prefix + "config.json"))["proofread_enabled"] is False
    print("PASS release allowlist, default config, bundled wheel and archive layout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

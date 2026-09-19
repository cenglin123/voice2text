#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按运行时白名单生成 Windows x64 分发 ZIP，并输出 SHA256。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TEXT_FILES = ("install.bat", "run.bat", "run_gui.pyw", "requirements.txt")
PACKAGE_FILES = tuple(f"voice2text/{name}.py" for name in (
    "__init__", "activity", "asr", "capture", "config", "desktop", "hotkey",
    "input", "keysender", "layered", "main", "model_download", "performance", "proofread",
    "punctuation", "settings_window", "target", "tray", "tray_menu", "trayicon", "widget",
))
SCRIPT_FILES = ("scripts/download_models.py", "scripts/verify_install.py")
FORBIDDEN_PARTS = (".git", ".venv", "__pycache__")


def _version() -> str:
    namespace: dict[str, str] = {}
    exec((ROOT / "voice2text" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def _default_config() -> dict:
    from voice2text.config import DEFAULTS
    return dict(DEFAULTS)


def _copy_runtime_files(stage: Path) -> None:
    for rel in TEXT_FILES + SCRIPT_FILES + PACKAGE_FILES:
        source = ROOT / rel
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (stage / "config.json").write_text(
        json.dumps(_default_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (stage / "安装说明.txt").write_text(
        "voice2text Windows x64 安装版\n\n"
        "1. 解压整个文件夹，不要直接在压缩包内运行。\n"
        "2. 双击 install.bat，等待依赖和约 1.5GB 模型下载完成。\n"
        "3. 双击 run.bat。程序常驻系统托盘，按 Alt+V 开始或停止听写。\n"
        "4. 调试时运行：run.bat --debug\n\n"
        "要求：Windows 10/11 x64、麦克风、约 2.5GB 可用空间、安装期间可联网。\n",
        encoding="utf-8",
    )


def _copy_wheel(stage: Path, wheel: Path) -> None:
    expected = "llama_cpp_python-0.3.35-py3-none-win_amd64.whl"
    if not wheel.is_file() or wheel.name != expected:
        raise SystemExit(f"无效的发行 wheel：{wheel}")
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read("llama_cpp_python-0.3.35.dist-info/WHEEL").decode("utf-8")
        if "Tag: py3-none-win_amd64" not in metadata or archive.testzip() is not None:
            raise SystemExit("发行 wheel 平台或完整性校验失败")
    target = stage / "vendor" / wheel.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wheel, target)


def _validate_stage(stage: Path, offline: bool = False) -> None:
    paths = [p for p in stage.rglob("*") if p.is_file()]
    if not paths:
        raise SystemExit("发行目录为空")
    for path in paths:
        lowered = {part.lower() for part in path.relative_to(stage).parts}
        if lowered.intersection(FORBIDDEN_PARTS):
            raise SystemExit(f"发行包混入禁止目录：{path.relative_to(stage)}")
    wheels = list((stage / "vendor").glob("llama_cpp_python-0.3.35-*.whl"))
    if not offline and len(wheels) != 1:
        raise SystemExit(f"发行包必须且只能包含一个 llama wheel，实际 {len(wheels)} 个")
    config = json.loads((stage / "config.json").read_text(encoding="utf-8"))
    expected = _default_config()
    if offline:
        expected["proofread_enabled"] = False
    if config != expected:
        raise SystemExit("发行配置不是内置默认值")
    for path in paths:
        if path.relative_to(stage).parts[0] in {"runtime", "models"}:
            continue
        if path.suffix.lower() not in {".py", ".pyw", ".bat", ".md", ".txt", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if "c:\\users\\" in text or "<user-home>" in text:
            raise SystemExit(f"发行文本包含用户路径：{path.relative_to(stage)}")


def build_release(output_dir: Path, wheel: Path, runtime: Path | None = None,
                  model_root: Path | None = None) -> tuple[Path, Path]:
    version = _version()
    release_name = f"voice2text-v{version}-windows-x64"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{release_name}.zip"
    sha_path = output_dir / f"{release_name}.zip.sha256"
    with tempfile.TemporaryDirectory(prefix="voice2text-release-") as tmp:
        stage = Path(tmp) / release_name
        stage.mkdir()
        _copy_runtime_files(stage)
        if runtime is None:
            _copy_wheel(stage, wheel)
        else:
            if not (runtime / "python.exe").is_file() or not (runtime / "pythonw.exe").is_file():
                raise SystemExit("独立 Python 不完整")
            shutil.copytree(runtime, stage / "runtime/python", ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo", "direct_url.json", "Scripts"))
            from download_models import ASR_NAME, ASR_REQUIRED, PUNCT_NAME
            for rel in [*(f"asr/{ASR_NAME}/{name}" for name in ASR_REQUIRED),
                        f"punctuation/{PUNCT_NAME}/model.int8.onnx"]:
                source = (model_root or ROOT / "models") / rel
                target = stage / "models" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            config = _default_config()
            config["proofread_enabled"] = False
            (stage / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (stage / "offline-bundle.txt").write_text("voice2text offline base bundle\n", encoding="ascii")
            (stage / "安装说明.txt").write_text(
                "voice2text Windows x64 离线基础版\n\n"
                "完整解压到可写目录，双击 install.bat 验证安装，再双击 run.bat 启动。\n"
                "已包含独立 Python、所有依赖、语音和标点模型，无需系统 Python 或联网。\n"
                "Alt+V 开始/停止听写；设置 → 识别与校对可联网下载可选校对模型（约 1.1 GB）。\n"
                "下载完成后开启二次校对并保存；所有识别、标点和校对均在本地执行。\n"
                "运行输出可从设置或托盘打开。调试启动：run.bat --debug。\n",
                encoding="utf-8")
        _validate_stage(stage, offline=runtime is not None)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(path.relative_to(stage.parent).as_posix(), (2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    return zip_path, sha_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--runtime", type=Path, default=ROOT / "dist/build-runtime/python")
    parser.add_argument("--models", type=Path, default=ROOT / "models")
    args = parser.parse_args()
    wheel = args.wheel
    if wheel is None:
        candidates = sorted((ROOT / "vendor").glob("llama_cpp_python-0.3.35-*.whl"))
        if len(candidates) != 1:
            raise SystemExit("请先下载且仅保留一个 vendor/llama_cpp_python-0.3.35-*.whl")
        wheel = candidates[0]
    zip_path, sha_path = build_release(args.output_dir.resolve(), wheel.resolve(), args.runtime.resolve(), args.models.resolve())
    print(zip_path)
    print(sha_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
TEXT_FILES = (
    "install.bat", "安装程序.bat", "run.bat", "启动程序.bat", "run_gui.pyw",
    "requirements.txt",
)
ASSET_FILES = ("voice2text.ico",)
PACKAGE_FILES = tuple(f"voice2text/{name}.py" for name in (
    "__init__", "activity", "asr", "capture", "clipboard_tx", "config", "desktop",
    "diagnostics", "dpi", "hotkey", "input", "keysender", "layered", "main", "model_download",
    "performance", "proofread", "punctuation", "settings_window", "target", "tray",
    "tray_menu", "trayicon", "update", "widget",
))
SCRIPT_FILES = (
    "scripts/apply_update.ps1", "scripts/create_shortcut.py",
    "scripts/download_models.py", "scripts/export_feedback.py", "scripts/verify_install.py",
)
AGENT_GUIDE_SOURCE = ROOT / "scripts/release_agent_guide.md"
FORBIDDEN_PARTS = (".git", ".venv", "__pycache__")


def _version() -> str:
    namespace: dict[str, str] = {}
    exec((ROOT / "voice2text" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def _default_config() -> dict:
    from voice2text.config import DEFAULTS
    return dict(DEFAULTS)


def _installation_guide(offline: bool) -> str:
    title = f"voice2text v{_version()} Windows x64 {'离线自包含版' if offline else '安装版'}"
    install_detail = (
        "此版本已包含独立 Python、全部运行依赖、语音模型和标点模型，基础功能无需联网。"
        if offline else
        "安装过程会准备 Python、运行依赖、语音模型和标点模型，需要联网并预留约 2.5 GB 空间。"
    )
    return (
        f"{title}\n\n"
        "【首次使用】\n"
        "1. 完整解压整个文件夹到可写目录，不要直接在压缩包内运行。\n"
        "2. 双击“安装程序.bat”，等待验证或安装完成。\n"
        "3. 双击新生成的“启动 voice2text”快捷方式。若未生成，可双击“启动程序.bat”。\n"
        f"4. {install_detail}\n\n"
        "【日常使用】\n"
        "- 程序启动后常驻右下角系统托盘，不会一直显示命令行窗口。\n"
        "- 默认按 Alt+V 开始听写，再按一次停止；可在设置页修改快捷键。\n"
        "- 请先把光标放入目标输入框，再按快捷键开始。\n"
        "- 设置页可调整悬浮窗、界面字体、提示音和开机启动。\n\n"
        "【可选二次校对】\n"
        "设置 → 识别与校对 → 下载校对模型（约 1.1 GB）。下载完成后才能开启二次校对。\n"
        "语音识别、标点恢复和二次校对全部在本机执行，不会上传录音或听写内容。\n\n"
        "【检查更新】\n"
        "设置 → 识别与校对 → 检查更新。程序会校验下载文件后安装并自动重启。\n\n"
        "【排查问题】\n"
        "- 可从设置页或托盘菜单打开“运行输出”。\n"
        "- 高级调试可运行：run.bat --debug\n"
        "- 若快捷键在管理员权限窗口中无响应，请以相同权限运行 voice2text。\n\n"
        "【Agent 排查】\n"
        "分发包根目录的 AGENTS.md 包含排查步骤与反馈导出方法；可生成反馈.md 和修复.diff，"
        "无需 Git，发送前请检查隐私信息。\n\n"
        "项目主页：https://github.com/cenglin123/voice2text\n"
        "问题反馈：https://github.com/cenglin123/voice2text/issues\n"
    )


def _copy_runtime_files(stage: Path) -> None:
    for rel in TEXT_FILES + ASSET_FILES + SCRIPT_FILES + PACKAGE_FILES:
        source = ROOT / rel
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(AGENT_GUIDE_SOURCE, stage / "AGENTS.md")
    (stage / "config.json").write_text(
        json.dumps(_default_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (stage / "安装说明.txt").write_text(_installation_guide(False), encoding="utf-8")


def _write_source_baseline(stage: Path) -> None:
    """给分发端反馈工具保留可编辑源码原样，绝不纳入配置、模型和运行时。"""
    with zipfile.ZipFile(stage / "source-baseline.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted((*TEXT_FILES, *SCRIPT_FILES, *PACKAGE_FILES, "AGENTS.md")):
            info = zipfile.ZipInfo(rel, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (stage / rel).read_bytes())


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
        _write_source_baseline(stage)
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
            (stage / "安装说明.txt").write_text(_installation_guide(True), encoding="utf-8")
        _validate_stage(stage, offline=runtime is not None)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(path.relative_to(stage.parent).as_posix(), (2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    (output_dir / "安装说明.txt").write_text(
        _installation_guide(runtime is not None), encoding="utf-8",
    )
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

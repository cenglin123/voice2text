#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在安装目录创建无控制台窗口、带程序图标的用户启动快捷方式。"""
from __future__ import annotations

import sys
from pathlib import Path


def shortcut_spec(root: Path, interpreter: Path) -> dict[str, str]:
    """返回固定的快捷方式属性，供创建逻辑和发行回归共用。"""
    root = root.resolve()
    pythonw = interpreter.resolve().with_name("pythonw.exe")
    return {
        "path": str(root / "启动 voice2text.lnk"),
        "target": str(pythonw),
        "arguments": f'-I "{root / "run_gui.pyw"}"',
        "working_directory": str(root),
        "icon": f'{root / "voice2text.ico"},0',
        "description": "启动 voice2text 语音输入",
    }


def create_shortcut(root: Path, interpreter: Path) -> Path:
    spec = shortcut_spec(root, interpreter)
    pythonw = Path(spec["target"])
    icon = root.resolve() / "voice2text.ico"
    if not pythonw.is_file():
        raise FileNotFoundError(f"pythonw.exe is missing: {pythonw}")
    if not icon.is_file():
        raise FileNotFoundError(f"Application icon is missing: {icon}")

    import win32com.client

    shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(spec["path"])
    shortcut.TargetPath = spec["target"]
    shortcut.Arguments = spec["arguments"]
    shortcut.WorkingDirectory = spec["working_directory"]
    shortcut.IconLocation = spec["icon"]
    shortcut.Description = spec["description"]
    shortcut.Save()
    return Path(spec["path"])


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: create_shortcut.py <python.exe>")
        return 2
    root = Path(__file__).resolve().parent.parent
    shortcut = create_shortcut(root, Path(sys.argv[1]))
    print("  Launch shortcut created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

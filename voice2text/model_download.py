"""用户主动触发的可选校对模型安装；与听写推理解耦。"""
from __future__ import annotations

import os
import re
from pathlib import Path
import subprocess
import sys
import threading

from voice2text.config import PROJECT_ROOT


class ModelDownload:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._message = ""
        self._process: subprocess.Popen | None = None
        self._closing = False

    def snapshot(self) -> tuple[bool, str]:
        with self._lock:
            return self._active, self._message

    def start(self, destination: Path) -> bool:
        with self._lock:
            if self._active or self._closing:
                return False
            self._active, self._message = True, "正在连接下载源…"
        threading.Thread(target=self._run, args=(destination,), daemon=True).start()
        return True

    def _run(self, destination: Path) -> None:
        try:
            with self._lock:
                if self._closing:
                    return
                self._process = subprocess.Popen(
                    [sys.executable, "-X", "utf8", "-u", str(PROJECT_ROOT / "scripts/download_models.py"),
                     "--only", "llm", "--llm-dest", str(destination)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace", cwd=PROJECT_ROOT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                process = self._process
            for line in process.stdout:
                line = line.strip()
                if line:
                    with self._lock:
                        progress = re.search(r"(\d+)%\s+([^\s]+/[^\s]+)", line)
                        self._message = (f"下载中 {progress[1]}% · {progress[2]}" if progress
                                         else "正在下载或切换下载源…")
            code = process.wait()
            with self._lock:
                self._message = ("下载完成，可开启二次校对并保存" if code == 0 and destination.is_file()
                                 else "下载未完成，点击重试；已下载部分会保留")
        except Exception as exc:
            with self._lock:
                self._message = f"下载失败：{exc}"
        finally:
            with self._lock:
                self._active = False
                self._process = None

    def close(self) -> None:
        with self._lock:
            self._closing = True
            process = self._process
        if process is not None and process.poll() is None:
            def terminate() -> None:
                try:
                    if os.name == "nt":
                        # 同时结束下载器可能启动的 curl，不留下后台下载进程。
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                    else:
                        process.terminate()
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f"[警告] 停止模型下载失败：{exc}")
            # 非 daemon：正常退出时等待清理，但不阻塞 Tk 与听写关闭路径。
            threading.Thread(target=terminate, daemon=False).start()


model_download = ModelDownload()

"""用户主动触发的 GitHub Release 自包含更新。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import uuid
import zipfile

from voice2text import __version__
from voice2text.config import PROJECT_ROOT

REPOSITORY = "cenglin123/voice2text"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_ASSET = re.compile(r"voice2text-v(?P<version>\d+\.\d+\.\d+)-windows-x64\.zip$")
AUTO_CHECK_INTERVAL = 86400.0


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError(f"不支持的版本号：{value}")
    return tuple(map(int, match.groups()))


def select_assets(release: dict) -> tuple[str, str, str]:
    version = str(release.get("tag_name", "")).removeprefix("v")
    version_tuple(version)
    expected = f"voice2text-v{version}-windows-x64.zip"
    urls = {str(item.get("name")): str(item.get("browser_download_url"))
            for item in release.get("assets", [])}
    if expected not in urls or expected + ".sha256" not in urls:
        raise ValueError("最新版本缺少 Windows x64 ZIP 或 SHA-256 文件")
    for url in (urls[expected], urls[expected + ".sha256"]):
        if not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/"):
            raise ValueError("更新资产不是固定 GitHub Release 地址")
    return version, urls[expected], urls[expected + ".sha256"]


def validate_archive(path: Path, version: str) -> None:
    prefix = f"voice2text-v{version}-windows-x64/"
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if not names or len(names) > 100_000:
            raise ValueError("更新压缩包为空或文件数异常")
        if sum(item.file_size for item in infos) > 6 * 1024 ** 3:
            raise ValueError("更新压缩包展开后体积异常")
        for item in infos:
            name = item.filename
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or not name.startswith(prefix):
                raise ValueError("更新压缩包包含不安全路径或多个根目录")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("更新压缩包不得包含符号链接")
        required = {
            prefix + "offline-bundle.txt",
            prefix + "run.bat",
            prefix + "voice2text/__init__.py",
            prefix + "runtime/python/python.exe",
        }
        if not required.issubset(names):
            raise ValueError("更新压缩包不是完整的自包含分发版")
        if archive.testzip() is not None:
            raise ValueError("更新压缩包损坏")
        init_text = archive.read(prefix + "voice2text/__init__.py").decode("utf-8")
        if f'__version__ = "{version}"' not in init_text:
            raise ValueError("更新压缩包内部版本不一致")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class UpdateSnapshot:
    state: str = "idle"
    message: str = ""
    version: str = ""
    archive: Path | None = None


class UpdateManager:
    def __init__(self, project_root: Path = PROJECT_ROOT) -> None:
        self.project_root = project_root
        self._lock = threading.Lock()
        self._snapshot = UpdateSnapshot()
        self._active = False
        self._closing = False
        self._automatic = False
        self._installing = False
        self._ready_fingerprint: tuple[int, int] | None = None
        self._last_attempt_loaded = False
        self._last_attempt: float | None = None

    @property
    def supported(self) -> bool:
        return (self.project_root / "offline-bundle.txt").is_file()

    def snapshot(self) -> UpdateSnapshot:
        with self._lock:
            return self._snapshot

    def _set(self, **values) -> None:
        with self._lock:
            if self._closing:
                return
            current = self._snapshot.__dict__.copy()
            current.update(values)
            self._snapshot = UpdateSnapshot(**current)

    def _attempt_path(self) -> Path:
        root = str(self.project_root.resolve()).casefold().encode("utf-8", errors="surrogatepass")
        key = hashlib.sha256(root).hexdigest()
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "voice2text" / "updates"
        return folder / f"auto-{key}.json"

    def _read_last_attempt(self) -> float | None:
        try:
            value = json.loads(self._attempt_path().read_text(encoding="utf-8"))
            timestamp = value.get("last_attempt") if isinstance(value, dict) else None
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                return None
            timestamp = float(timestamp)
            return timestamp if math.isfinite(timestamp) and timestamp >= 0 else None
        except (OSError, ValueError, TypeError, UnicodeError):
            return None

    def _write_last_attempt(self, timestamp: float) -> None:
        path = self._attempt_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps({"last_attempt": timestamp}), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            # Persistence is best-effort; a read-only profile must not block updates.
            pass

    def start(self, automatic: bool = False) -> bool:
        with self._lock:
            if self._active or self._closing or self._installing or self._snapshot.state == "ready":
                return False
            if not self.supported:
                self._snapshot = UpdateSnapshot("unsupported", "仅自包含安装版支持一键更新")
                return False
            self._active = True
            self._automatic = automatic
            if not automatic:
                self._last_attempt = time.time()
                self._last_attempt_loaded = True
                self._write_last_attempt(self._last_attempt)
            self._snapshot = UpdateSnapshot("checking", "正在检查 GitHub 最新版本…")
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def tick_auto(self, enabled: bool, busy: bool, now: float | None = None) -> UpdateSnapshot | None:
        """在 GUI 主线程轮询；只启动后台检查或领取已验证的自动更新包。"""
        if not enabled:
            return None
        timestamp = now if now is not None else time.time()
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or not math.isfinite(timestamp) or timestamp < 0:
            timestamp = time.time()
        with self._lock:
            if self._closing or self._installing or not self.supported:
                return None
            if self._snapshot.state == "ready":
                return self._snapshot if self._automatic and not busy else None
            if self._active:
                return None
            if not self._last_attempt_loaded:
                self._last_attempt = self._read_last_attempt()
                self._last_attempt_loaded = True
            last_attempt = self._last_attempt
            # A clock rollback invalidates the saved future timestamp instead of
            # suppressing checks indefinitely.
            if last_attempt is not None and timestamp >= last_attempt and timestamp - last_attempt < AUTO_CHECK_INTERVAL:
                return None
            self._last_attempt = timestamp
            self._write_last_attempt(timestamp)
        return self._start_auto()

    def _start_auto(self) -> UpdateSnapshot | None:
        # start() owns state transitions and thread creation; the timestamp was
        # recorded first so a crash immediately after dispatch remains throttled.
        self.start(automatic=True)
        return None

    def begin_install(self, archive: Path, version: str) -> bool:
        with self._lock:
            if self._closing or self._installing or self._snapshot.state != "ready":
                return False
            if self._snapshot.archive != archive or self._snapshot.version != version:
                return False
            try:
                stat = archive.stat()
                fingerprint = (stat.st_size, stat.st_mtime_ns)
            except OSError as exc:
                fingerprint = None
                failure = f"更新包已不可用：{exc}"
            else:
                failure = "更新包在后台校验后发生变化，拒绝安装"
            if fingerprint is None or fingerprint != self._ready_fingerprint:
                self._snapshot = UpdateSnapshot("error", failure, version, archive)
                self._ready_fingerprint = None
                return False
            self._installing = True
            self._snapshot = UpdateSnapshot("installing", f"正在安装 v{version}…", version, archive)
            return True

    def install_failed(self, exc: Exception) -> None:
        with self._lock:
            if not self._installing:
                return
            self._installing = False
            current = self._snapshot
            self._snapshot = UpdateSnapshot("error", f"安装失败：{exc}", current.version, current.archive)

    @staticmethod
    def _open(url: str):
        request = urllib.request.Request(url, headers={
            "User-Agent": f"voice2text/{__version__}",
            "Accept": "application/vnd.github+json",
        })
        return urllib.request.urlopen(request, timeout=30)

    def _download(self, url: str, destination: Path, version: str) -> None:
        part = destination.with_suffix(destination.suffix + ".part")
        with self._open(url) as response, part.open("wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            if total > 2 * 1024 ** 3:
                raise ValueError("更新包下载体积异常")
            received = 0
            while True:
                if self._closing:
                    raise RuntimeError("更新下载已取消")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                if received > 2 * 1024 ** 3:
                    raise ValueError("更新包下载体积异常")
                if total:
                    self._set(message=f"正在下载 v{version} · {received * 100 // total}%")
        part.replace(destination)

    def _run(self) -> None:
        with self._lock:
            if self._closing:
                self._active = False
                return
        try:
            with self._open(API_URL) as response:
                release = json.load(response)
            if release.get("draft") or release.get("prerelease"):
                raise ValueError("拒绝安装草稿版或预发行版")
            latest = str(release.get("tag_name", "")).removeprefix("v")
            if version_tuple(latest) <= version_tuple(__version__):
                self._set(state="current", message=f"当前已是最新版本 v{__version__}", version=latest)
                return
            version, zip_url, sha_url = select_assets(release)
            folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "voice2text" / "updates"
            folder.mkdir(parents=True, exist_ok=True)
            archive = folder / f"voice2text-v{version}-windows-x64.zip"
            self._set(state="downloading", message=f"准备下载 v{version}…", version=version)
            self._download(zip_url, archive, version)
            with self._open(sha_url) as response:
                checksum_text = response.read(4096).decode("ascii", errors="strict")
            expected = checksum_text.split()[0].lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError("SHA-256 文件格式无效")
            actual = file_sha256(archive)
            if actual != expected:
                archive.unlink(missing_ok=True)
                raise ValueError("更新包 SHA-256 校验失败")
            validate_archive(archive, version)
            stat = archive.stat()
            with self._lock:
                if not self._closing:
                    self._ready_fingerprint = (stat.st_size, stat.st_mtime_ns)
                    self._snapshot = UpdateSnapshot("ready", f"v{version} 已下载并验证，可以安装", version, archive)
        except Exception as exc:
            with self._lock:
                if not self._closing:
                    self._snapshot = UpdateSnapshot("error", f"更新失败：{exc}")
        finally:
            with self._lock:
                self._active = False

    def close(self) -> None:
        with self._lock:
            self._closing = True
            if self._active:
                self._snapshot = UpdateSnapshot("idle", "更新下载已取消")


def launch_installer(archive: Path, version: str, process_id: int, *, prevalidated: bool = False) -> None:
    if not (PROJECT_ROOT / "offline-bundle.txt").is_file():
        raise RuntimeError("当前不是自包含安装版")
    if not prevalidated:
        validate_archive(archive, version)
    update_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "voice2text" / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    script = update_dir / f"apply-{uuid.uuid4().hex}.ps1"
    shutil.copy2(PROJECT_ROOT / "scripts" / "apply_update.ps1", script)
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    subprocess.Popen(
        [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
         "-File", str(script), "-Archive", str(archive), "-InstallDir", str(PROJECT_ROOT),
         "-ProcessId", str(process_id), "-Version", version],
        cwd=update_dir,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


update_manager = UpdateManager()

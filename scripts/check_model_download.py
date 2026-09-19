"""可选模型下载生命周期回归，不联网。"""
import io
import subprocess
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice2text.model_download import ModelDownload


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        destination = Path(tmp) / "optional.gguf"
        released = threading.Event()
        entered = threading.Event()

        class Process:
            stdout = io.StringIO("model: 50% 500MB/1GB\n")
            pid = 12345

            def wait(self):
                entered.set()
                assert released.wait(3)
                destination.write_bytes(b"downloaded model")
                return 0

            def poll(self):
                return 0

        manager = ModelDownload()
        with patch("voice2text.model_download.subprocess.Popen", return_value=Process()) as spawn:
            assert manager.start(destination)
            assert entered.wait(3)
            assert manager.snapshot()[0]
            assert not manager.start(destination), "不能重复创建下载进程"
            released.set()
            deadline = time.monotonic() + 3
            while manager.snapshot()[0] and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not manager.snapshot()[0]
            assert "下载完成" in manager.snapshot()[1]
            assert spawn.call_count == 1
        failed = ModelDownload()
        with patch("voice2text.model_download.subprocess.Popen", side_effect=OSError("test failure")):
            failed._run(destination)
        assert not failed.snapshot()[0] and "失败" in failed.snapshot()[1]
        failed.close()
        assert not failed.start(destination)
        # 活跃下载退出：OS 清理超时也不能向调用方抛出或阻塞上屏关闭。
        cleanup_called = threading.Event()
        active = ModelDownload()
        process = Process()
        process.poll = lambda: None
        active._process = process

        def cleanup_failure(*args, **kwargs):
            cleanup_called.set()
            raise subprocess.TimeoutExpired("taskkill", 10)

        with patch("voice2text.model_download.subprocess.run", side_effect=cleanup_failure):
            started = time.monotonic()
            active.close()
            assert time.monotonic() - started < 1
            assert cleanup_called.wait(3)
            assert not active.start(destination)
    print("PASS shared download state, duplicate prevention, success, failure and shutdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

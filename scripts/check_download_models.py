"""模型下载证书回退回归；不联网、不下载真实模型。"""
from pathlib import Path
import ssl
import tempfile
import urllib.error
from unittest.mock import patch

import download_models as dm


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "model.bin"
        error = urllib.error.URLError(ssl.SSLCertVerificationError("test certificate"))

        def curl_success(args, **kwargs):
            assert "--insecure" not in args and "-k" not in args
            assert kwargs["check"] is True
            Path(args[args.index("--output") + 1]).write_bytes(b"model-data")

        with patch.object(dm.urllib.request, "urlopen", side_effect=error), \
                patch.object(dm.shutil, "which", return_value="curl.exe"), \
                patch.object(dm.subprocess, "run", side_effect=curl_success) as run:
            assert dm.download(("https://example.invalid/model",), dest, min_bytes=10)
            assert dest.read_bytes() == b"model-data"
            assert run.call_count == 1
            dest.unlink()
            assert not dm.download(("https://example.invalid/model",), dest, min_bytes=20)
            assert not dest.exists()

        with patch.object(dm.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")), \
                patch.object(dm.subprocess, "run") as run:
            assert not dm.download(("https://example.invalid/model",), dest)
            run.assert_not_called()
    print("PASS certificate fallback, TLS validation, minimum size and network failure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

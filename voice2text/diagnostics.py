"""显式启用的内存诊断；不创建日志文件。"""
import hashlib
import json
import os
from pathlib import Path


def trace(stage: str, **values) -> None:
    if os.environ.get("VOICE2TEXT_DIAGNOSTICS") == "1":
        print("[诊断] " + stage + " " + json.dumps(values, ensure_ascii=False, default=str))


def fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]

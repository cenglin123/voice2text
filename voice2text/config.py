"""配置加载：config.json 与内置默认值合并，路径相对项目根解析。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "hotkey": "alt+v",
    "sample_rate": 16000,
    "endpoint_pause_seconds": 1.5,
    "proofread_enabled": True,
    "proofread_timeout_seconds": 10,
    "asr_model_dir": "models/asr/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
    "llm_model_path": "models/llm/Qwen3-1.7B-Q4_K_M.gguf",
    "debug_dump_wav": False,
    "non_editable_process_blacklist": [],
}


@dataclass
class AppConfig:
    hotkey: str
    sample_rate: int
    endpoint_pause_seconds: float
    proofread_enabled: bool
    proofread_timeout_seconds: float
    asr_model_dir: Path
    llm_model_path: Path
    debug_dump_wav: bool
    non_editable_process_blacklist: list = field(default_factory=list)

    def asr_file(self, name: str) -> Path:
        """识别模型目录下的文件路径。"""
        return self.asr_model_dir / name


def load_config(path: str | Path | None = None) -> AppConfig:
    """读取配置文件（缺省为项目根 config.json），与 DEFAULTS 按白名单键合并后返回。

    配置文件不存在时直接使用默认值——工具应当零配置可用。
    配置文件损坏时同样回退默认值并给出警告，不让用户被 traceback 挡住。
    """
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.json"
    merged = dict(DEFAULTS)
    if cfg_path.exists():
        try:
            user_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not isinstance(user_cfg, dict):
                print(f"[警告] 配置文件不是 JSON 对象，使用默认配置：{cfg_path}")
                user_cfg = {}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[警告] 配置文件解析失败（{exc}），使用默认配置：{cfg_path}")
            user_cfg = {}
        merged.update({k: v for k, v in user_cfg.items() if k in DEFAULTS})

    return AppConfig(
        hotkey=str(merged["hotkey"]),
        sample_rate=int(merged["sample_rate"]),
        endpoint_pause_seconds=float(merged["endpoint_pause_seconds"]),
        proofread_enabled=bool(merged["proofread_enabled"]),
        proofread_timeout_seconds=float(merged["proofread_timeout_seconds"]),
        asr_model_dir=_resolve(merged["asr_model_dir"]),
        llm_model_path=_resolve(merged["llm_model_path"]),
        debug_dump_wav=bool(merged["debug_dump_wav"]),
        non_editable_process_blacklist=list(merged["non_editable_process_blacklist"]),
    )


def _resolve(p: str) -> Path:
    """相对路径统一解析到项目根，避免受启动目录影响。"""
    path = Path(p)
    return path if path.is_absolute() else PROJECT_ROOT / path

"""程序入口。阶段 1 为占位实现：加载配置、检查模型就绪状态后退出。

后续阶段在此挂接热键监听、音频采集、识别与校对循环。
"""

from __future__ import annotations

import sys

from voice2text import __version__
from voice2text.config import AppConfig, load_config

ASR_REQUIRED_FILES = (
    "encoder-epoch-99-avg-1.onnx",
    "decoder-epoch-99-avg-1.onnx",
    "joiner-epoch-99-avg-1.onnx",
    "tokens.txt",
)


def check_models(cfg: AppConfig) -> bool:
    """检查识别与校对模型文件是否就位（安装脚本跑完即应通过）。"""
    ok = True
    for name in ASR_REQUIRED_FILES:
        if not cfg.asr_file(name).is_file():
            print(f"  [缺失] ASR 模型文件: {cfg.asr_file(name)}")
            ok = False
    if not cfg.llm_model_path.is_file():
        print(f"  [缺失] 校对模型文件: {cfg.llm_model_path}")
        ok = False
    return ok


def main() -> int:
    cfg = load_config()
    print(f"voice2text v{__version__}")
    print(f"  热键: {cfg.hotkey} | 采样率: {cfg.sample_rate}Hz | 停顿阈值: {cfg.endpoint_pause_seconds}s")
    print(f"  二次校对: {'开' if cfg.proofread_enabled else '关'} | 超时: {cfg.proofread_timeout_seconds}s")
    if check_models(cfg):
        print("  模型就绪")
        print("（阶段 1 占位入口：完整功能在后续阶段接入）")
        return 0
    print("  模型未就绪：请先运行 install.bat")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""离线安装检查；只加载本地组件，不进行任何下载。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    import tkinter
    import sherpa_onnx
    import llama_cpp
    import sounddevice
    import keyboard
    import uiautomation
    import pystray
    import pyperclip
    import pythoncom
    import win32clipboard
    from voice2text.config import load_config
    from voice2text.asr import StreamingASR
    from voice2text.punctuation import PunctuationRestorer
    cfg = load_config()
    print("All dependencies imported OK", flush=True)
    # 验证模型实际可加载，而不只检查文件是否存在。
    asr = StreamingASR(cfg)
    punctuation = PunctuationRestorer(cfg)
    print("ASR and punctuation models loaded OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

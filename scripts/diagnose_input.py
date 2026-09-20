"""固定文本注入探针：无模型、不发送 Enter；仅用户主动运行时写入前台输入框。"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["VOICE2TEXT_DIAGNOSTICS"] = "1"

from voice2text.diagnostics import trace, fingerprint
from voice2text.target import InputTarget
from voice2text.keysender import send_text_slow


def main():
    print("请在 5 秒内聚焦空白测试输入框；将输入固定诗句，不会发送消息。")
    time.sleep(5)
    target = InputTarget.capture(set())
    trace("probe_target", build=fingerprint(), snapshot=target.diagnostic_snapshot())
    def guard():
        if not target.focused():
            raise RuntimeError("焦点校验失败：" + str(target.diagnostic_snapshot()))
    text = "锄禾日当午，汗滴禾下土，谁知盘中餐，粒粒皆辛苦。"
    trace("probe_expected", text=text)
    send_text_slow(text, guard=guard)
    print("注入调用完成；请核对屏幕文字。此处不代表编辑器已正确接收。")


if __name__ == "__main__":
    main()

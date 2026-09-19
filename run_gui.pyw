"""无控制台启动入口（开机自启动 / 双击启动用）。

由 pythonw 执行：脚本目录即项目根（sys.path[0]），配置与模型路径按项目根解析。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voice2text.desktop import install_output

output = install_output()
try:
    from voice2text.main import main
    sys.exit(main(output))
except Exception:
    import ctypes
    import traceback
    traceback.print_exc()
    ctypes.windll.user32.MessageBoxW(None, output.snapshot()[1][-3000:], "voice2text 启动失败", 0x10)
    raise

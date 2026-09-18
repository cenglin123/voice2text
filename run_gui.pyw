"""无控制台启动入口（开机自启动 / 双击启动用）。

由 pythonw 执行：脚本目录即项目根（sys.path[0]），配置与模型路径按项目根解析。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from voice2text.main import main

sys.exit(main())

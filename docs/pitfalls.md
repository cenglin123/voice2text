# 已知环境陷阱

> 记录踩过的、代码里看不出来的坑。新条目按"现象 / 原因 / 规避"三段写。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## Windows

- **keyboard 全局热键与 UIPI**：普通用户权限即可安装低级键盘钩子；真正的限制是 UIPI——焦点位于管理员权限窗口（任务管理器、管理员 CMD 等）时收不到热键。规避：不做默认提权；仅在用户需要在管理员窗口内听写时建议以管理员运行；首次启动引导按一次 Alt+V 做可达性自检。
- **Windows Store 假 python.exe**：未装 Python 的机器上 `python` 命令可能命中 Store 别名（拉起商店而非运行）。规避：install.bat 检测时识别假别名，缺失则下载 Windows embeddable Python 到 runtime/。
- **中文上屏不能走模拟键击**：会触发/经过输入法产生二次转换。规避：剪贴板 + Ctrl+V 粘贴。
- **控制台中文乱码**：Windows 控制台默认 GBK。规避：Python 端统一 UTF-8（`PYTHONUTF8=1`），脚本输出避免依赖代码页。

## 模型相关

- **llama-cpp-python 无 PyPI wheel**：PyPI 只发布 sdist，pip 默认安装会在 Windows 触发源码编译（需要 MSVC，极慢且常失败）。规避：`--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/` 安装预编译 wheel（0.3.35 起 wheel 标签为 `py3-none-win_amd64`）；发行包随包携带 wheel，不长期依赖该第三方索引。
- **sherpa-onnx funasr-nano int8 量化版转写文字重复**（k2-fsa/sherpa-onnx issue #3066）：规避：用非 int8 版本或流式 Zipformer。
- **Qwen3 系列默认开启思考模式**：输出带 `<think>` 段、延迟暴涨，破坏固定格式解析。规避：chat template 传 `enable_thinking=False` 或 prompt 追加 `/no_think`。
- **sherpa-onnx `get_result()` 返回累计假设而非增量**：解码中尾部文本会自我修正，当 delta 逐次上屏会出现重复错乱。规避：以句为单位整句刷新（退格 + 重粘），endpoint 后锁句。

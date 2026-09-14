# 已知环境陷阱

> 记录踩过的、代码里看不出来的坑。新条目按"现象 / 原因 / 规避"三段写。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## Windows

- **embeddable Python 隔离模式不含 cwd**：存在 `._pth` 文件时 Python 进入隔离模式，sys.path 只有 runtime 目录、pythonXX.zip 和 site-packages——`import voice2text`、`python -m voice2text.main` 都会失败。规避：`._pth` 追加 `import site` 启用 site-packages，并追加 `..\..` 把项目根加入 sys.path（相对路径以 `._pth` 所在目录为基准）。
- **用户 AppData site-packages 污染 runtime**：`import site` 生效后用户 Roaming 目录（`AppData\Roaming\Python\Python311\site-packages`）也会进 sys.path，装过其他 Python 3.11 包的机器上旧版本 numpy 等可能遮蔽 runtime 内的版本。规避：install.bat / run.bat 设置 `PYTHONNOUSERSITE=1`。
- **keyboard 全局热键与 UIPI**：普通用户权限即可安装低级键盘钩子；真正的限制是 UIPI——焦点位于管理员权限窗口（任务管理器、管理员 CMD 等）时收不到热键。规避：不做默认提权；仅在用户需要在管理员窗口内听写时建议以管理员运行；首次启动引导按一次 Alt+V 做可达性自检。
- **Windows Store 假 python.exe**：未装 Python 的机器上 `python` 命令可能命中 Store 别名（拉起商店而非运行）。规避：install.bat 检测时识别假别名，缺失则下载 Windows embeddable Python 到 runtime/。
- **Git Bash 与 cmd 的 tar 不是同一个**：Git Bash 的 GNU tar 不认 zip；cmd 下 `tar` 是 System32 bsdtar（Win10 1803+ 自带），可解 zip。规避：开发期在 Git Bash 手动测试解压用 `/c/Windows/System32/tar.exe`。
- **中文上屏不能走模拟键击**：会触发/经过输入法产生二次转换。规避：剪贴板 + Ctrl+V 粘贴。
- **控制台中文乱码**：Windows 控制台默认 GBK。规避：Python 端统一 UTF-8（`PYTHONUTF8=1`），脚本输出避免依赖代码页。

## 模型相关

- **sherpa-onnx 1.13.x 模块改名**：Python 包由 `sherpa.onnx` 改为 `sherpa_onnx`（新布局 sherpa-onnx + sherpa-onnx-core），旧示例代码的 `import sherpa.onnx` 会报 No module named 'sherpa'。规避：用 `import sherpa_onnx`。
- **Qwen 官方 GGUF 仓只有 Q8_0**：`Qwen/Qwen3-1.7B-GGUF` 不含 Q4_K_M；Q4_K_M 用 unsloth 仓（HF/hf-mirror/ModelScope 三路可达）。
- **llama-cpp-python 无 PyPI wheel**：PyPI 只发布 sdist，pip 默认安装会在 Windows 触发源码编译（需要 MSVC，极慢且常失败）。规避：`--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/` 安装预编译 wheel（wheel 实际托管在 GitHub Releases，索引页只是目录）；发行包随包携带 wheel，不长期依赖该第三方索引。
- **sherpa-onnx funasr-nano int8 量化版转写文字重复**（k2-fsa/sherpa-onnx issue #3066）：规避：用非 int8 版本或流式 Zipformer。
- **Qwen3 系列默认开启思考模式**：输出带 `<think>` 段、延迟暴涨，破坏固定格式解析。规避：chat template 传 `enable_thinking=False` 或 prompt 追加 `/no_think`。
- **sherpa-onnx `get_result()` 返回累计假设而非增量**：解码中尾部文本会自我修正，当 delta 逐次上屏会出现重复错乱。规避：以句为单位整句刷新（退格 + 重粘），endpoint 后锁句。

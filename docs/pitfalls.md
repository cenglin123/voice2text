# 已知环境陷阱

> 记录踩过的、代码里看不出来的坑。新条目按"现象 / 原因 / 规避"三段写。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## Windows

- **keyboard 全局热键可能失效**：普通用户权限下 keyboard 库的低级键盘钩子可能被 UAC/权限拦截。规避：以管理员运行，或安装时授予；程序启动时自检热键是否可达并提示。
- **中文上屏不能走模拟键击**：会触发/经过输入法产生二次转换。规避：剪贴板 + Ctrl+V 粘贴。
- **控制台中文乱码**：Windows 控制台默认 GBK。规避：Python 端统一 UTF-8（`PYTHONUTF8=1`），脚本输出避免依赖代码页。

## 模型相关

- **sherpa-onnx funasr-nano int8 量化版转写文字重复**（k2-fsa/sherpa-onnx issue #3066）：规避：用非 int8 版本或换流式 Zipformer。
- **llama-cpp-python 源码编译陷阱**：无预编译 wheel 时安装会尝试本地编译，需要 MSVC 且耗时极长。规避：requirements.txt 固定有 wheel 的版本；install.bat 检测失败给出明确提示。

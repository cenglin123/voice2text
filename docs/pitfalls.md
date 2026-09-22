# 已知环境陷阱

> 记录踩过的、代码里看不出来的坑。新条目按"现象 / 原因 / 规避"三段写。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## Windows

- **sounddevice 回调缓冲区仅在回调返回前有效**：`indata` 是 PortAudio 内部缓冲区的视图，入队必须 `copy()`；单声道时 `np.ascontiguousarray(indata[:, 0])` 返回视图不拷贝，是隐蔽的悬垂引用。规避：显式 `.copy()`（官方示例 rec_unlimited.py 同款写法）。
- **向提权窗口注入会被 UIPI 静默吞掉，但识别、剪贴板和 SendInput 全部"成功"**：非提权进程对管理员窗口的 SendInput 被系统丢弃、OpenClipboard 照常成功，所有性能指标 ok，目标窗口却一个字不出现——日志完全无法区分"输入成功"和"被吞"。内置 Administrator 账户若开启 FilterAdministratorToken，本软件默认也是普通权限，而"终端(管理员)"是提权实例，属于必现场景。规避：捕获目标阶段同时检查顶层 PID 与实际焦点 PID 的令牌提权状态，任一明确失配即拒绝开始并指引以管理员重启；根除注入本身仍需程序提权。
- **焦点切出编辑框后同句继续粘贴会重复上屏**：partial 已在框内，焦点切回后若继续整句刷新会再贴一遍。规避：脱管机制——焦点离开后本句剩余 partial 全部跳过（牺牲脱管句后半段，保记账正确）。
- **键盘事件注入在开发沙箱中不可靠**：ZCode 沙箱会话里 keybd_event/SendInput 注入的按键大部分事件丢失、原生 ctypes 低级钩子安装失败——keyboard 库代码本身正常。规避：热键相关自动化测试只测状态机（直接调回调），真人按键验证放用户验收。
- **PowerShell 5.1 读 UTF-8 脚本需 BOM**：无 BOM 的 UTF-8 ps1 会被按 GBK 解析成乱码。规避：`encoding='utf-8-sig'` 写 ps1；另注意 Windows python 与 Git Bash 的 `/tmp` 不是同一目录，跨工具传文件用显式 Windows 路径。
- **embeddable Python 隔离模式不含 cwd**：存在 `._pth` 文件时 Python 进入隔离模式，sys.path 不含项目根。规避：`._pth` 追加 `import site` + 项目根路径（相对 `._pth` 所在目录）。现 runtime 已改用 python-build-standalone（普通布局无此问题），此条保留给仍需 embeddable zip 的场景。
- **用户 AppData site-packages 污染 runtime**：`import site` 生效后用户 Roaming 目录（`AppData\Roaming\Python\Python311\site-packages`）也会进 sys.path，装过其他 Python 3.11 包的机器上旧版本 numpy 等可能遮蔽 runtime 内的版本。规避：install.bat / run.bat 设置 `PYTHONNOUSERSITE=1`。
- **keyboard 全局热键与 UIPI**：普通用户权限即可安装低级键盘钩子；UIPI 的已确认故障点是非提权进程向管理员目标发送输入会被静默丢弃。规避：目标捕获时检查权限并拒绝失配；仅在用户确实需要向管理员窗口听写时建议以管理员运行本软件，不做默认提权。
- **Windows Store 假 python.exe**：未装 Python 的机器上 `python` 命令可能命中 Store 别名（拉起商店而非运行）。规避：install.bat 检测时识别假别名，缺失则下载独立 CPython（python-build-standalone）到 runtime/。
- **Git Bash 与 cmd 的 tar 不是同一个**：Git Bash 的 GNU tar 不认 zip；cmd 下 `tar` 是 System32 bsdtar（Win10 1803+ 自带），可解 zip。规避：开发期在 Git Bash 手动测试解压用 `/c/Windows/System32/tar.exe`。
- **普通键击会被输入法转义，Qt 微信又会错误接收 VK_PACKET**：合成普通字母键会进入中文输入法组合框；SendInput KEYEVENTF_UNICODE 通常能绕过输入法，但微信 `Qt51514QWindowIcon` 真机把正确注入文本变成重复标点和丢字。微信使用受保护 Ctrl+V，Windows Terminal 使用受保护 Ctrl+Shift+V；事务以 clipboard sequence 保护并发复制，刷新 partial 时必须先完成快照和临时发布、再删除旧字。其他应用仍默认 VK_PACKET。
- **WPS 顶层窗口和编辑控件可能跨进程**：真机快照中 WPS 顶层 `OpusApp` 与实际 `EXCEL6` 焦点分别属于不同 PID。目标捕获必须同时记录顶层身份和捕获时编辑进程，后续只允许这两个 PID；不能用“焦点必须与顶层同进程”作为恢复条件。
- **控制台中文乱码**：Windows 控制台默认 GBK。规避：Python 端统一 UTF-8（`PYTHONUTF8=1`），脚本输出避免依赖代码页。

## 模型相关

- **sherpa-onnx 1.13.x 模块改名**：Python 包由 `sherpa.onnx` 改为 `sherpa_onnx`（新布局 sherpa-onnx + sherpa-onnx-core），旧示例代码的 `import sherpa.onnx` 会报 No module named 'sherpa'。规避：用 `import sherpa_onnx`。
- **Qwen 官方 GGUF 仓只有 Q8_0**：`Qwen/Qwen3-1.7B-GGUF` 不含 Q4_K_M；Q4_K_M 用 unsloth 仓（HF/hf-mirror/ModelScope 三路可达）。
- **llama-cpp-python 无 PyPI wheel**：PyPI 只发布 sdist，pip 默认安装会在 Windows 触发源码编译（需要 MSVC，极慢且常失败）。规避：`--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/` 安装预编译 wheel（wheel 实际托管在 GitHub Releases，索引页只是目录）；发行包随包携带 wheel，不长期依赖该第三方索引。
- **sherpa-onnx funasr-nano int8 量化版转写文字重复**（k2-fsa/sherpa-onnx issue #3066）：规避：用非 int8 版本或流式 Zipformer。
- **Qwen3 系列默认开启思考模式**：输出带 `<think>` 段、延迟暴涨，破坏固定格式解析。规避：chat template 传 `enable_thinking=False` 或 prompt 追加 `/no_think`。
- **sherpa-onnx `get_result()` 返回累计假设而非增量**：解码中尾部文本会自我修正，当 delta 逐次上屏会出现重复错乱。规避：以句为单位整句刷新（退格 + 重粘），endpoint 后锁句。

## GUI 相关

- **embeddable zip 与 nuget 包都不带 tkinter**：GUI 依赖 tkinter，两者装出来 import 即败（nuget 包连 tcl/tk 目录都没有，实测）。规避：runtime 用 python-build-standalone 的 install_only 包（自带 tcl/tk，解压即得 runtime/python）。
- **cmd 的 move 通配符不移动子目录**：`move dir\* dest` 只搬顶层文件且返回 0（静默失败）。规避：整目录 rename 或 robocopy /E /MOVE。
- **pythonw 下 sys.stdout/stderr 为 None**：任何 print 都会 AttributeError。规避：main() 入口把 None 的标准流重定向到 devnull。
- **Tk geometry 与 ULW 位置竞争**：Tk 的 geometry 变更尚未处理时，ULW 读取旧坐标重绘可撤销移动；先 update_idletasks 再呈现。ULW 自行保留窗口表面，不在 Expose 中重贴旧帧。拖动仍须通过同一透明度处理路径。
- **原生模糊不遵循 ULW 透明像素轮廓**：只给像素 alpha 裁圆角会在四角留下矩形模糊底；须同步 SetWindowRgn。成功后 HRGN 归系统所有，失败由调用方释放，回退时清除区域与模糊。

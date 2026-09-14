---
status: in_progress
mode: phased
coordinator: ""
created_at: 2026-09-15
---

# voice2text MVP 开发计划

## 任务分配表

| 任务 / 阶段 | Owner | 状态 | Reviewer | 备注 |
|------------|-------|------|----------|------|
| 阶段 1：项目骨架 + 一键安装 | 主 Agent | ✅ completed | 审计子代理（两轮） | requirements / install.bat / 模型下载 |
| 阶段 2：热键 + 音频采集 | 主 Agent | ✅ completed | 独立 reviewer 子代理（两轮） | Alt+V 开关、麦克风 PCM 流 |
| 阶段 3：流式识别 + 实时上屏 | 主 Agent | queue | 待定 | sherpa-onnx 集成、UIA 检测、partial 刷新 |
| 阶段 4：停顿检测 + 二次校对 | 主 Agent | queue | 待定 | Qwen GGUF 校对替换、停止时终校 |
| 阶段 5：打磨 + 分发验证 | 主 Agent | queue | 待定 | 干净环境验证、异常处理、托盘 |

## 目标

交付可分发的 Windows 语音听写工具：Alt+V 开始/停止，流式识别文字实时输入到光标所在文本框，说话停顿后本地小模型校对并替换。全程离线，install.bat 一键安装（含 Python 本体自包含）。

## 阶段划分

### 阶段 1：项目骨架 + 一键安装
- **目标**：建立 Python 包结构、锁定全部运行依赖（含阶段 5 托盘依赖）、install.bat 可在无 Python 的干净 Windows 机器拉起环境并下载两个模型到 models/；提供最小 main 占位
- **涉及文件**：requirements.txt、install.bat、run.bat、config.json、.gitignore、voice2text/__init__.py、voice2text/main.py（占位：加载 config 打印后退出）、voice2text/config.py、scripts/download_models.py
- **关键实现约束**：
  - Python 本体自包含：install.bat 检测本机 Python 3.10+（识别并跳过 Windows Store 假 python.exe），缺失则下载 Windows embeddable Python zip 解压到 runtime/ 使用
  - llama-cpp-python 固定 0.3.35，从作者 wheel 索引安装：`--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu`（PyPI 只有 sdist，装了必触发源码编译）；发行打包时把 wheel 随包携带，不长期依赖第三方个人索引
  - 识别模型钉死：`sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20`（GitHub release asr-models tag，ModelScope `pengzhendong/sherpa-onnx-streaming-zipformer-bilingual-zh-en` 镜像 fallback）
  - 校对模型钉死：`Qwen3-1.7B` Q4_K_M GGUF（HuggingFace `Qwen/Qwen3-1.7B-GGUF`，ModelScope 同名镜像 fallback）
  - requirements.txt 一次锁定全部运行依赖（sherpa-onnx、sounddevice、keyboard、uiautomation、pystray、pywin32、pyperclip 等），后续阶段新增依赖须更新 requirements 并重验安装
- **验证标准**：
  1. 无 Python 的干净机器（含仅装 Store 假 python 的机器）执行 install.bat 成功：runtime 就绪、依赖安装零源码编译、models/ 下出现双语 Zipformer 模型与 Qwen GGUF；断网 GitHub 场景 ModelScope fallback 生效
  2. `python -c "import voice2text"` 成功；run.bat 打印配置后正常退出
- **Owner**：主 Agent
- **Reviewer**：独立 reviewer 子代理
- **状态**：✅ completed
- **完成记录**：
  - 交付文件：requirements.txt（直接依赖全钉死实测版本）、install.bat、run.bat、config.json、voice2text/{__init__,config,main}.py（占位入口）、scripts/download_models.py
  - 实测（本机 venv 分支）：install.bat 全链路成功；依赖全 wheel 安装零编译；ASR tar.bz2 488MB 下载解压；GGUF 1.03GB 下载且 llama.cpp 1.1s 加载；run.bat exit 0
  - reviewer 第一轮结论 needs rework：blocker=embeddable Python 隔离模式（._pth 存在时 sys.path 不含 cwd，import voice2text 必败）；major=runtime 半成品死局（python.exe 在但 pip 缺失时重跑跳过 bootstrap）。已修复：._pth 追加 `import site` + `..\..`；就绪判定收紧为 python.exe+pip 双条件，get-pip 段可重入。另吸收 7 项 minor（venv 失败检查、全模块导入验证、get-pip 阿里镜像、坏 tarball 清理、config 损坏兜底、依赖钉版、run.bat 探活）
  - embeddable 分支修复后已实测走通（bsdtar 解压、_pth 生效、get-pip、依赖安装、全模块导入、main 正常退出）
  - reviewer 第二轮复核结论 pass with issues，阶段 1 判定通过；三个遗留项已当场修复并验证：A=venv 重建段补版本检查（3.9-only 机器不再死循环/毒化 run.bat）、B=[4/4] 验证补 pythoncom/win32clipboard（pywin32 的可导入名）、C=config 非对象 JSON 兜底；另加 PYTHONNOUSERSITE=1 隔离用户 AppData site-packages（embeddable 实测发现）
- **交接摘要**：
  - sherpa-onnx 1.13.8 的 Python 模块名是 `sherpa_onnx`（旧文档/示例中的 `sherpa.onnx` 已废弃）——阶段 3 按新名 import
  - Qwen3-1.7B Q4_K_M GGUF 实际来自 unsloth 仓（Qwen 官方 GGUF 仓只有 Q8_0）；三路源 HF→hf-mirror→ModelScope 均 200
  - llama wheel 实际托管在 GitHub Releases（abetlen 索引页只是目录），pip 经索引页可正常解析
  - Git Bash 里 `tar` 是 GNU tar 不认 zip；bat 在 cmd 下用 System32 bsdtar 正常——开发期手动测试要用 `/c/Windows/System32/tar.exe`
  - 阶段 2 开始前先读 voice2text/config.py（AppConfig 结构）与 AGENTS.md 硬约束

### 阶段 2：热键 + 音频采集
- **目标**：常驻进程监听全局 Alt+V，切换听写开/关；开启时采集麦克风 PCM 送入队列，关闭时停止采集并 flush；首次启动做热键可达性自检
- **涉及文件**：voice2text/main.py、voice2text/hotkey.py、voice2text/capture.py
- **关键实现约束**：
  - keyboard 库普通用户权限即可装钩子；UIPI 限制是焦点位于管理员权限窗口时收不到热键——权限提示按此事实设计，不默认提权
  - 热键可达性自检：首次启动引导用户按一次 Alt+V，10 秒未收到事件则提示"焦点在管理员窗口或热键被占用，可尝试以管理员运行"
  - 采集参数：优先 16kHz 单声道直接采集；设备不支持时按官方示例以 48kHz 采集再重采样到 16kHz
- **验证标准**：控制台可见开/关状态日志；采集 PCM 写入调试 wav 可正常播放（调试开关）；拔掉麦克风后程序不崩溃、给出友好提示；热键自检流程按上述判定逻辑触发
- **Owner**：主 Agent
- **Reviewer**：独立 reviewer 子代理
- **前置条件**：阶段 1 完成
- **状态**：✅ completed
- **完成记录**：
  - 交付：voice2text/hotkey.py（keyboard 钩子 + 首按自检 + Event 信号）、voice2text/capture.py（16k 直采/设备默认采样率回退重采样、回调→队列、调试 wav、看门狗）、main.py 常驻循环（toggle/drain/错误善后）
  - 已验证：重采样单测（8k→16k 保频）；回调管线→队列→调试 wav；启动无麦克风的 CaptureError 友好提示（真实触发，本机仅剩未连接的蓝牙幽灵设备）；主循环状态机（mock：开关/drain/CaptureError 不崩溃/采集中断善后/看门狗超时）
  - reviewer 第一轮 needs rework：blocker=直采路径入队 sounddevice 回调缓冲区视图（`ascontiguousarray` 单声道时不拷贝，阶段 3 会读到垃圾）→ 已改 `copy()` 并加别名回归测试；major=中途拔麦克风静默挂死 → 已加回调时间戳看门狗（3s 无回调报错停会话）。另修 4 项 minor（探测期采样率先赋值、stop/close 各自吞错、self_check 进 try、queue.Empty 精确捕获、调试 wav 落 PROJECT_ROOT），全部回归通过
  - 环境限制（已核实非代码问题）：本开发环境（ZCode 沙箱）注入按键大部分事件丢失（keybd_event/SendInput/computer-use 均试过，原生 ctypes LL 钩子安装失败），真人按 Alt+V 的端到端验证无法在本环境完成——**列入用户验收清单**
- **交接摘要**：
  - 阶段 3 挂接点：`DictationApp._drain()` 是替换点——改为把队列块喂识别线程；`MicrophoneCapture.queue` 以 None 哨兵标记流结束；`seconds_since_audio()` 可复用做停顿参考（但 endpoint 以 sherpa-onnx 自带检测为准）
  - 采集输出为 float32 单声道 16kHz ndarray 块（约 0.25s/块），与 sherpa-onnx `stream.accept_waveform` 的输入格式直接匹配
  - 真机麦克风测试同样受限于本机无可用输入设备（蓝牙耳机未连接），采集路径用合成音频验证；用户验收时连同热键一起真机过一遍

### 阶段 3：流式识别 + 实时上屏
- **目标**：sherpa-onnx 流式识别线程消费 PCM 队列；可编辑检测（UIAutomation）通过后，partial 文本整句刷新上屏，endpoint 锁句进入待校对队列；不可编辑时静默跳过
- **涉及文件**：voice2text/asr.py、voice2text/input.py、voice2text/main.py
- **关键实现约束**：
  - 可编辑检测用 `uiautomation` 取焦点控件：ControlType ∈ {Edit, Document} 或 ValuePattern 可写即视为可输入；查不到控件（自绘 UI，如部分 Qt/Electron 应用）时默认允许粘贴，config 黑名单可关停指定进程；pyautogui 无 UI introspection，不得用于检测
  - partial 上屏策略：sherpa-onnx `get_result()` 返回当前句累计假设文本（尾部会自我修正，非单调追加），不能当增量逐次粘贴。以句为单位整句刷新：退格删除本句已上屏 partial → 粘贴最新 partial；endpoint 触发后本句锁定，不再变动，进入校对队列
  - 剪贴板：MVP 只保存/恢复文本格式剪贴板（图片/文件列表不保证），写入文档
  - 中文上屏走剪贴板 + Ctrl+V 粘贴（模拟键击会被输入法拦截）
- **验证标准**：记事本/浏览器地址栏/微信输入框中说话，文字随说随出且无重复错乱；焦点在非编辑区（如桌面）说话不上屏不报错；UIA 查不到控件的典型应用（如某 Qt 应用）默认粘贴生效；停止后剪贴板文本内容恢复
- **Owner**：主 Agent
- **Reviewer**：待定
- **前置条件**：阶段 2 完成
- **状态**：queue
- **完成记录**：
- **交接摘要**：

### 阶段 4：停顿检测 + 二次校对
- **目标**：endpoint（停顿阈值约 1.5s）触发校对；llama-cpp-python 加载 Qwen GGUF 校对已锁定的句子；退格抹除原文并粘贴校对结果；Alt+V 停止时对尾部音频做最终识别 + 最终校对
- **涉及文件**：voice2text/proofread.py、voice2text/asr.py、voice2text/input.py、config.json
- **关键实现约束**：
  - Qwen3-1.7B 默认开启思考模式，校对 prompt 必须关闭（chat template `enable_thinking=False` 或 prompt 追加 `/no_think`），否则输出带 `<think>` 段且延迟暴涨
  - 延迟预算：单句校对超过 10s 则放弃校对、保留已上屏原文（超时跳过，不阻塞后续句子）
  - 校对期间识别继续，新句照常上屏；校对线程与识别线程独立
  - 停止语义：Alt+V 停止 → 对剩余音频执行 `input_finished()` 完成最终识别 → 尾句照常走一次校对 → 程序回到待命
- **验证标准**：说一段带"嗯、那个"的口语，停顿后上屏文本变为整洁书面语；说完立即按 Alt+V，尾句同样被校对；校对超时场景（模拟）跳过校对不卡死；替换无字符错位
- **Owner**：主 Agent
- **Reviewer**：待定
- **前置条件**：阶段 3 完成
- **状态**：queue
- **完成记录**：
- **交接摘要**：

### 阶段 5：打磨 + 分发验证
- **目标**：异常处理、系统托盘常驻 + 状态提示、中文 UTF-8 输出、临时文件清理、发行打包（含 wheel 随包）
- **涉及文件**：voice2text/main.py、voice2text/tray.py、install.bat、docs/*
- **关键实现约束**：新增依赖须更新 requirements.txt 并重验安装；发行包将 llama-cpp-python wheel 与模型下载脚本一起携带
- **验证标准**：
  1. 无 Python 的干净机器完整走 install → run → 记事本听写 → 校对替换 → 退出，全程可用
  2. 异常注入（拔麦克风/删模型目录/热键被占用）均有友好提示不崩溃
  3. 正常退出与强制结束进程后，均无残留临时音频文件（含调试 wav）
  4. CHANGELOG / overview / deployment 文档已同步
- **Owner**：主 Agent
- **Reviewer**：待定
- **前置条件**：阶段 4 完成
- **状态**：queue
- **完成记录**：
- **交接摘要**：

## 决策记录

- 2026-09-15：识别框架选 sherpa-onnx（原生流式、CPU 快、跨平台），校对模型选 Qwen3-1.7B Q4 GGUF + llama-cpp-python。详见 docs/overview.md「关键设计决策」。
- 2026-09-15：上屏方案定为剪贴板粘贴（中文模拟键击会被输入法拦截），保存/恢复用户文本剪贴板。
- 2026-09-15（审计修订）llama-cpp-python 的 PyPI 只有 sdist，Windows wheel 仅在作者索引 `https://abetlen.github.io/llama-cpp-python/whl/cpu/`（实测 0.3.35 有 `py3-none-win_amd64.whl`）。安装命令固定带 `--extra-index-url`，发行包直接随包携带 wheel。
- 2026-09-15（审计修订）Python 本体纳入自包含：无本机 Python 时 install.bat 下载 Windows embeddable Python 到 runtime/；需处理 Windows Store 假 python.exe 别名。
- 2026-09-15（审计修订）可编辑检测定案 uiautomation 库（焦点控件 ControlType/ValuePattern），查不到控件默认放行 + config 黑名单；放弃 pyautogui（无 UI introspection 能力）。
- 2026-09-15（审计修订）partial 上屏定案"整句刷新"：`get_result()` 是当前句累计假设（非单调 delta），以句为单位退格+重粘；endpoint 后锁句。若实测刷新抖动明显，降级方案为 endpoint 后整句上屏（验证标准同步放宽为"每句停顿后出字"）。
- 2026-09-15（审计修订）Qwen3-1.7B 校对必须关闭思考模式（`enable_thinking=False` / `/no_think`）；单句校对延迟预算 10s，超时放弃校对保留原文。
- 2026-09-15（审计修订）Alt+V 停止时对尾部音频做最终识别 + 最终校对，避免高频路径"漏校对"。
- 2026-09-15（审计修订）音频采集优先 16kHz 直采，设备不支持时 48kHz 采集 + 重采样（对齐 sherpa-onnx 官方麦克风示例）。

## 风险与遗留

- ~~llama-cpp-python 的 Windows 预编译 wheel 可用性~~ → 已核实并定案：PyPI 无 wheel，用作者索引 + 发行包随包携带（见决策记录）
- keyboard 热键：普通权限即可；仅在管理员权限窗口内听写需要本程序提权（UIPI），不做默认提权，首次启动自检引导
- 校对替换与用户手动编辑光标位置可能冲突 → MVP 接受此风险，仅保证替换发生在停顿锁句后
- 双语 Zipformer 2023 版社区反馈精度一般 → 若实测准确率不足，备选 funasr-nano 流式模型（非 int8 版，避开 issue #3066 重复文字问题）
- 各文本应用对粘贴行为差异（如终端自动换行）→ 验证标准覆盖主流场景即可

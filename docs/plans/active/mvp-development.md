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
| 阶段 1：项目骨架 + 一键安装 | 主 Agent | queue | 待定 | requirements.txt / install.bat / run.bat |
| 阶段 2：热键 + 音频采集 | 主 Agent | queue | 待定 | Alt+V 开关、麦克风 PCM 流 |
| 阶段 3：流式识别 + 实时上屏 | 主 Agent | queue | 待定 | sherpa-onnx 集成、光标处插入 |
| 阶段 4：停顿检测 + 二次校对 | 主 Agent | queue | 待定 | Qwen GGUF 校对替换 |
| 阶段 5：打磨 + 分发验证 | 主 Agent | queue | 待定 | 干净环境验证、异常处理、托盘 |

## 目标

交付可分发的 Windows 语音听写工具：Alt+V 开始/停止，流式识别文字实时输入到光标所在文本框，说话停顿后本地小模型校对并替换。全程离线，`install.bat` 一键安装。

## 阶段划分

### 阶段 1：项目骨架 + 一键安装
- **目标**：建立 Python 包结构、锁定依赖版本、install.bat/run.bat 可在干净 Windows 机器拉起环境并下载两个模型到 models/
- **涉及文件**：requirements.txt、install.bat、run.bat、config.json、.gitignore、voice2text/__init__.py、voice2text/config.py、scripts/download_models.py
- **验证标准**：全新目录执行 install.bat 成功：venv 创建、依赖安装无源码编译、models/ 下出现流式 Zipformer 模型与 Qwen GGUF（GitHub 失败时 ModelScope fallback 生效）；run.bat 能启动并退出
- **Owner**：主 Agent
- **Reviewer**：待定
- **状态**：queue
- **完成记录**：
- **交接摘要**：

### 阶段 2：热键 + 音频采集
- **目标**：常驻进程监听全局 Alt+V，切换听写开/关；开启时 sounddevice 采集 16kHz 单声道 PCM 送入队列，关闭时停止采集并 flush
- **涉及文件**：voice2text/main.py、voice2text/hotkey.py、voice2text/capture.py
- **验证标准**：控制台可见开/关状态日志；采集的 PCM 写入临时 wav 可正常播放（调试开关）；热键无响应时程序给出权限提示
- **Owner**：主 Agent
- **Reviewer**：待定
- **前置条件**：阶段 1 完成
- **状态**：queue
- **完成记录**：
- **交接摘要**：

### 阶段 3：流式识别 + 实时上屏
- **目标**：sherpa-onnx 流式识别线程消费 PCM 队列，增量文本实时插入到当前光标所在的可编辑控件；不可编辑时静默跳过
- **涉及文件**：voice2text/asr.py、voice2text/input.py（可编辑检测 + 剪贴板粘贴 + 记账）、voice2text/main.py
- **验证标准**：记事本/浏览器地址栏/微信输入框中说话，文字随说随出；焦点在非编辑区（如桌面）说话不上屏不报错；剪贴板原内容在停止后恢复
- **Owner**：主 Agent
- **Reviewer**：待定
- **前置条件**：阶段 2 完成
- **状态**：queue
- **完成记录**：
- **交接摘要**：

### 阶段 4：停顿检测 + 二次校对
- **目标**：~1.5s 无有效语音触发校对；llama-cpp-python 加载 Qwen GGUF，按固定 prompt 清理错别字/语气词/通顺度；用校对结果退格抹除并替换已上屏原文；校对期间识别继续不丢字
- **涉及文件**：voice2text/proofread.py、voice2text/asr.py（停顿/分句）、voice2text/input.py（替换）、config.json
- **验证标准**：说一段带"嗯、那个"的口语，停顿后上屏文本变为整洁书面语；校对中的新增语音在校对完成后继续正常上屏；Ctrl+V 风格替换无字符错位
- **Owner**：主 Agent
- **Reviewer**：待定
- **前置条件**：阶段 3 完成
- **状态**：queue
- **完成记录**：
- **交接摘要**：

### 阶段 5：打磨 + 分发验证
- **目标**：异常处理（无麦克风/模型缺失/热键被占用）、系统托盘常驻 + 状态提示、中文 UTF-8 输出、干净机器完整走一遍 install→run→听写
- **涉及文件**：voice2text/main.py、voice2text/tray.py、install.bat、docs/*
- **验证标准**：拔麦克风/删模型目录等异常均有友好提示不崩溃；全新环境完整流程可用；CHANGELOG/overview 文档同步
- **Owner**：主 Agent
- **Reviewer**：待定
- **前置条件**：阶段 4 完成
- **状态**：queue
- **完成记录**：
- **交接摘要**：

## 决策记录

- 2026-09-15：识别框架选 sherpa-onnx（原生流式、CPU 快、跨平台），校对模型选 Qwen3-1.7B Q4 GGUF + llama-cpp-python（预编译 wheel 对一键安装友好）。详见 docs/overview.md「关键设计决策」。
- 2026-09-15：上屏方案定为剪贴板粘贴（中文模拟键击会被输入法拦截），需保存/恢复用户剪贴板。

## 风险与遗留

- llama-cpp-python 的 Windows 预编译 wheel 可用性随版本波动 → 阶段 1 须实测锁定版本
- keyboard 全局热键在 UAC 下可能需管理员权限 → 阶段 2 做启动自检与提示
- 校对替换与用户手动编辑光标位置可能冲突 → MVP 接受此风险，仅保证替换发生在停顿后
- 各文本应用对粘贴行为差异（如终端自动换行）→ 阶段 3 验证标准覆盖主流场景即可

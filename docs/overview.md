# 系统设计概览

> 记录系统级设计决策和架构选型理由。只写"为什么这样设计"，不写代码能直接看到的"是什么"。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## 系统定位

为 Windows 用户提供的全局语音听写工具：任何可输入文本的地方按 Alt+V 即可语音输入，说完即得经过校对的整洁文本。完全离线，一键安装分发。

## 架构主线

```
Alt+V（keyboard 全局热键，常驻后台）
  → sounddevice 采集麦克风 PCM → 环形缓冲
  → sherpa-onnx 流式识别线程（增量文本回调）
  → input 模块：锁定输入目标 → 默认 SendInput Unicode；微信/Windows Terminal 用受保护粘贴
  → 停顿检测（0.8s）→ sherpa-onnx 标点模型只插入标点并锁句
  → Alt+V 停止 → proofread 模块用 Qwen GGUF 统一校对
     → 用校对结果替换本次已上屏文本
```

关键不变量：
- 识别线程与校对推理不得阻塞音频采集与热键响应（各自独立线程）
- 准备阶段先采集并排队音频；识别流完成就绪握手后才向用户声明“正在聆听”并播放开始提示音
- 校对替换必须精确知道"刚才上屏了哪些字"，上屏文本与替换文本由同一模块记账
- 捕获、焦点恢复或权限验证失败时关闭本次写入，并给出可执行的状态说明

## 关键设计决策

### 为什么选 sherpa-onnx 而不是 Whisper 系
- **场景**：需要边说边出字的实时听写，CPU 推理，Windows 桌面
- **备选**：faster-whisper / whisper.cpp（准确但本质是 30 秒整段模型）、FunASR 直接部署（Python 生态、偏批量）
- **选择**：sherpa-onnx——原生流式、ONNX Runtime CPU 实时率远小于 1、跨平台、Apache 2.0
- **取舍**：识别精度略低于 SenseVoice/Whisper 的离线批量水平，由二次校对环节补偿

### 识别模型选哪个
- 流式 Zipformer 中英双语模型起步；funasr-nano 流式模型为备选
- 已知陷阱：funasr-nano 的 int8 量化版有转写文字重复问题（sherpa-onnx issue #3066），避开 int8 版
- 国内下载走 ModelScope 镜像（install 脚本内做 GitHub→ModelScope fallback）

### 为什么二次校对用 Qwen 小模型（GGUF + llama-cpp-python）
- **场景**：清理错别字、赘余语气词（"嗯""那个"）、理顺口语，需要生成能力而非纯判别
- **备选**：BERT 类纠错模型（只能改错别字，无法删语气词/顺句）；要求用户装 Ollama（破坏一键安装）
- **选择**：Qwen3-1.7B Q4_K_M GGUF（约 1.1GB）。注意：PyPI 上 llama-cpp-python 只发布 sdist，Windows wheel 在作者索引 `https://abetlen.github.io/llama-cpp-python/whl/cpu/`，安装命令须带 `--extra-index-url`，发行包随包携带 wheel
- **取舍**：校对质量低于 7B 级模型；做成配置项可换更大模型（如 Qwen3-4B）。10 秒只标记慢校对，结果仍应用；单块超过 30 秒会关闭该输入会话并释放焦点，迟到结果由会话代数拦截。

### 上屏为什么默认用 SendInput Unicode 注入
- 初版方案是剪贴板 + Ctrl+V（规避输入法对普通键击的转义），但 Windows 剪贴板历史（Win+V）会积累每一次 partial 刷新的文本（用户实测不可接受），且与用户剪贴板存在保存/恢复竞态
- 现方案：SendInput KEYEVENTF_UNICODE（VK_PACKET）把字符作为键盘事件直发光标处，绕过输入法组合、不经剪贴板；KeePass 等自动输入工具的标准做法
- 微信 Qt 输入框会错误接收 VK_PACKET，partial 变化尾部和标点改用受保护剪贴板事务；Windows Terminal 同样使用该事务并发送 Ctrl+Shift+V
- 临时内容声明不进入 Win+V/云同步。事务以 clipboard sequence 校验快照、发布和恢复边界；替换已有文字时先成功备份并发布，再删除旧字。用户同时复制的新内容优先保留
- 兜底：其他不认 VK_PACKET 的应用可用 `config.input_clipboard=true` 使用同一受保护剪贴板路径（Ctrl+V 键间留有间隔，防 IME 异步钩子拆散组合键）

### 可编辑检测为什么用 UIAutomation
- pyautogui/pyperclip 没有 UI 元素内省能力，判断不了"光标是否在可编辑控件"
- Windows 可靠路径是 UIA：`uiautomation` 取焦点控件，ControlType ∈ {Edit, Document} 或 ValuePattern 可写
- 取舍：UIA 对自绘控件覆盖不全。未知应用验证失败时拒绝开始；只有 Windows Terminal 与 WPS 套件走经过回归覆盖的原生焦点路径，config 黑名单可继续关停指定进程

### 流式 partial 为什么只替换变化尾部
- sherpa-onnx `get_result()` 返回当前句累计假设文本，解码中尾部会自我修正（非单调追加），当增量逐次粘贴会出现重复错乱
- 保留最长公共前缀，只退格并重写不稳定尾部；endpoint 触发后锁句不再变动，进入校对队列
- 取舍：尾部仍会随模型假设修正，但稳定前缀不会闪动；若体验差可延迟显示最后几个不稳定字

### 为什么停顿时先做一次轻量标点恢复

- 流式 Zipformer 不输出标点；若停止后的 Qwen 校对取消，用户会留下整段无标点文本
- 每次 0.8 秒停顿锁句时调用 sherpa-onnx 中英文 CT-Transformer INT8 模型，本机样例约 5–11ms
- 标点层通过字符一致性门禁，只接受“插入标点”的结果；任何改字、删字或异常都保留原识别文本
- Qwen 仍在停止后负责错字、语气词和通顺度，轻量标点层不承担文字改写

### 为什么校对放在停止后而不是边说边校
- 边说边校对会反复替换光标处文本，与用户编辑冲突、画面跳动（用户决策：听写期间屏幕文字只增不改）
- endpoint（0.8 秒停顿）先恢复标点并锁句；Alt+V 停止后把锁定句按 ≤60 字分块，逐块校对并替换
- 分块原因：校对模型对更长文本会原样照抄不加工（实测 bug）；清理失败时只加标点，模型也失败时只给中文自然语言补句末符号，数字、URL 与路径保留原样
- 取舍：停止后有数秒校对等待期；模型校对可能引入新的同音字错误（1.7B 能力边界，可换更大模型）

### 悬浮窗原生模糊为何保留回退

Windows 10 原生合成模糊通过 `SetWindowCompositionAttribute` 的 ACCENT_ENABLE_BLURBEHIND 与 ULW 半透明表面组合，不需要升级 GUI 框架或抓取桌面。该接口非公开，因此按能力探测；远程桌面、高对比或系统透明效果关闭时回退深蓝绘制。圆角区域交给系统裁剪，避免透明角外出现矩形模糊背景。当前真机验证覆盖 Windows 10 19045；Windows 11 尚待实机验证。

### 为什么桌面层保留轻量原生组合

- 设置页使用标准库 Tkinter，悬浮窗由 Pillow 超采样绘制后通过 pywin32 提交分层窗口，托盘
  生命周期使用 pystray；不引入 Chromium 或独立 Web 前端运行时
- 该组合能随自包含 Python 一起分发，并直接使用 Win32 焦点、剪贴板、模糊和逐像素透明能力
- 取舍是 Windows 行为需要真机覆盖，DPI、窗口合成和不同权限级别不能只靠无界面测试证明

### 为什么自更新由独立进程应用

- 自包含版运行时的 `python.exe`、DLL 和扩展模块在程序运行期间受 Windows 文件锁保护，主进程不能安全覆盖自身
- 设置页只负责从固定 GitHub Release 下载 ZIP 和 SHA-256，并验证版本、摘要、单一根目录、路径穿越、符号链接、文件数与展开体积
- 用户确认后把仓库内置的 PowerShell 更新脚本复制到 LocalAppData，主程序退出后再覆盖安装目录并重启；不执行 Release 中携带的脚本
- 更新前把现有 `config.json` 和 `models/llm/` 合并进已完整解压的新版目录，用户设置与可选校对模型不会因基础包更新丢失
- 首版只支持用户主动检查，不做静默后台更新；网络或校验失败时继续使用当前版本

## 不在这里记的内容

- 目录结构 → `ls` / `tree`
- 函数签名、参数默认值 → 源码
- 部署与环境变量 → [docs/deployment.md](deployment.md)
- 已知环境陷阱 → [docs/pitfalls.md](pitfalls.md)

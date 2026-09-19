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
  → input 模块：检测焦点控件可编辑 → SendInput Unicode 注入光标处（实时上屏）
  → 停顿检测（~1.5s 无有效语音）
  → proofread 模块：llama-cpp-python 加载 Qwen GGUF，校对该句
     → 用校对结果替换刚才上屏的原文（退格抹除 + 重新粘贴）
```

关键不变量：
- 识别线程与校对推理不得阻塞音频采集与热键响应（各自独立线程）
- 校对替换必须精确知道"刚才上屏了哪些字"，上屏文本与替换文本由同一模块记账
- 光标位置不可输入时，一切写入操作静默跳过（不弹窗、不粘贴）

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

### 上屏为什么用 SendInput Unicode 注入而不是剪贴板
- 初版方案是剪贴板 + Ctrl+V（规避输入法对普通键击的转义），但 Windows 剪贴板历史（Win+V）会积累每一次 partial 刷新的文本（用户实测不可接受），且与用户剪贴板存在保存/恢复竞态
- 现方案：SendInput KEYEVENTF_UNICODE（VK_PACKET）把字符作为键盘事件直发光标处，绕过输入法组合、不经剪贴板；KeePass 等自动输入工具的标准做法
- 兜底：个别不认 VK_PACKET 的应用用 `config.input_clipboard=true` 回退剪贴板路径（该路径键间需留间隔，防 IME 异步钩子把 Ctrl+V 拆散）

### 可编辑检测为什么用 UIAutomation
- pyautogui/pyperclip 没有 UI 元素内省能力，判断不了"光标是否在可编辑控件"
- Windows 可靠路径是 UIA：`uiautomation` 取焦点控件，ControlType ∈ {Edit, Document} 或 ValuePattern 可写
- 取舍：UIA 对自绘控件（部分 Qt/Electron/游戏）覆盖不全——查不到控件时默认允许粘贴，config 黑名单可关停指定进程

### 流式 partial 为什么只替换变化尾部
- sherpa-onnx `get_result()` 返回当前句累计假设文本，解码中尾部会自我修正（非单调追加），当增量逐次粘贴会出现重复错乱
- 保留最长公共前缀，只退格并重写不稳定尾部；endpoint 触发后锁句不再变动，进入校对队列
- 取舍：尾部仍会随模型假设修正，但稳定前缀不会闪动；若体验差可延迟显示最后几个不稳定字

### 为什么校对放在停止后而不是边说边校
- 边说边校对会反复替换光标处文本，与用户编辑冲突、画面跳动（用户决策：听写期间屏幕文字只增不改）
- endpoint（0.8 秒停顿，低于则连续说话永不分句）锁句仅用于分段记账；Alt+V 停止后把锁定句按 ≤60 字分块，逐块校对并替换
- 分块原因：校对模型对更长文本会原样照抄不加工（实测 bug）；清理失败时只加标点，模型也失败时只给中文自然语言补句末符号，数字、URL 与路径保留原样
- 取舍：停止后有数秒校对等待期；模型校对可能引入新的同音字错误（1.7B 能力边界，可换更大模型）

### 悬浮窗原生模糊为何保留回退

Windows 10 原生合成模糊通过 `SetWindowCompositionAttribute` 的 ACCENT_ENABLE_BLURBEHIND 与 ULW 半透明表面组合，不需要升级 GUI 框架或抓取桌面。该接口非公开，因此按能力探测；远程桌面、高对比或系统透明效果关闭时回退深蓝绘制。圆角区域交给系统裁剪，避免透明角外出现矩形模糊背景。当前真机验证覆盖 Windows 10 19045；Windows 11 尚待实机验证。

## 不在这里记的内容

- 目录结构 → `ls` / `tree`
- 函数签名、参数默认值 → 源码
- 部署与环境变量 → [docs/deployment.md](deployment.md)
- 已知环境陷阱 → [docs/pitfalls.md](pitfalls.md)

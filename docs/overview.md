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
  → input 模块：检测焦点控件可编辑 → 剪贴板粘贴方式插入光标处（实时上屏）
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
- **选择**：Qwen3-1.7B Q4_K_M GGUF（约 1.1GB），llama-cpp-python 有预编译 wheel，CPU 上校对一两句话在数秒内
- **取舍**：校对质量低于 7B 级模型；做成配置项可换更大模型（如 Qwen3-4B）

### 为什么用剪贴板粘贴而不是模拟键盘逐字输入
- 中文输入走模拟键击会被输入法拦截/转义；剪贴板粘贴在任何文本框都可靠
- 取舍：会覆盖用户剪贴板内容——保存/恢复原剪贴板以缓解

### 为什么校对要等停顿而不是每句立即触发
- 边说边校对会反复替换光标处文本，与用户编辑冲突
- 约 1.5 秒无新语音视为"这句说完了"，一次性校对替换

## 不在这里记的内容

- 目录结构 → `ls` / `tree`
- 函数签名、参数默认值 → 源码
- 部署与环境变量 → [docs/deployment.md](deployment.md)
- 已知环境陷阱 → [docs/pitfalls.md](pitfalls.md)

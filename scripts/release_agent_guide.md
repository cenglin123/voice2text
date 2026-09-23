# voice2text 分发版排查指南

本文件供在**已解压的分发包目录**中工作的 agent 使用。这里没有开发仓库的 Git 历史和治理脚本；请直接检查当前安装包的代码、运行输出与 `source-baseline.zip`。不要把开发仓库的 `AGENTS.md` 原样复制到分发端。

## 先确定故障层

1. 查看 `安装说明.txt`，确认完成安装。离线包可运行 `runtime\python\python.exe scripts\verify_install.py` 检查依赖与本地模型；在线安装包用 `.venv\Scripts\python.exe`，若不存在则用 `runtime\python\python.exe`。
2. 从托盘或设置页打开“运行输出”。需要更详细诊断时，先从托盘退出正在运行的实例，在命令提示符执行 `set VOICE2TEXT_DIAGNOSTICS=1`，再运行 `run.bat --debug`。
3. 区分“没有捕获目标”“没有采到声音”“识别正确但没有上屏”“停止后校对未应用”。检查原输入窗口权限、实际麦克风、焦点与输入控件身份，再查相应模块。
4. 修复后先运行 `scripts\verify_install.py`，再在记事本和问题应用中分别验证开始、实时上屏、停止和焦点保护。修改热键或输入安全逻辑时，不得向错误窗口盲写。

## 本地修改边界

- 识别、标点与校对必须继续在本机运行；不要上传麦克风音频或听写内容，也不要把音频持久化到磁盘。
- 保留 `config.json`、`models/` 与 `runtime/`，不要把其中内容写进反馈补丁。`config.json` 可能含个人设置；模型和运行时不是源码。
- 修改源码前保留原文件，尽量只改与故障相关的文件。`source-baseline.zip` 保存了本版发出的干净源码，可用于生成上游可读的 diff。
- 不要自动上传反馈文件。发送前人工检查里面的文本，去掉姓名、账号、机器路径、令牌、聊天内容和其它私密信息。

## 向上游交付反馈

在分发包根目录执行以下其中一个命令；脚本只使用 Python 标准库：

```bat
runtime\python\python.exe scripts\export_feedback.py --summary "简述问题" --steps "复现步骤" --expected "期望结果" --actual "实际结果" --validation "修复后验证"
```

如果运行时在 `.venv`，把上述解释器换为 `.venv\Scripts\python.exe`。脚本会在 `feedback/` 下生成 `反馈.md` 和 `修复.diff`。请在 `反馈.md` 中补充能解释问题的少量运行输出；默认导出不会采集日志、配置或录音。把两份文件发给开发仓库即可。若没有改源码，`修复.diff` 为空，反馈文档仍可用于排查。

项目主页：https://github.com/cenglin123/voice2text
反馈入口：https://github.com/cenglin123/voice2text/issues

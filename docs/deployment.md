# 部署与环境配置

> 记录部署方式、环境差异和启动约定。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## 环境变量

无必需环境变量（全离线、零配置为目标）。可选配置项以 `config.json`（程序同目录）承载：热键、停顿阈值、模型路径、校对模型选择。默认值以代码为准。

## 启动方式

### 开发环境

```bash
# Windows，Git Bash；本机已有 Python 3.11–3.13 x64（含 tkinter）
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/
.venv/Scripts/python -m voice2text.main
```

### 最终用户

- 离线分发 ZIP：完整解压到可写目录，双击 `安装程序.bat` 验证依赖与模型；成功后运行安装流程生成的带图标 `启动 voice2text` 快捷方式，失败时可直接双击 `启动程序.bat`。包内有独立 Python、全部依赖、语音和标点模型；基础安装不联网，也不依赖系统 Python。`offline-bundle.txt` 标记决定使用包内运行时。英文 `install.bat` / `run.bat` 作为兼容和调试入口保留。
- 校对 GGUF 为可选组件：设置 → 识别与校对 → 下载校对模型（约 1.1 GB），完成后打开二次校对并保存。下载失败可重试，下载过程中仍可使用基础听写；关闭设置不终止下载，退出程序终止下载。网络仅用于用户明确触发的模型安装，推理全部在本地。
- 源码仓库的 `install.bat` 在线准备环境：探测 Python 3.11–3.13 x64 和 Tk，不兼容时下载固定独立运行时，再安装依赖、下载模型。Python 的证书链失败时，模型下载可回退系统 curl，保持证书校验。
- 最终用户快捷方式直接调用选定运行时的 `pythonw.exe`，不显示控制台；`启动程序.bat` 默认同样常驻托盘并显示悬浮窗。运行输出从设置或托盘打开，`run.bat --debug` 才显示调试控制台。
- 自包含分发版的一键更新位于设置 → 识别与校对。程序只查询固定 GitHub 仓库的最新正式
  Release，下载同版本 Windows x64 ZIP 与 `.sha256`，通过摘要和压缩包安全检查后才允许安装。
  更新器等待当前进程退出再覆盖独立运行时，保留 `config.json` 和 `models/llm/`，完成后自动重启。
  源码开发环境没有 `offline-bundle.txt`，因此只显示说明，不执行自更新。

### 制作离线分发包

在 `dist/build-runtime/python` 准备固定的 python-build-standalone 3.11.9 x64，使用其 Python
执行 `-I -X utf8 -m pip install --only-binary=:all: --find-links vendor -r requirements.txt`。
`vendor` 需预先准备固定版本 llama wheel；构建运行时不得使用开发 `.venv` 或系统 Python 的目录副本。
运行 `python scripts/build_release.py`，从干净运行时与 `models/` 中仅复制基础模型白名单，
生成 `dist/voice2text-v0.1.3-windows-x64.zip` 和同名 `.sha256`。
构建会生成默认配置（校对关闭），不携带个人配置、GGUF 或开发环境。产物和模型不入 Git。

代码版本已提升为 `0.1.3`，用于发布 `v0.1.2` 之后的输入兼容、安全与临时音频清理修复。
只有重新生成的 `v0.1.3` 资产通过完整校验并上传后，才能把该版本标记为正式发行。

构建结构检查：`python scripts/check_release.py`。一键更新回归：`python scripts/check_update.py`。
模型下载回归：
`python scripts/check_download_models.py` 与 `python scripts/check_model_download.py`。
最终包还必须在虚拟机独立目录验证，构建检查不能替代实际模型加载与 GUI 验收。

## 持久化与备份

用户设置持久化在程序目录的 `config.json`，可选校对模型位于 `models/llm/`；一键更新会保留
两者。语音/标点模型与 `runtime/` 可由安装或发行包重建。构建和提交必须排除个人
`config.json`、全部模型文件和运行时目录。

## 部署陷阱

- 全局热键（keyboard 库）普通权限即可；向管理员窗口注入会受 UIPI 限制。捕获目标时检查顶层与实际焦点进程，权限失配即拒绝开始并给出管理员重启指引，不做默认提权
- llama-cpp-python 在 PyPI 只有 sdist；必须带 `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/` 安装预编译 wheel，否则触发源码编译（需 MSVC）；发行包随包携带 wheel，不依赖第三方个人索引的长期可用性
- 模型下载在国内网络环境下 GitHub Release 可能超时，须有 ModelScope fallback

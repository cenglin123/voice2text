# 部署与环境配置

> 记录部署方式、环境差异和启动约定。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## 环境变量

无必需环境变量（全离线、零配置为目标）。可选配置项以 `config.json`（程序同目录）承载：热键、停顿阈值、模型路径、校对模型选择。默认值以代码为准。

## 启动方式

### 开发环境

```bash
# Windows，Git Bash；本机已有 Python 3.10+
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/
.venv/Scripts/python -m voice2text.main
```

### 最终用户

- `install.bat`：一键安装，自包含——检测本机 Python 3.10+（识别并跳过 Windows Store 假别名），缺失则下载 Windows embeddable Python 到 runtime/；然后装依赖（llama-cpp-python 走 abetlen wheel 索引）+ 下载识别模型与校对 GGUF 到 models/
- `run.bat`：启动常驻进程（热键生效）

## 持久化与备份

无用户数据持久化。`models/`（约 1.5–2GB）与 `runtime/`（embeddable Python，约 20MB 解压后 ~70MB）为可重建目录，删除后重跑 `install.bat` 可恢复。

## 部署陷阱

- 全局热键（keyboard 库）普通权限即可；仅在管理员权限窗口内听写时收不到热键（UIPI 限制）——首次启动自检并提示，不做默认提权
- llama-cpp-python 在 PyPI 只有 sdist；必须带 `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/` 安装预编译 wheel，否则触发源码编译（需 MSVC）；发行包随包携带 wheel，不依赖第三方个人索引的长期可用性
- 模型下载在国内网络环境下 GitHub Release 可能超时，须有 ModelScope fallback

# 部署与环境配置

> 记录部署方式、环境差异和启动约定。
> 修改本文件后同步更新 [CHANGELOG.md](CHANGELOG.md)。

## 环境变量

无必需环境变量（全离线、零配置为目标）。可选配置项以 `config.json`（程序同目录）承载：热键、停顿阈值、模型路径、校对模型选择。默认值以代码为准。

## 启动方式

### 开发环境

```bash
# Windows，Git Bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
python -m voice2text.main
```

### 最终用户

- `install.bat`：一键安装（创建 venv → 装依赖 → 下载识别模型与校对 GGUF 到 models/）
- `run.bat`：启动常驻进程（热键生效）

## 持久化与备份

无用户数据持久化。`models/` 为唯一大体积目录（约 1.5–2GB），删除后重跑 `install.bat` 可恢复。

## 部署陷阱

- 全局热键（keyboard 库）在部分 Windows 环境需要管理员权限，普通权限下可能收不到 Alt+V —— 安装脚本需提示用户
- llama-cpp-python 在 Windows 依赖预编译 wheel；若 pip 源没有对应 wheel 会回退到源码编译（需要 MSVC），安装脚本应固定 wheel 可用的版本
- 模型下载在国内网络环境下 GitHub Release 可能超时，须有 ModelScope fallback

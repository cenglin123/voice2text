# voice2text

Windows 桌面语音听写工具：在任何可输入文本的地方按下 Alt+V 开始听写，说中文/英文即刻流式上屏；停顿后由本地小模型自动校对（错别字、赘余语气词、通顺度）。全部离线运行，一键安装。

## 快速开始

### 环境要求

- Windows 10/11 x64
- Python 3.10+
- 麦克风
- 磁盘空间 ~2.5GB（依赖 + 模型）

### 安装与运行

```bash
git clone <仓库地址>
cd voice2text

# 一键安装：创建 venv + 安装依赖 + 下载识别模型与校对模型
install.bat

# 启动（托盘常驻、无控制台窗口，Alt+V 触发）
run.bat

# 调试启动（保留控制台输出）
run.bat --debug
```

> 提示：全局热键在部分环境需要管理员权限运行，否则 Alt+V 可能无响应。

### 测试

悬浮窗右下角可拖动调整长宽，最窄可调成正方形；设置页的“窗口大小”和“长宽比”会与拖动结果同步。

桌面组件验证：`python scripts/check_widget.py`、`python scripts/check_settings.py`、`python scripts/check_tray_menu.py`、`python scripts/check_session.py`（Windows，不加载模型）；`python scripts/check_target_desktop.py` 只向脚本自建编辑窗注入测试文字。悬浮窗和托盘菜单验证分别支持截图参数，详见脚本帮助。

听写手动验证：启动后打开记事本，按 Alt+V 说话 → 观察流式上屏 → 再按 Alt+V 停止 → 确认二次校对替换。

## 项目结构

```
voice2text/
├── voice2text/    # 主程序（热键、采集、识别、校对、上屏）
├── models/        # 模型文件（不入 git，install.bat 下载）
├── scripts/       # 文档体系维护脚本
└── docs/          # 文档（详见 docs/overview.md）
```

详细的架构说明见 [docs/overview.md](docs/overview.md)。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/STRUCTURE.md](docs/STRUCTURE.md) | 文档总索引 |
| [docs/overview.md](docs/overview.md) | 系统架构与设计决策 |
| [docs/deployment.md](docs/deployment.md) | 部署与环境配置 |
| [docs/pitfalls.md](docs/pitfalls.md) | 已知环境陷阱 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 变更记录 |
| [docs/CURRENT.md](docs/CURRENT.md) | 当前任务状态 |

## 贡献

1. 创建功能分支：`git checkout -b feat/your-feature`
2. 提交更改：`git commit -m "feat: your feature description"`
3. 推送分支并创建 Pull Request

**提交规范**：Conventional Commit 风格（`feat:` / `fix:` / `chore:` 等）。

## AI Agent 协作

本仓库配置了面向 AI Agent 的文档体系。如果你是 AI Agent，请加载 [AGENTS.md](AGENTS.md)（或 [CLAUDE.md](CLAUDE.md) / [GEMINI.md](GEMINI.md)）获取行为规则和信息导航。

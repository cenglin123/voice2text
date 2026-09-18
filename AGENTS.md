# AI 协作规范

> 本文件会被 AI 框架自动加载并始终驻留在上下文中，因此必须保持精简（≤ 250 行）。
> 只放行为规则和信息指针，不放可从代码或其他文档获取的事实描述。

## 项目概述

voice2text：Windows 桌面语音听写工具。按下 Alt+V 开始/停止听写，麦克风音频经 sherpa-onnx 流式识别后实时输入到当前光标所在的可编辑文本框；说话停顿后由本地 Qwen 小模型（GGUF + llama-cpp-python）做二次校对（错别字、赘余语气词、通顺度）并替换已上屏文本。全部离线运行，面向最终用户一键安装分发。

## 同步声明

`AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 内容必须保持一致。**只编辑 AGENTS.md**，另两个由脚本同步。

- `python scripts/agent_links.py check --mode copy`
- `python scripts/agent_links.py repair --mode copy --force`
- 模式：copy

## 信息导航

- 文档总索引：[docs/STRUCTURE.md](docs/STRUCTURE.md)
- 系统主线与设计决策：[docs/overview.md](docs/overview.md)
- 部署与同步：[docs/deployment.md](docs/deployment.md)
- 环境陷阱：[docs/pitfalls.md](docs/pitfalls.md)
- 文档一致性审计：[docs/audit-checklist.md](docs/audit-checklist.md)
- 复杂任务计划：[docs/plans/](docs/plans/)
- 当前任务状态：[docs/CURRENT.md](docs/CURRENT.md)
- 项目记忆索引：[.agents/memory/MEMORY.md](.agents/memory/MEMORY.md)
- Bugfix 档案：[docs/problems/bugfix/](docs/problems/bugfix/)
- 变更记录：[docs/CHANGELOG.md](docs/CHANGELOG.md)

省略声明：本项目无对外 API，不设 docs/api.md；无独立 frontmatter schema 文档（约定内嵌于各模板文件）。

## 项目记忆

- **用户**：中文交流；关注可分发性（自包含、一键安装）与最终用户体验
- **项目上下文**：voice2text 处于从零开发阶段，技术选型已定（sherpa-onnx 流式识别 + Qwen GGUF 校对 + llama-cpp-python）
- **最近教训**：① llama-cpp-python 在 PyPI 只有 sdist、无任何 wheel——Windows wheel 仅在作者索引 abetlen.github.io/llama-cpp-python/whl/cpu/，装依赖必须带 `--extra-index-url`；② sherpa-onnx 1.13.x 的 Python 模块名是 `sherpa_onnx`（旧 `sherpa.onnx` 已废弃）；③ embeddable Python 的 `._pth` 隔离模式不含 cwd，须在 `._pth` 追加项目根 + 设 `PYTHONNOUSERSITE=1`；④ sherpa-onnx funasr-nano int8 版有转写重复问题（issue #3066），避开 int8；⑤ 中文输入法激活时合成按键三坑：全局热键必须 suppress 不透传（v 会进拼音组合框）、Ctrl+V 键间须加间隔（否则被 IME 异步钩子拆散）、剪贴板恢复必须晚于最后一次粘贴（档案见 bugfix/ime-vmode-text-vanish.md）
- **详细记忆**：[.agents/memory/MEMORY.md](.agents/memory/MEMORY.md)

> 维护细节（写入触发、touch 规范、索引重建）见 MEMORY.md 和 `python scripts/maintain.py`。

## 行为规则

### Compact 恢复

若上下文含 "continued from a previous conversation"：
1. 读 [docs/CURRENT.md](docs/CURRENT.md) — 确认当前任务状态
2. 读 [.agents/memory/MEMORY.md](.agents/memory/MEMORY.md) — 恢复项目记忆
3. 上述完成前，**禁止写操作、禁止有副作用的判断**

### 任务前记忆检索

除非任务非常简单明确，开始前先查经验系统：[.agents/memory/MEMORY.md](.agents/memory/MEMORY.md) 索引段 → 按需深入。
Bugfix 任务（修复 / bug / 报错 / 异常等）必须先查索引段的 bugfix 分区——检索动作必须发生，确认无相关记录才可继续。检索流程详情见 MEMORY.md。

### Bugfix 沉淀

修复 bug、排查异常、处理回归完工时，必须沉淀一篇 `docs/problems/bugfix/<slug>.md`。触发条件不变：完工时必写；写作规范（frontmatter、复现、验证）见 [docs/problems/bugfix/_template.md](docs/problems/bugfix/_template.md)。逐篇索引由 `python scripts/maintain.py` 派生，不手工登记。

### 硬约束（不可违反）

- **全部离线**：不得引入任何云端 API 调用（识别、校对、模型下载均需本地或安装期完成）
- **模型文件不入库**：`models/` 目录（sherpa-onnx 模型、Qwen GGUF，体积大）不进 git，由安装脚本下载
- **一键安装**：`install.bat` 必须能从干净 Windows 机器拉起完整环境（venv + 依赖 + 模型），破坏此性质即破坏核心需求
- **全局热键 Alt+V**：keyboard 库普通权限即可装钩子；仅焦点在管理员权限窗口时收不到热键（UIPI 限制）。不做默认提权，首次启动自检引导（详见 docs/pitfalls.md）

### 默认偏好（有充分理由可偏离）

- **先读后改**：修改任何文件前先读取，理解现有逻辑再动手。
- **Occam**：如无必要，勿增实体。
- **Bitter Lesson**：通用方法优于硬编码先验。
- **模式匹配**：单会话小任务用直接执行；跨模块/跨会话任务走当前选定的控制器下的「复杂任务闭环」：
  1. `docs/plans/active/` 落盘计划 → 2. 独立视角审查 → 3. 用户确认 → 4. 执行 → 5. 验收
- **任务启动先读 CURRENT.md**。
- **验证尽量换视角**：高风险改动优先由新上下文或 reviewer 视角复查。
- **代码风格**：Python 3.10+，4 空格缩进，中文注释与文档，类型标注用于公共函数。
- **Windows 优先**：本项目只面向 Windows；脚本用 .bat + Python，避免 bash-only 语法（Git Bash 可用于开发期命令）。

## 测试要求

暂无自动化测试套件。验证方式为手动功能验证：启动程序 → 在记事本中按 Alt+V 说话 → 确认流式上屏、停顿校对、再次 Alt+V 停止。后续若引入 pytest，测试命令写入本节并更新 README。

## 安全与配置

- 麦克风音频只在本地处理，不得写入磁盘持久化（临时缓冲除外，须在程序退出时清理）
- 校对模型与识别模型的下载源写死在安装脚本中，不执行任意远端指令

## 提交规范

Conventional Commit（`feat:` / `fix:` / `chore:`）。治理文档修改须含 `[governance]` 标记。完成一个阶段后主动提交。

## 文档维护原则

1. **不重复**：同一信息只在最合适的位置出现一次
2. **只记代码/正文里读不出来的东西**：设计原因、协作约束、环境陷阱
3. **治理文档直接写最终态**：修改 AGENTS.md / STRUCTURE.md 等规则文件时不留「以前xx，现在xx」对比、日期标记或弃用标注——当前文本即权威；过程性历史归 git log，制度变更归 CHANGELOG
4. **CHANGELOG**：用 `python scripts/changelog.py titles/show/add/recent`，不读全文
5. **计划落盘**：跨模块/跨会话的任务在 `docs/plans/active/` 写计划，完成后移 `completed/`
6. **定期审计**：每 ~20 次任务或每月，跑 `python scripts/maintain.py`（内含 audit.py check）

> docs/ 文件的治理规则（存在/合并/创建/删除条件）见 [docs/STRUCTURE.md](docs/STRUCTURE.md)「文件治理」段。

## 完工必检

```
python scripts/check_all.py --quiet
```

无输出 = 机械层通过。每条 FAIL 自带修复指引。

机械层通过后再确认：
- [ ] 有高风险改动且没经过独立视角复查？→ 新上下文或 subagent 复查
- [ ] 本次对话有值得沉淀的记忆？→ 更新 `.agents/memory/` 并同步 AGENTS 内联摘要
- [ ] 纯格式修改/注释修改/同一会话已记录？→ 文档更新可跳过（验证不跳过）

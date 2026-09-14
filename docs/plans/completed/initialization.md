---
status: done
mode: direct-execution
coordinator: ""
created_at: 2026-09-15
---

# 文档体系初始化

## 任务分配表

| 任务 / 阶段 | Owner | 状态 | Reviewer | 备注 |
|------------|-------|------|----------|------|
| 初始化 agent-first 文档体系 | 主 Agent | ✅ completed | reviewer subagent | Step 8 reviewer-perspective 自检 |

## 目标

为 voice2text 建立面向 AI Agent 的文档体系，支撑后续分阶段开发与跨会话协作。

## 规模与模式（用户已确认）

- **规模**：中型（全套 docs/ + plans/ + 记忆系统 + 维护脚本）
- **仓库模式**：Git（初始化新仓库，main 分支）

## 第 0 步 intent 答案

1. **项目做什么**：Windows 语音听写工具，Alt+V 触发，流式识别上屏 + 本地小模型二次校对
2. **技术栈**：Python 3.10+；sherpa-onnx（识别）、llama-cpp-python + Qwen GGUF（校对）、sounddevice（采集）、keyboard（热键）、剪贴板粘贴（上屏）
3. **硬约束**：全离线、模型不入库、一键安装、热键 Alt+V
4. **已有文档**：无（全新空目录）
5. **AI Agent**：ZCode（加载 CLAUDE.md 入口）
6. **构建产物**：models/（~2GB，不入 git）、.venv/
7. **测试**：暂无自动化测试，手动功能验证
8. **协作倾向**：单 Agent 顺序推进（分阶段模式）
9. **常见任务类型**：分阶段开发任务
10. **文档语言**：中文

## 完成记录

- 创建 AGENTS.md 及同步副本（copy 模式）、docs/ 全套（STRUCTURE/overview/deployment/pitfalls/CURRENT/CHANGELOG/audit-checklist）、plans/ 目录、bugfix 模板
- 初始化记忆系统：.agents/memory/MEMORY.md + user/role.md，maintain.py 生成首版索引
- git init + Python pre-commit hook（agent_links 一致性检查）
- 有意省略：docs/api.md（无对外 API）、frontmatter-schemas.md（约定内嵌于模板文件）

## 完成记录（Step 8 自检结果）

- reviewer subagent 仅读 AGENTS.md 通过四问测试：能答出项目用途、禁改文件（模型不入库/离线约束）、完工须跑 check_all.py、复杂任务先落盘计划

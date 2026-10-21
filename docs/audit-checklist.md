# 文档一致性审计清单

> **何时触发**：`python scripts/audit.py check` 报告发现后，或每 ~20 次任务 / 每月主动执行一次。
> **角色**：本文件由 Agent 读取并填写，不是人类维护的文档。

## 1. 机械检查结果复核

运行 `python scripts/audit.py check`，对每个非 OK 项逐条复核。

> **技术栈漂移字典**：新增依赖时同步追加 `scripts/audit.py` 的 `DRIFT_PATTERNS` 关键词；通用字典是起点，不是终点。

- [ ] 死链：是文件被移动了？还是 AGENTS.md 指针过时？
- [ ] STRUCTURE 索引偏差：docs/ 下多了/少了文件？更新索引或清理孤儿文件。
- [ ] 计划目录：active/ 里有已完成或停滞计划？completed/ 混入进行中计划？停滞计划复核后在本次「审计记录」留痕（LINGER 是提醒，不阻塞机械层）。
- [ ] 行数警告：AGENTS.md 超过 250 行？如有内容可下沉到 docs/，执行下沉。
- [ ] 依赖漂移：文档声明的技术栈与实际 manifest 不符？更新文档或确认为误报。
- [ ] 出生档案：缺失则从 Git history / 当前状态重建。
- [ ] 记忆系统：`.agents/memory/MEMORY.md` 空壳或断链？AGENTS.md 内联记忆段缺失或过时？`python scripts/audit.py memory` 逐项复核。
- [ ] 单一入口不变式：根目录无 `CLAUDE.md` / `GEMINI.md` 副本，`scripts/agent_links.py` 不存在。
- [ ] 钩子不变式：`.githooks/pre-commit` 与 `.pre-commit-config.yaml` 不调用同步脚本。

## 2. 关键设计决策仍成立？

重新读取 `docs/overview.md` 中"关键设计决策"段，逐条验证：

- [ ] 对每条决策中提到的技术栈，检查 `requirements.txt` 中是否仍有对应依赖。若文档说"使用 X"但 manifest 已无 → 决策已过时，更新文档。
- [ ] 对每条决策中提到的约束条件（如"CPU 推理""约 1.5 秒停顿"），用 `git log --oneline --since="6 months ago"` 检查是否有相关重构。若有 → 约束可能已失效，需更新。
- [ ] 是否有新的重要决策未记录？浏览最近 CHANGELOG 中涉及架构的变更，确认已反映到 `docs/overview.md`。

## 3. 环境与部署仍准确？

- [ ] 启动命令仍能执行？
- [ ] install.bat 的模型下载源仍有效？
- [ ] models/ 体积与文档描述一致？

## 4. 未记录的重要变更

- [ ] 浏览 CHANGELOG 最近 ~30 天：`python scripts/changelog.py recent --days 30`，是否有架构级变更未反映到 docs/？
- [ ] `git log --oneline --since="1 month ago"` 中是否有被遗漏的重大改动？

## 5. 完工

- [ ] 审计期间的修改已通过 `python scripts/check_all.py --quiet`
- [ ] 审计结果写入 CHANGELOG：
  ```bash
  python scripts/changelog.py add \
    --title "文档一致性审计" \
    --body "机械检查 + 手动裁决完成。修复项：<列出>；确认为误报：<列出>；仍待处理：<列出>"
  ```
- [ ] 将审计日期记录到本文件末尾的"审计记录"中

## 审计记录

<!-- 每次完成审计后在此追加一条记录，格式：YYYY-MM-DD — 审计摘要（发现/修复/遗留） -->
- 2026-09-22 — 首次完整审计。修正 CURRENT 的发行态、输入通道、UIPI、持久化数据和下一版
  边界；为 sherpa-onnx、llama-cpp-python、桌面输入与 GUI 依赖增加漂移检测并补齐设计说明。
  机械检查无遗留；微信、WPS、Windows Terminal 与 VM 仍按 CURRENT 进行真机验收。
- 2026-10-21 — 治理体系升级：清退三文件同步体系（`agent_links.py`、`CLAUDE.md`、
  `GEMINI.md`），脚本与钩子对齐当前 init-agent-docs，补治理文档分级复查规则。
  机械检查（check_all / audit.py check / maintain.py --check）通过；复核全部 4 个活跃计划
  （MVP、性能可靠性、Windows 发行验证、本升级计划），均保持 in_progress 或本日归档，
  等待用户真机验收；计划 LINGER 已降为不阻塞的提醒，不以修改 mtime 消警。
  治理改动经 3 名独立 reviewer 复查，结论见 `docs/plans/completed/governance-upgrade.md`。
  遗留：`docs/CURRENT.md` 中的真机验收项不变。

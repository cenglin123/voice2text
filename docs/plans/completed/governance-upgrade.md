---
status: done
mode: phased
coordinator: DSH Lead
created_at: 2026-10-21
---

# 治理体系升级（对齐 init-agent-docs 当前版）

## 任务分配表

| 任务 / 阶段 | Owner | 状态 | Reviewer | 备注 |
|------------|-------|------|----------|------|
| 阶段 1：清退三文件同步体系 | DSH Lead | ✅ completed | — | 与阶段 2 同一次变更（skill 第 1.7 步要求） |
| 阶段 2：脚本与审计资产对齐 | DSH Lead | ✅ completed | — | audit/check_all/maintain/hook |
| 阶段 3：治理债收敛与规则补齐 | DSH Lead | ✅ completed | — | 计划不跑 mtime 凑数，LINGER 降为提醒 |
| 阶段 4：独立复查（ultraverge） | 3 个独立 reviewer | ✅ completed | — | 覆盖全部准则段改动，提交前完成 |

## 目标

把项目治理体系从「已退役的三文件同步时代」升级到当前 `init-agent-docs` skill 的规范态：
`AGENTS.md` 单一入口、脚本与审计资产无退役残留、治理文档改动有明确的分级复查规则、
机械层（`check_all.py --quiet`、`audit.py check`、`maintain.py --check`）收敛且不产生
为消警而做的凑数编辑。

## 范围（用户已确认）

- 采纳范围 A：核心对齐；删除 `CLAUDE.md`、`GEMINI.md`，单一入口。
- 不采纳：会话级治理提醒（哲学 12）、`worktree_task.py`、`docs/frontmatter-schemas.md`、
  知识库 `.meta/` 布局——本项目单 Agent 顺序推进、治理文档密度不高，按 skill 默认跳过。

## 阶段划分

### 阶段 1：清退三文件同步体系
- **目标**：`AGENTS.md` 成为唯一行为入口，仓库内无可执行的同步依赖与副本。
- **改动**：`git rm CLAUDE.md GEMINI.md scripts/agent_links.py`；AGENTS.md 删除「同步声明」并
  声明单一入口；README 的 AI Agent 指针改为仅 AGENTS.md；hook 内嵌的同步调用在同一变更中移除。
- **验证标准**：三个文件不存在；`.py` / `.bat` / hook 中无 `agent_links` 调用（规范态禁止性表述与
  历史叙事中的提及允许）；`audit.py check` 不再输出 sync 项。

### 阶段 2：脚本与审计资产对齐
- **目标**：治理脚本与当前 skill 行为一致，同时保留项目定制。
- **改动**：
  - `audit.py`：删 `_check_sync` 及其输出/依赖；补 `unquote` 链接解析修复；已归档计划
    不参与 LINGER；时间型 LINGER 降为提醒、不参与退出码（避免 mtime 凑数编辑）。
  - `check_all.py`：删「同步」检查项。
  - `maintain.py`：删 agent_links 步骤并重编号。
  - `.githooks/pre-commit`：按 Python 栈 hook 重写——记忆目录结构兜底（fail-closed）、
    治理文档变更提醒（WARN，只打印 AGENTS 分级指针）、Python 语法兜底；仅当项目显式配置
    lint（`pyproject.toml [tool.ruff]`、`.flake8`、`setup.cfg [flake8]`）才跑风格检查，
    避免 PATH 上偶然存在的 flake8/ruff 用默认规则误伤提交。
  - `.gitattributes`：`.githooks/*` 固定 LF；hook 索引权限设为可执行。
- **验证标准**：各脚本退出码符合预期；hook 正例通过、缺 `MEMORY.md` 时拒绝、非法 Python
  语法时拒绝（用临时文件 + `finally` 恢复，不移动受版本控制的 MEMORY.md，不产生真实提交）。

### 阶段 3：治理债收敛与规则补齐
- **目标**：机械层无遗留；治理文档写明分级复查规则。
- **改动**：
  - AGENTS.md「硬约束」新增「治理文档改动必须独立复查」（准则段 ≥3 reviewer，
    其余治理改动 ≥1；判据是文件性质不是行数），完工必检增加对应勾选项。
  - `docs/audit-checklist.md`：删「同步断裂」、改为「单一入口/钩子不变式」、
    完工口径改为 `check_all.py --quiet`，保留项目特有的 install.bat / models 检查。
  - 复核活跃计划（MVP、性能可靠性、Windows 发行验证），结论记入审计记录；不通过修改
    计划 mtime 来消警。
  - 更新 CURRENT、CHANGELOG（删除/迁移事件单列一条并写明去向）、记忆 touch。
- **验证标准**：`check_all.py --quiet` 无输出且退出 0；`audit.py check` 退出 0（允许打印
  LINGER 提醒）；`maintain.py --check` 退出 0；AGENTS.md ≤250 行且无迁移考古。

### 阶段 4：独立复查（ultraverge）
- **目标**：全部准则段改动经 ≥3 个独立视角复查。
- **做法**：3 个只读 reviewer 分角度（一致性 / 回归与机械 / 规范与歧义）复查；问题修复后
  复跑机械验证，提交前收敛。计划审查（1 个 reviewer）已在执行期完成，其结论中的阻塞项
  已按本计划修正。
- **验证标准**：无未处理阻塞项；非阻塞意见已处理或记录为遗留。

## 独立复查记录

### 计划审查（1 名独立 reviewer，执行期）
- 结论：方向与范围裁剪成立；提出 5 项阻塞（LINGER 验收不可持续、无残留判据自相矛盾、
  阶段门循环依赖、流程顺序、hook 验证安全性）与 7 项建议。
- 处置：阻塞项已全部修正（LINGER 降为提醒不阻塞、验收判据改为可执行、阶段按依赖重排、
  hook 验证改为临时文件 + `finally` 恢复、补计划审查记录）；建议项已并入最终文本或记录为遗留。

### ultraverge（3 名独立 reviewer，提交前）
- 一致性 reviewer（R1）：通过项为范围裁剪正确、同步残留已清、机械层通过、项目定制记录完整、
  钩子 LF 与启用方式正确、文档导航一致；提出 4 项阻塞（计划链接、未完成先声称已复查、
  钩子提示指向已迁移段落、暂存区不完整）与 5 项建议（计划数、LINGER 术语、治理脚本
  范围、语法检查对象、review 状态）。处置：链接随归档同步、复查记录本节、钩子提示改为
  硬约束段、提交前统一 add 并复核、术语统一、规则显式枚举四个脚本、语法检查改读暂存 blob。
- 回归与机械 reviewer（R2）：在临时仓库实测 hook 正反例、LINGER 作用域、退役引用与
  Git 卫生均通过；提出 3 项阻塞（同链接/暂存/`.gitattributes` 未跟踪）与 7 项建议。
  处置：`.gitattributes` 随本次提交入库；hook 的 fail-closed 增加暂存区删除与空 blob 检查；
  `audit.py` 在 AGENTS 仍声明记忆入口时把目录缺失判为 missing；清理未用 import；
  `.pre-commit-config.yaml` 表述限定为“若存在”；CHANGELOG 的 LINGER 术语统一。
  其最终复跑确认 check_all / audit / `bash -n` 均退出 0。
- 规范与歧义 reviewer（R3）：两轮复验；确认规则迁入硬约束、钩子提示与范围对齐、
  审计清单去迁移叙事、STRUCTURE/README 去重、完工必检门槛等旧阻塞关闭。剩余修正：
  准则段最小单位补 `##` 与命令块、独立性改“非 fork 的 subagent”、落盘位置明确、
  catch-all 改用“被 AGENTS.md 引用为规则执行工具”、明确 plans/memory 不属本款。
  处置：已全部写入 AGENTS 硬约束；计划归档与 CURRENT/CHANGELOG 链接同步在提交前完成，
  3 名 reviewer 的结论与证据本节落盘。
- 复验方式：三份结论均为只读独立会话；阻塞项由执行者逐条修正后复跑机械层，R3 对修订后
  文本做了第二轮只读复核（旧阻塞关闭、剩余项当日修正）。

## 验证标准

1. `python scripts/check_all.py --quiet` 无输出、退出 0。
2. `python scripts/audit.py check` 退出 0（LINGER 仅提醒）。
3. `python scripts/maintain.py --check` 退出 0。
4. hook 正反用例符合预期；无同步机制可执行残留；`.gitattributes` 生效。
5. 3 名独立 reviewer 无阻塞性意见；阻塞项修复后已逐条复验并落盘记录。
6. 提交只包含治理相关文件，排除用户本地 `config.json`。

## 完成记录

- 2026-10-21：三文件同步体系清退，`AGENTS.md` 单一入口；`audit.py` / `check_all.py` /
  `maintain.py` / `.githooks/pre-commit` 对齐当前 init-agent-docs 并保留项目定制；
  治理文档分级复查规则进入 AGENTS 硬约束；审计清单、STRUCTURE、README、CURRENT、
  CHANGELOG 与记忆同步。
- 验证：`check_all.py --quiet`（8 项，含 92+10 个回归用例）无输出退出 0；
  `audit.py check` 退出 0；`maintain.py --check` 退出 0；hook 正反例通过；
  计划审查 1 名 + ultraverge 3 名独立 reviewer 结论已落盘。

## 风险与遗留

- 删除 `CLAUDE.md` / `GEMINI.md` 依赖宿主已支持 `AGENTS.md`（当前 skill 的既有结论，用户已确认）。
- hook 为 bash 脚本，需要 Git for Windows 提供解释器；Windows 下 Git 忽略可执行位，
  `.gitattributes` 固定 LF 避免 CRLF 破坏解释器；新克隆需 `git config core.hooksPath .githooks`，
  README 已注明。`--no-verify` 可绕过，属已知边界。
- `LINGER` 不参与退出码、completed 计划不报 LINGER 是项目对上游的有意分歧，已在
  `audit.py` 注释与 CHANGELOG 记录；升级 skill 上游时需重新比对合并。
- 真实宿主会话级提醒（哲学 12）未落地，保持软约束，作为后续可选项。
- 本轮计划审查与执行并行（用户确认范围后即开工），审查结论中的阻塞项已在提交前修正；
  后续复杂任务按「先审后执行」顺序执行。

---
id: bugfix-[slug]
type: bugfix
title: [问题标题]
status: investigating
severity: unknown
liveness: active
last_confirmed: ""
confirmed_count: 0
tags: []
related_files: []
verification:
  level: none
created_at: [YYYY-MM-DD]
updated_at: [YYYY-MM-DD]
---

# [问题标题]

> 本文件是 bugfix 文档写作模板。逐篇索引由 scripts/maintain.py 派生到
> `.agents/memory/MEMORY.md` 索引段，无需手工登记到任何索引文件。
>
> frontmatter 字段说明：
> - status：investigating | mitigated | fixed | wontfix（解决状态）
> - severity：low | medium | high | critical | unknown
> - liveness：active | dormant | archived（活性状态，与 status 正交——已修复的文档
>   也会随时间沉睡；状态变更由维护审计建议、人确认后手改，不由脚本自动改）
> - last_confirmed / confirmed_count：任务前检索命中本文档并实际遵循后，
>   将 last_confirmed 更新为当日、confirmed_count +1（touch 规范，见 AGENTS.md
>   完工检查清单「记忆自检」项）。缺失时维护脚本以 git 最后提交时间兜底——
>   git 修改 ≠ 确认有效，只补日期，不虚增 confirmed_count。
>   时间戳兜底命令：`git log -1 --format=%ai -- <文件路径>`
> - tags / related_files：供检索命中；related_files 必须指向真实存在的文件
> - verification.level：manual | automated | none；为 automated 时必须补
>   verification.kind（如 unit-test / regression-test）+ verification.path +
>   verification.command（真实执行过的命令，禁止臆造）
> - evidence（事实门禁，不是可选字段）：每篇文档应至少有一条 evidence 锚点；
>   找不到任何 evidence 时宁可不写这篇文档，也不编造来源。
>   evidence:
>     - type: commit | error_log | user_quote | conversation_context
>       ref: "短哈希 / 报错特征 / 用户原话 / 会话摘录"
>
> 写作纪律：
> - 只写已确认的事实；未确认部分明确标注"待确认""推测"或"可能原因"
> - 优先写根因和修复机制，不要只写"改了某个文件"
> - 临时规避/回滚也算 bugfix，须明确写这是临时方案及遗留风险
> - 多个独立 bug 分别建文档，不混在一篇

## 现在的行为

<!-- 触发条件、报错现象、影响范围 -->

## 预期的行为

<!-- 系统本来应该怎么工作 -->

## 复现方式

<!-- 前置条件、输入、操作步骤、复现是否稳定 -->

## 原因是什么

<!-- 根因。不能完全确认时，分开写已确认事实与待确认点 -->

## 怎么修复的

<!-- 修复思路、改动点、为什么这样改、为何选此方案 -->

## 验证结果

<!-- 验证命令、范围、结果。无自动化验证时说明原因和人工验证方式 -->

## 风险和后续

<!-- 剩余风险、未覆盖的边界、需要补的测试或后续治理事项 -->

## 变更历史

<!-- 记录关键提交，便于追溯。示例：
- `abc1234` 2026-01-15: 初始修复
- `def5678` 2026-01-16: 补充边界条件处理
-->

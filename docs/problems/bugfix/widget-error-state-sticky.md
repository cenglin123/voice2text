---
id: bugfix-widget-error-state-sticky
type: bugfix
title: 悬浮窗不可用状态不会自动恢复
status: fixed
severity: low
liveness: active
last_confirmed: "2026-09-23"
confirmed_count: 1
tags: [widget, state, error, usability]
related_files: [voice2text/widget.py, scripts/check_widget.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_widget.py
  command: .venv/Scripts/python.exe -X utf8 scripts/check_widget.py
evidence:
  - type: user_quote
    ref: "悬浮窗只要触发过不可用状态，即使选择其它可输入的位置，只要不去启动它以覆盖状态，悬浮窗会一直显示不可用"
created_at: 2026-09-23
updated_at: 2026-09-23
---

# 悬浮窗不可用状态不会自动恢复

## 现在的行为

一次目标捕获或会话启动失败会把悬浮窗置为“不可用”。没有后续状态事件时，该提示永久保留，
即使用户已经把光标移动到其他可输入位置。

## 预期的行为

“不可用”只作为一次失败的短暂反馈；两秒后自动回到“待命中”。期间若收到准备、聆听、校对
等新状态，应取消旧复位任务，不能覆盖新状态。

## 复现方式

将光标放在不可输入位置触发听写，使悬浮窗显示“不可用”，随后移到正常输入框但不再次启动。
原实现会一直保留错误状态。

## 原因是什么

悬浮窗状态机没有错误状态的生命周期。`set_state("error")` 只重绘，没有复位机制。

## 怎么修复的

错误状态进入时创建两秒定时复位；任何新状态先取消旧定时器。定时器触发时再次确认当前仍为
错误状态，才切换回待命，避免迟到回调覆盖有效状态。

## 验证结果

`scripts/check_widget.py` 验证错误态创建复位任务、新状态取消旧任务、复位只把当前错误态改为
待命；悬浮窗全部状态、尺寸、拖动、透明度和 GDI 稳定性检查继续通过。

## 风险和后续

错误详情仍保留在运行输出中；悬浮窗只负责短暂状态提示，因此自动复位不会丢失诊断信息。

## 变更历史

- 2026-09-23: 将不可用状态改为两秒后自动恢复的瞬时提示。

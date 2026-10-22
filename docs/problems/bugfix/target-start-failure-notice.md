---
id: bugfix-target-start-failure-notice
type: bugfix
title: 输入焦点错误导致听写未开始却只有日志提示
status: fixed
severity: medium
liveness: active
last_confirmed: "2026-10-22"
confirmed_count: 1
tags: [focus, widget, notification, usability]
related_files: [voice2text/main.py, voice2text/widget.py, scripts/check_session.py, scripts/check_widget.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_widget.py
  command: .venv/Scripts/python.exe -X utf8 scripts/check_widget.py
created_at: 2026-10-22
updated_at: 2026-10-22
evidence:
  - type: user_quote
    ref: "窗口没有对焦导致进入不了聆听状态，需要显式地提醒，而不是直接变回待命中没有任何反应"
---

# 输入焦点错误导致听写未开始却只有日志提示

## 现在的行为

未聚焦到可输入位置、目标捕获失败或开始录音前焦点验证失败，会经主线程显示原因提示卡。
提示卡不激活、不改变前台窗口，包含重试操作说明；保留 7.5 秒后自动关闭。

## 预期的行为

用户不打开运行输出也能知道听写没有开始及原因，并可重新点击输入框、按快捷键重试。

## 复现方式

把焦点放在不可编辑位置按热键，或目标捕获后、录音启动前让焦点失效。
原实现只有两秒“不可用”及控制台日志，自动回到待命后像没有响应。

## 原因是什么

普通目标捕获异常和后台启动异常没有 UI 原因通知。此前管理员权限异常已有专用警告框，
但不涵盖这两条普通失败路径；错误状态的短期复位也不足以传达原因。

## 怎么修复的

两个失败路径通过命令队列向悬浮窗发送原因，后台失败在 busy 清理后再发消息，避免主线程
因启动仍忙而丢弃提示。通知窗口使用 NOACTIVATE / SHOWNOACTIVATE，并按工作区与 DPI 限位。
悬浮窗隐藏时仍在工作区右下角显示；重复失败替换原卡，不堆叠。错误复位到 idle 保留卡片，
loading/listening/proofreading 或窗口销毁取消旧提示与计时器。

## 验证结果

`check_session.py` 覆盖目标捕获失败、录音前焦点失效，确认排队原因且不启动录音。
`check_widget.py` 在 Windows 验证前台窗口不变、长中文滚动、隐藏悬浮窗、重复提示、
error→idle 保留、loading 清除、销毁清理及 200% DPI 负像素字号和脚注边界。

## 风险和后续

管理员权限不匹配仍使用已有专用警告框。具体应用中的失败原因沿用目标校验，不放宽输入保护。
关联既有状态生命周期见 `widget-error-state-sticky.md`；完整集成记录见自动更新计划。

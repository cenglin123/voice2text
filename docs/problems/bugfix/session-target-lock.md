---
id: bugfix-session-target-lock
type: bugfix
title: 听写失焦后文字或校对可能写到其他位置
status: fixed
severity: high
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [focus, input-target, proofreading, sendinput]
related_files: [voice2text/target.py, voice2text/activity.py, voice2text/input.py, voice2text/main.py, scripts/check_target_desktop.py]
verification:
  level: automated
  kind: integration-test
  path: scripts/check_target_desktop.py
  command: python scripts/check_target_desktop.py
evidence:
  - type: user_quote
    ref: "识别开始后到校对结束为止，输出位置要在同一个地方操作"
created_at: 2026-09-19
updated_at: 2026-09-19
---

# 听写失焦后文字或校对可能写到其他位置

## 现在的行为

旧逻辑只检查当下是否可编辑。窗口切换后，流式结果或停止后的校对可能失去原始输入位置，继续写入会影响其他控件。

## 预期的行为

开始听写时锁定输入目标，从流式识别、尾句排空到校对结束始终恢复并验证同一位置；无法安全恢复时停止写入并保留已有文字。

## 复现方式

开始听写后切换到另一个窗口，或在校对前关闭原窗口、切换同一窗口内的控件。

## 原因是什么

会话没有保存目标窗口与控件身份，注入和校对只依赖瞬时前台焦点。

## 怎么修复的

开始时捕获窗口、进程、线程、原生焦点和普通控件 RuntimeId；每批注入前核对，主循环持续恢复原前台。目标关闭、句柄身份变化或同窗换控件时关闭写入闸门。物理键盘编辑或在原窗口内点击会终止本次上屏，避免用旧记账退格用户的新内容。

## 验证结果

独立桌面测试创建两个隔离编辑窗，验证失焦后恢复原窗口、校对只替换原窗口、目标关闭后不向第二窗口写入。单元回归覆盖恢复失败、批次中失焦、迟到回调和尾句排空顺序。

## 风险和后续

Windows 的前台切换策略和 UIPI 仍可能拒绝恢复；此时按设计停止写入，不尝试绕过权限。

## 变更历史

- 2026-09-19: 引入会话目标锁定、活动保护与生命周期闸门。

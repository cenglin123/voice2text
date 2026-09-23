---
id: bugfix-admin-target-warning-hidden-in-log
type: bugfix
title: 管理员目标窗口的权限提示只在运行输出中可见
status: fixed
severity: medium
liveness: active
last_confirmed: 2026-09-23
confirmed_count: 1
tags: [Windows, UIPI, elevation, UI, dictation]
related_files: [voice2text/target.py, voice2text/main.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: user_quote
    ref: "有一些对话框，他就会存在管理员权限，然后这个就静默失效，就没有办法把文字给输入上去"
created_at: 2026-09-23
updated_at: 2026-09-23
---

# 管理员目标窗口的权限提示只在运行输出中可见

## 现在的行为

普通权限的 voice2text 面对已提权目标时，目标捕获逻辑会拒绝听写并在运行输出打印原因；
悬浮窗只短暂显示“不可用”，未直接告诉用户权限失配及处理办法。

## 预期的行为

明确检测到管理员目标时，听写不开始，界面直接显示可操作的原因与解决办法。

## 复现方式

以普通权限启动 voice2text，把焦点放在管理员权限运行的应用输入区，按热键。
已有目标捕获回归覆盖权限失配；用户报告实际体验仍像静默失效。

## 原因是什么

目标捕获的 `RuntimeError` 包含完整说明，但通用异常路径只将其写入运行输出并将悬浮窗切到
两秒“不可用”状态。正常托盘运行时控制台隐藏，原因因此不易发现。

## 怎么修复的

用专门的 `ElevatedTargetError` 标识已经确认的权限失配，经主线程命令队列显示 Windows 警告对话框。
继续拒绝开始听写，不自动提权，也不向可能被 UIPI 拦截的窗口盲写。

## 验证结果

权限专项 10 项与会话回归 83 项通过；新增用例确认提权失配会排队显示提示且不会开始会话。
真实管理员窗口中的对话框可见性仍需设备人工复验。

## 风险和后续

令牌查询结果不明确时沿用既有放行策略，避免把普通窗口误判为提权；此类目标若仍无法上屏，
需结合运行输出和目标进程权限继续定位。警告对话框为模态窗口，仅在明确的权限失配时出现。

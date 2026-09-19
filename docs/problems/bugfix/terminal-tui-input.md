---
id: bugfix-terminal-tui-input
type: bugfix
title: OpenCode TUI 听写已启动但没有文字
status: fixed
severity: high
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [terminal, tui, opencode, uia, sendinput]
related_files: [voice2text/target.py, voice2text/input.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: user_quote
    ref: "悬浮窗变红，但 TUI 不出现文字"
created_at: 2026-09-19
updated_at: 2026-09-19
---

# OpenCode TUI 听写已启动但没有文字

## 现在的行为

热键和识别会话已经启动，悬浮窗进入红色聆听状态，但 Windows Terminal 中的 OpenCode 输入区没有文字。

## 预期的行为

终端 TUI 与普通编辑框一样接收离线识别结果。

## 复现方式

聚焦 OpenCode TUI 的对话输入区，按快捷键开始听写并说话。

## 原因是什么

终端是自绘界面，通常不暴露稳定的 UIA Edit/ValuePattern；TUI 重绘还可能更换 UIA RuntimeId。普通文本框的可编辑检测因此在首批注入前拒绝终端。

## 怎么修复的

对已知 Windows 终端窗口类使用稳定的原生窗口、进程、线程和焦点句柄身份；不保存随 TUI 重绘变化的 UIA RuntimeId。普通应用仍要求可写 UIA 控件，避免扩大盲写范围。

## 验证结果

回归测试覆盖终端无 UIA 控件、终端非 Edit 控件、普通未知控件拒绝和同窗口控件变化拒绝；Unicode 注入另由独立编辑窗口验证。OpenCode 的实际语音输入仍需用户在其当前 TUI 会话中做最终体验验收。

## 风险和后续

新终端实现如使用未列出的窗口类，需要按其稳定原生身份补充兼容。

## 变更历史

- 2026-09-19: 增加终端目标路径并移除 TUI RuntimeId 依赖。

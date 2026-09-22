---
id: bugfix-terminal-tui-input
type: bugfix
title: Windows Terminal / OpenCode TUI 听写已启动但没有文字
status: mitigated
severity: high
liveness: active
last_confirmed: "2026-09-22"
confirmed_count: 3
tags: [terminal, tui, opencode, uia, sendinput, clipboard]
related_files: [voice2text/target.py, voice2text/input.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: user_quote
    ref: "悬浮窗变红，但 TUI 不出现文字"
  - type: error_log
    ref: "windowsterminal 的 partial_write 连续记录 ok 且耗时约 0.1ms，但终端没有显示文字"
  - type: error_log
    ref: "改用受保护 Ctrl+V 后 partial_write 中位数约 170ms 且全部记录 ok，但终端仍没有文字；Alt+V 首次捕获报告无法验证目标输入控件"
created_at: 2026-09-19
updated_at: 2026-09-22
---

# Windows Terminal / OpenCode TUI 听写已启动但没有文字

## 现在的行为

热键和识别会话已经启动，悬浮窗进入红色聆听状态，但 Windows Terminal 输入区没有文字。运行日志中的目标恢复、识别、标点和 `partial_write` 均显示成功。

## 预期的行为

终端 TUI 与普通编辑框一样接收离线识别结果。

## 复现方式

聚焦 OpenCode TUI 的对话输入区，按快捷键开始听写并说话。

## 原因是什么

这个问题分为两层：

1. 终端是自绘界面，通常不暴露稳定的 UIA Edit/ValuePattern；TUI 重绘还可能更换 UIA RuntimeId。普通文本框的可编辑检测会在首批注入前拒绝终端。
2. 目标身份修复后，Windows Terminal 可以开始听写，但不会消费 `VK_PACKET` Unicode 注入。`SendInput` 返回成功只代表事件已提交到系统输入队列，不能证明目标应用已接收文字。因此日志会出现 `partial_write [ok]`，界面却没有文本。
3. 首次剪贴板修复只按进程切换传输方式，却仍发送 Ctrl+V。用户真机日志显示该路径耗时已经符合剪贴板事务特征，但 Windows Terminal 仍没有文字；同时，部分启动状态下顶层宿主窗口类未命中终端类白名单，导致 Alt+V 已触发却在捕获阶段被普通 UIA 校验拒绝。

## 怎么修复的

对已知 Windows 终端窗口类使用稳定的原生窗口、进程、线程和焦点句柄身份；不保存随 TUI 重绘变化的 UIA RuntimeId。普通应用仍要求可写 UIA 控件，避免扩大盲写范围。

Windows Terminal 的文字传输改用受保护剪贴板粘贴：临时内容不进入 Win+V 和云剪贴板历史，粘贴后恢复用户原剪贴板。终端改发专用的 Ctrl+Shift+V 粘贴组合键；微信等普通 GUI 输入框继续使用 Ctrl+V。

终端识别同时增加 `windowsterminal` 进程名兜底，不再只依赖可能随系统版本、启动方式和窗口状态变化的 XAML 宿主窗口类。

## 验证结果

自动回归覆盖终端无 UIA 控件、终端非 Edit 控件、普通未知控件拒绝、同窗口控件变化拒绝、宿主类变化时按进程识别终端，并确认 Windows Terminal 选择受保护剪贴板和 Ctrl+Shift+V。Windows Terminal 的实际语音输入仍需用户在当前终端会话中做最终体验验收。

## 风险和后续

受保护粘贴比单次 `VK_PACKET` 注入慢，但通常仍低于当前约 250ms 的识别更新周期。若用户自行取消 Windows Terminal 的 Ctrl+Shift+V 粘贴绑定，这一路径将无法工作；真机复验前状态保持为 mitigated。

## 变更历史

- 2026-09-19: 增加终端目标路径并移除 TUI RuntimeId 依赖。
- 2026-09-22: Windows Terminal 改用受保护剪贴板粘贴，修复输入事件提交成功但界面无文字的回归。
- 2026-09-22: 根据分发端日志改用 Ctrl+Shift+V，并增加进程名终端识别兜底；等待真机复验。

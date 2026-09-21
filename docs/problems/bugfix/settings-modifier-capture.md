---
id: bugfix-settings-modifier-capture
type: bugfix
title: 设置快捷键时修饰键捕获错误
status: fixed
severity: medium
liveness: active
last_confirmed: "2026-09-21"
confirmed_count: 2
tags: [gui, hotkey]
related_files: [voice2text/settings_window.py, scripts/check_settings.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_settings.py
  command: .venv\Scripts\python.exe scripts\check_settings.py
evidence:
  - type: conversation_context
    ref: "设置页验证发现 capture_key 对修饰键返回的 None 也调用 _finish_capture，按 Ctrl 后尚未按字母即结束捕获。"
  - type: user_quote
    ref: "设置快捷键的时候，如果按单按键，比如 Pause，那么会变成 ALT + Pause，按其它的按键也是如此"
created_at: 2026-09-18
updated_at: 2026-09-21
---

# 设置快捷键时修饰键捕获错误

## 复现与原因

首次问题是点击修改快捷键后先按 Ctrl 再按字母，捕获会在修饰键事件时提前结束。后续发现单独
按 `Pause` 等按键会被保存成 `Alt+Pause`，而且实现明确拒绝无 Ctrl/Alt 的单键。

## 修复与预期

无有效组合时继续等待，只有有效按键或 Escape 才结束。捕获绑定限制在设置窗口，通过绑定 ID
清理，关闭窗口也清理捕获。修复后的实现不再从 Tk `event.state` 推断修饰键，而是只记录本次
捕获过程中实际发生的 Ctrl、Alt、Shift 按下与释放；因此系统遗留状态不会给普通按键附加 Alt，
同时允许 `Pause`、F 键等单键原样保存。

## 验证与边界

`scripts/check_settings.py` 覆盖纯规范化与真实 Tk 捕获事件：单按 `Pause` 得到 `pause`，单按 F8
得到 `f8`，按住 Ctrl 再按 K 得到 `ctrl+k`，Ctrl+Shift+K 的顺序稳定；`keyboard` 库也能解析
`pause`。真实物理键盘仍保留为发行前手感验收。

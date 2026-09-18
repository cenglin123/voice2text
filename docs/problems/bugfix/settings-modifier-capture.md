---
id: bugfix-settings-modifier-capture
type: bugfix
title: 设置快捷键时按下修饰键立即退出捕获
status: fixed
severity: medium
liveness: active
last_confirmed: "2026-09-18"
confirmed_count: 1
tags: [gui, hotkey]
related_files: [voice2text/settings_window.py]
verification:
  level: manual
evidence:
  - type: conversation_context
    ref: "设置页验证发现 capture_key 对修饰键返回的 None 也调用 _finish_capture，按 Ctrl 后尚未按字母即结束捕获。"
created_at: 2026-09-18
updated_at: 2026-09-18
---

# 设置快捷键时按下修饰键立即退出捕获

## 复现与原因

点击修改快捷键，先按 Ctrl 再按字母。原实现会对修饰键事件调用结束捕获；此时规范化返回 None，后续字母已无法组成快捷键。

## 修复与预期

无有效组合时继续等待，只有有效组合或 Escape 才结束。捕获绑定限制在设置窗口，通过绑定 ID 清理，关闭窗口也清理捕获；避免 bind_all/unbind_all 干扰其他窗口。

## 验证与边界

本次临时 Tk 验证脚本依次生成 Control_L 与 Ctrl+K 事件，确认前者保持捕获、后者得到 ctrl+k；再次捕获后生成 Escape，确认取消捕获而不关闭窗口。保存回读成功。真实系统热键重绑定和输入法环境仍属真机听写验收范围。

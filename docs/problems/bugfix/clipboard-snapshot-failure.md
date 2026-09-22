---
id: bugfix-clipboard-snapshot-failure
type: bugfix
title: 临时粘贴备份失败时可能清空用户剪贴板
status: fixed
severity: high
liveness: active
last_confirmed: "2026-09-22"
confirmed_count: 1
tags: [clipboard, ole, paste, data-loss]
related_files: [voice2text/clipboard_tx.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: conversation_context
    ref: "隔离模拟确认 OleGetClipboard 失败后仍发布临时文本，并在 finally 中调用 _empty"
created_at: 2026-09-22
updated_at: 2026-09-22
---

# 临时粘贴备份失败时可能清空用户剪贴板

## 现在的行为

受保护剪贴板路径在 `OleGetClipboard` 备份失败时把异常等同于“原剪贴板为空”，随后仍覆盖
剪贴板；事务结束后又调用清空，用户原有但暂时无法读取的内容可能丢失。

## 预期的行为

只有成功备份原内容或确认剪贴板确实为空后，才允许发布临时听写文本。

## 复现方式

隔离模拟 `OleGetClipboard` 持续抛出 COM 错误，同时让临时文本发布成功。旧实现会依次调用
发布与清空。

## 原因是什么

`original = None` 同时表示“剪贴板为空”和“备份读取失败”，恢复阶段无法区分这两种状态。

## 怎么修复的

发布前先用 `CountClipboardFormats` 区分空剪贴板；非空时重试 OLE 快照。重试仍失败则抛出
明确的 `OSError` 并终止本次写入，绝不发布或清空剪贴板。空剪贴板仍可正常使用，并在粘贴
后恢复为空。

## 验证结果

`python scripts/check_session.py` 的 68 项测试通过，覆盖非空剪贴板快照失败不发布、不清空，
空剪贴板可正常发布并恢复为空，以及系统性失败会携带明确原因停止当前输入会话。

## 风险和后续

剪贴板被其他程序持续独占时，本次听写写入会明确失败并停止；这是保护用户数据的预期取舍。

## 变更历史

- 2026-09-22: 区分空剪贴板与备份失败，失败时在覆盖前终止。

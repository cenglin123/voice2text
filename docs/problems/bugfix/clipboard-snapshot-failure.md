---
id: bugfix-clipboard-snapshot-failure
type: bugfix
title: 临时粘贴失败或竞争时可能损坏正文与用户剪贴板
status: fixed
severity: high
liveness: active
last_confirmed: "2026-09-22"
confirmed_count: 2
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

# 临时粘贴失败或竞争时可能损坏正文与用户剪贴板

## 现在的行为

受保护剪贴板路径在 `OleGetClipboard` 备份失败时把异常等同于“原剪贴板为空”，随后仍覆盖
剪贴板；事务结束后又调用清空，用户原有但暂时无法读取的内容可能丢失。
刷新已有 partial 时还会先退格删除分歧尾部，再准备临时剪贴板；若备份或发布失败，正文已经
被删。快照与发布分两次打开剪贴板，期间发生的用户复制也可能被覆盖。

## 预期的行为

只有成功备份原内容或确认剪贴板确实为空后，才允许发布临时听写文本。

## 复现方式

隔离模拟 `OleGetClipboard` 持续抛出 COM 错误，同时让临时文本发布成功。旧实现会依次调用
发布与清空。

## 原因是什么

`original = None` 同时表示“剪贴板为空”和“备份读取失败”，恢复阶段无法区分这两种状态。

## 怎么修复的

发布前先用 `CountClipboardFormats` 区分空剪贴板；非空时重试 OLE 快照。快照前后校验
clipboard sequence，并在持有剪贴板锁时再次核对序列号，发现并发复制就停止而不清空。
发布中途失败时，仅在序列号仍属于本事务时恢复原 IDataObject。刷新已有文字时先完成上述
备份和发布，再执行退格与粘贴，因此准备失败不会先删正文。

## 验证结果

`python scripts/check_session.py` 的 74 项测试通过，覆盖快照失败、快照后并发复制、发布中途
失败、发布后外部复制，以及刷新已有正文时预检失败不退格。

## 风险和后续

剪贴板被其他程序持续独占时，本次听写写入会明确失败并停止；这是保护用户数据的预期取舍。
临时文本成功发布后，目标应用仍可能拒绝实际粘贴；键盘注入本身无法做成跨进程原子事务，
失败后会关闭当前会话，避免继续按错误账本删除。

## 变更历史

- 2026-09-22: 区分空剪贴板与备份失败，失败时在覆盖前终止。
- 2026-09-22: 增加序列号竞争保护，并把刷新顺序改为先发布、后删除。

---
id: bugfix-wps-custom-editor-target-detection
type: bugfix
title: WPS 自绘编辑区无法通过 UIA 可编辑验证
status: mitigated
severity: high
liveness: active
last_confirmed: 2026-09-20
confirmed_count: 1
tags: [WPS, UIA, input-target, native-focus]
related_files: [voice2text/target.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: user_quote
    ref: "WPS 中依然无法识别；连续输出‘无法验证目标输入控件，听写未开始’"
  - type: error_log
    ref: "[听写未开始] 无法验证目标输入控件，听写未开始"
created_at: 2026-09-20
updated_at: 2026-09-20
---

# WPS 自绘编辑区无法通过 UIA 可编辑验证

## 现在的行为

光标位于 WPS 文档编辑区时按 Alt+V，目标捕获在 UIA 验证阶段失败，听写不会开始。

## 预期的行为

WPS 文字、表格和演示的自绘编辑区应能以稳定原生窗口焦点作为输入目标；其他未知且无法验证
的控件仍应拒绝输入。

## 复现方式

在 WPS 文档正文中放置光标并按 Alt+V，运行输出显示“无法验证目标输入控件，听写未开始”。

## 原因是什么

目标捕获要求所有非终端应用都提供 UIA `EditControl`/`DocumentControl`、RuntimeId 和可编辑
ValuePattern。WPS 的文档画布使用自绘控件，无法稳定提供这组标准 UIA 属性，但已有原生前台
窗口、进程、线程和焦点 HWND 可用于会话锁定。

## 怎么修复的

仅对 WPS 套件进程 `wps`、`et`、`wpp` 启用原生焦点兜底：开始时仍验证前台窗口、进程、线程
和焦点 HWND，后续每批输入继续核对这些身份并受物理输入活动守卫保护。其他应用继续执行严格
UIA 可编辑验证。

## 验证结果

`python scripts/check_session.py` 通过 45 项测试；回归覆盖三个 WPS 进程在 UIA 不返回控件时
仍能捕获稳定原生焦点，以及未知应用同样情况仍被拒绝。真实 WPS 文档需用新包复验。

## 风险和后续

WPS 菜单或非编辑区也可能拥有原生焦点；用户应先把光标放入正文再启动。若 WPS 将来提供稳定
UIA 文本模式，可恢复更细粒度的控件身份检查。

## 变更历史

- 待提交：增加 WPS 套件原生焦点兜底与回归测试。

---
id: bugfix-wps-custom-editor-target-detection
type: bugfix
title: WPS 自绘编辑区无法通过 UIA 可编辑验证
status: mitigated
severity: high
liveness: active
last_confirmed: 2026-09-20
confirmed_count: 3
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
  - type: user_quote
    ref: "WPS Excel 单元格显示‘目标锁定 wps’，但悬浮窗仍是待命中"
  - type: error_log
    ref: "[目标锁定] wps 后紧接‘原输入窗口已关闭或焦点无法安全恢复’"
created_at: 2026-09-20
updated_at: 2026-09-20
---

# WPS 自绘编辑区无法通过 UIA 可编辑验证

## 现在的行为

光标位于 WPS 文档编辑区时按 Alt+V，目标捕获在 UIA 验证阶段失败，听写不会开始。
表格单元格场景即使已输出“目标锁定”，Alt 释放或单元格进入编辑态时焦点子窗口仍可能变化，
启动线程会静默放弃会话，悬浮窗回到待命。

## 预期的行为

WPS 文字、表格和演示的自绘编辑区应能以稳定原生窗口焦点作为输入目标；其他未知且无法验证
的控件仍应拒绝输入。

## 复现方式

在 WPS 文档正文中放置光标并按 Alt+V，运行输出显示“无法验证目标输入控件，听写未开始”。

## 原因是什么

目标捕获要求所有非终端应用都提供 UIA `EditControl`/`DocumentControl`、RuntimeId 和可编辑
ValuePattern。WPS 的文档画布使用自绘控件，无法稳定提供这组标准 UIA 属性，但已有原生前台
窗口、进程、线程和焦点 HWND 可用于会话锁定。

WPS 表格的焦点 HWND 会在同一 WPS 顶层窗口和进程内切换。旧兜底仍把捕获瞬间的焦点 HWND
当成不可变化的身份，因此目标捕获成功后，录音启动前的再次检查仍可能失败。

进一步确认：单元格编辑焦点还可能转移到同进程的另一 GUI 线程。继续用顶层窗口创建线程调用
`GetGUIThreadInfo` 会得到空焦点，从而错误报告原窗口已关闭。

## 怎么修复的

仅对 WPS 套件进程 `wps`、`et`、`wpp` 启用原生焦点兜底：开始时仍验证前台窗口、进程、线程
和焦点 HWND，后续每批输入继续核对这些身份并受物理输入活动守卫保护。其他应用继续执行严格
UIA 可编辑验证。

会话期间允许 WPS 在同一锁定顶层窗口、同一进程内切换焦点子窗口；前台窗口或进程变化仍会
关闸。目标锁定后悬浮窗立即进入准备状态，启动复查失败则明确输出原因并显示错误状态。
WPS 复查通过 `GetGUIThreadInfo(0)` 读取当前前台线程队列的真实焦点，再验证该焦点仍属于锁定
进程，不再假定焦点始终归属于顶层窗口的创建线程。

## 验证结果

`python scripts/check_session.py` 通过 50 项测试；回归覆盖三个 WPS 进程在 UIA 不返回控件时
仍能捕获目标、单元格编辑器焦点转移到同进程另一线程后仍有效，以及未知应用同样情况仍被
拒绝。真实 WPS 表格需用当前源码复验。

## 风险和后续

WPS 菜单或非编辑区也可能拥有原生焦点；用户应先把光标放入正文再启动。若 WPS 将来提供稳定
UIA 文本模式，可恢复更细粒度的控件身份检查。

## 变更历史

- 待提交：增加 WPS 套件原生焦点兜底与回归测试。
- 待提交：允许 WPS 同进程焦点子窗口切换，并补齐启动状态反馈。
- 待提交：WPS 焦点复查改用当前前台线程的 GUI 焦点。

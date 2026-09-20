---
id: bugfix-wps-custom-editor-target-detection
type: bugfix
title: WPS 自绘编辑区无法通过 UIA 可编辑验证
status: investigating
severity: high
liveness: active
last_confirmed: 2026-09-20
confirmed_count: 5
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
  - type: user_quote
    ref: "改用当前前台线程焦点后，WPS 仍在目标锁定后报告焦点无法安全恢复"
  - type: error_log
    ref: "真机快照显示顶层 OpusApp PID 37592，而 EXCEL6 焦点 PID 33964"
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

显式句柄快照已确认：WPS 顶层 `OpusApp` 与实际获得焦点的 `EXCEL6` 编辑控件属于两个不同
PID。旧逻辑只允许焦点 PID 等于顶层 PID，因此目标捕获虽然成功，首次恢复检查必然失败。
这不是热键释放时序或瞬时空焦点问题。

## 怎么修复的

仅对 WPS 套件进程 `wps`、`et`、`wpp` 启用原生焦点兜底：开始时仍验证前台窗口、进程、线程
和焦点 HWND，后续每批输入继续核对这些身份并受物理输入活动守卫保护。其他应用继续执行严格
UIA 可编辑验证。

会话期间允许 WPS 在同一锁定顶层窗口、同一进程内切换焦点子窗口；前台窗口或进程变化仍会
关闸。目标锁定后悬浮窗立即进入准备状态，启动复查失败则明确输出原因并显示错误状态。
WPS 复查通过 `GetGUIThreadInfo(0)` 读取当前前台线程队列的真实焦点，再验证该焦点仍属于锁定
进程，不再假定焦点始终归属于顶层窗口的创建线程。
若 WPS 当前前台 HWND 仍属于锁定进程，则允许顶层 HWND 变化；热键释放阶段焦点句柄短暂为空
也视为有效。切到其他进程仍立即关闸，WPS 内的物理输入仍由活动守卫停止会话。
全局热键注册改为在组合键释放后调用切换回调，使目标捕获和首次恢复检查发生在 Alt+V 已完整
释放之后；重新绑定快捷键也使用同一触发方式。
捕获时分别记录顶层 PID/TID 和实际焦点 PID/TID。WPS 会话保持顶层进程在前台，并只接受焦点
仍属于捕获时顶层进程或编辑进程；其他任意进程仍会立即关闸。

## 验证结果

`python scripts/check_session.py` 通过 56 项测试；回归覆盖三个 WPS 进程在 UIA 不返回控件时
仍能捕获目标、单元格编辑器焦点转移到同进程另一线程后仍有效，以及未知应用同样情况仍被
拒绝；另覆盖同进程前台 HWND 切换、焦点短暂为空、原顶层 HWND 被重建的启动窗口，以及热键
只在组合键释放后回调；新增真实快照结构的跨进程编辑焦点回归。真实 WPS 表格需用当前源码复验。

## 风险和后续

WPS 菜单或非编辑区也可能拥有原生焦点；用户应先把光标放入正文再启动。若 WPS 将来提供稳定
UIA 文本模式，可恢复更细粒度的控件身份检查。

## 变更历史

- 待提交：增加 WPS 套件原生焦点兜底与回归测试。
- 待提交：允许 WPS 同进程焦点子窗口切换，并补齐启动状态反馈。
- 待提交：WPS 焦点复查改用当前前台线程的 GUI 焦点。
- 待提交：WPS 以锁定进程为边界，容忍同进程顶层窗口变化和瞬时空焦点。
- 待提交：Alt+V 完整释放后再捕获 WPS 输入目标。
- 待提交：同时锁定 WPS 顶层进程与实际编辑焦点进程。

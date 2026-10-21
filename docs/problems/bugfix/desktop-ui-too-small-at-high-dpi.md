---
id: bugfix-desktop-ui-too-small-at-high-dpi
type: bugfix
title: 高 DPI 屏幕上悬浮窗和设置界面偏小
status: mitigated
severity: medium
liveness: active
last_confirmed: 2026-10-22
confirmed_count: 2
tags: [Windows, DPI, widget, settings, tray-menu]
related_files: [voice2text/dpi.py, voice2text/widget.py, voice2text/settings_window.py, voice2text/tray_menu.py, scripts/check_widget.py, scripts/check_settings.py, scripts/check_tray_menu.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_settings.py
  command: python scripts/check_settings.py --dpi 2
evidence:
  - type: user_quote
    ref: "在高清、高缩放屏幕上（笔记本居多），悬浮窗和设置界面会显得很小"
created_at: 2026-09-23
updated_at: 2026-10-22
---

# 高 DPI 屏幕上悬浮窗和设置界面偏小

## 现在的行为

用户确认 v0.1.4 的高 DPI 真机整体仍偏小。模拟放大几何尺寸通过，不能证明实际字号正确。

## 预期的行为

用户的窗口大小和字体偏好表示相对倍率；同一偏好在不同系统缩放下应接近同样的视觉尺寸。
拖拽悬浮窗后写回设置的也应是用户倍率，而非混入系统 DPI 的物理倍率。

## 复现方式

在 Windows 显示设置中选 150% 或 200% 缩放，再打开悬浮窗与设置页，和 100% 下比较。

## 原因是什么

UIAutomation 的导入副作用先设定 PMv1，而界面只读取系统 DPI，混合缩放显示器上倍率不匹配。
设置页还按屏宽降低整套界面倍率。文字缩放有两个独立问题：`Font.cget("size")` 会把声明的
像素字号转成点数；配置字体元组时把 underline/overstrike 的 0 值当样式传给 Tk，引发
TclError 后被捕获忽略，因此正文可能没有随控件放大。

## 怎么修复的

应用在导入 UIAutomation 前主动声明 PMv1；定位后通过 GetDpiForWindow 获取窗口倍率。
悬浮窗跨屏重算尺寸但保留用户倍率，托盘每次弹出重新定位和取 DPI。设置页打开到悬浮窗
所在屏，窗口限制在该屏工作区，内容滚动而非缩小整套字体。
保留字体声明中的负像素大小，只传合法样式；预览位置和字号同样按 DPI 换算。

## 验证结果

窗口 DPI API、64 位 HWND、旧 API 回退与负坐标工作区回归通过；实际进程导入确认 PMv1。
设置页 100%/150%/200% 与 135% 字体的回归覆盖实际字号、分类可见性、负坐标定位和保存。
截图目视检查覆盖常规、识别与校对、关于页；悬浮窗和托盘回归通过。
高 DPI 笔记本及双屏迁移尚待用户真机复验，保留 mitigated 状态。

## 风险和后续

采用 PMv1，尚未切换 PMv2。设置页在打开时选屏并缩放，已打开的设置页跨屏后不动态重建；
可关闭后从目标屏幕的悬浮窗重新打开。悬浮窗跨屏与隐藏菜单换屏行为仍需双屏实测。

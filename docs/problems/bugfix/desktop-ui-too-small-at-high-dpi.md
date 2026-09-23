---
id: bugfix-desktop-ui-too-small-at-high-dpi
type: bugfix
title: 高 DPI 屏幕上悬浮窗和设置界面偏小
status: fixed
severity: medium
liveness: active
last_confirmed: 2026-09-23
confirmed_count: 1
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
updated_at: 2026-09-23
---

# 高 DPI 屏幕上悬浮窗和设置界面偏小

## 现在的行为

程序声明自己具备系统 DPI 感知，但悬浮窗和设置页仍用固定物理像素绘制。系统缩放升高后，
它们在屏幕上的实际视觉尺寸变小。

## 预期的行为

用户的窗口大小和字体偏好表示相对倍率；同一偏好在不同系统缩放下应接近同样的视觉尺寸。
拖拽悬浮窗后写回设置的也应是用户倍率，而非混入系统 DPI 的物理倍率。

## 复现方式

在 Windows 显示设置中选 150% 或 200% 缩放，再打开悬浮窗与设置页，和 100% 下比较。

## 原因是什么

`SetProcessDpiAwareness(1)` 将进程设为系统 DPI 感知，Windows 因此不再放大应用自行绘制的固定
像素界面；原代码未读取系统 DPI 来换算悬浮窗和设置页的几何尺寸。

## 怎么修复的

读取系统 DPI，按 96 DPI 基准放大悬浮窗的绘制、命中区域与拖拽界限；回写配置前除去 DPI 倍率。
设置页同步放大窗口、字体、卡片、滑块、按钮和圆角；小屏幕限制倍率以保持侧栏与页脚可用。
托盘自绘菜单把逻辑画布缩放到物理尺寸，点击命中坐标逆向换算。

## 验证结果

设置页在 150%/200% 模拟倍率下通过几何和保存检查；悬浮窗在 150% 下通过大小与拖拽同步检查；
托盘菜单在 150% 下通过图像与点击区域检查。当前桌面会话无法使用屏幕抓取 API，仍需在真实
高 DPI 笔记本上确认最终显示效果。

## 风险和后续

当前采用 system-DPI-aware 模式；把窗口移到 DPI 不同的第二块屏幕时由 Windows 负责系统级
缩放，可能出现轻微位图模糊。若未来要求跨屏始终像素清晰，需要整体升级 per-monitor DPI
模式并处理窗口迁移事件。

---
id: bugfix-tray-icon-invisible-on-light-taskbar
type: bugfix
title: 白色托盘图标在浅色任务栏上难以辨认
status: fixed
severity: low
liveness: active
last_confirmed: 2026-09-23
confirmed_count: 1
tags: [Windows, tray, icon, contrast]
related_files: [voice2text/trayicon.py, scripts/generate_app_icon.py, scripts/check_tray_menu.py]
verification:
  level: manual
evidence:
  - type: user_quote
    ref: "当前托盘图标为白色，电脑的颜色处于浅色配置时就看不清"
created_at: 2026-09-23
updated_at: 2026-09-23
---

# 白色托盘图标在浅色任务栏上难以辨认

## 现在的行为

待命图标是透明底上的白色麦克风。浅色任务栏会使轮廓几乎消失。

## 预期的行为

四种状态在浅色和深色任务栏上都可辨认，待命麦克风保持醒目。

## 复现方式

将 Windows 颜色模式切成浅色，查看右下角托盘待命图标。

## 原因是什么

托盘图标只绘制浅色麦克风，未给透明图像提供对浅色背景有对比度的底色。

## 怎么修复的

为托盘四种状态统一加入深蓝圆角底和蓝色描边；麦克风继续按白、红、蓝、灰色表达状态。
生成应用 ICO 时仍使用已有外层背景，避免双层边框。

## 验证结果

将四种状态图标合成在模拟浅色和深色任务栏背景上目视检查，均能分辨图标与状态。
真实 Windows 浅色任务栏仍需在用户设备复验。

## 风险和后续

Windows 托盘缩到 16px 时细节会减少，因此保留大色块和粗线条。系统自定义强调色可能改变
任务栏背景，深蓝底仍提供稳定对比。

---
id: bugfix-settings-corner-mask-inset
type: bugfix
title: 设置窗口四角出现向内的蓝色块
status: fixed
severity: low
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [settings, window, rounded-corners, tkinter]
related_files:
  - voice2text/settings_window.py
  - scripts/check_settings.py
verification:
  level: automated
  kind: regression-test
  path: scripts/check_settings.py
  command: .venv/Scripts/python.exe scripts/check_settings.py --capture .tmp/settings-corners.png
evidence:
  - type: user_quote
    ref: "现在边缘四角有向内的东西"
created_at: 2026-09-19
updated_at: 2026-09-19
---

# 设置窗口四角出现向内的蓝色块

## 现在的行为

设置窗口使用透明色角罩后，四角内侧出现明显的蓝色四分之一圆块，尤其在左右两侧背景色不同时更醒目。

## 预期的行为

四角外侧透明，内侧应与对应区域的背景连续，只保留一条细圆弧边框。

## 复现方式

打开设置窗口即可稳定复现；观察任意外角可见向窗口内部延伸的蓝色填充。

## 原因是什么

四个角罩的椭圆内部全部使用边框色填充。角罩确实裁掉了外侧方角，但本应属于窗口内容的四分之一圆也被整块边框色覆盖，因此形成蓝色内凹块。

## 怎么修复的

左侧两个角使用侧栏背景色填充，右侧两个角使用主内容背景色填充；边框色仅用于 1px 椭圆轮廓。透明色仍只覆盖圆角外部区域。

## 验证结果

运行 `.venv/Scripts/python.exe scripts/check_settings.py --capture .tmp/settings-corners.png` 通过。回归断言检查四个角罩的填充色和轮廓色，桌面截图确认四角背景连续且没有向内色块。

## 风险和后续

角罩使用 Tk 的透明色能力，仅面向本项目支持的 Windows 环境。不同 DPI 下仍由 Tk 按窗口逻辑像素绘制，后续若调整圆角半径需同步桌面截图检查。

## 变更历史

- 2026-09-19：修正角罩填充色并增加回归断言。

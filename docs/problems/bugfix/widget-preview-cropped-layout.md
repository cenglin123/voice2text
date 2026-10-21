---
id: bugfix-widget-preview-cropped-layout
type: bugfix
title: 悬浮窗比例预览裁掉操作按钮与状态
status: fixed
severity: low
liveness: active
last_confirmed: 2026-10-22
confirmed_count: 1
tags: [widget, settings, preview]
related_files: [voice2text/widget_render.py, voice2text/widget.py, voice2text/settings_window.py, scripts/check_widget_render.py, scripts/check_settings.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_widget_render.py
  command: python scripts/check_widget_render.py
evidence:
  - type: commit
    ref: "1ea2191 中 settings_window.py 的 _draw_preview 按目标长宽比裁切 _preview_source"
created_at: 2026-10-22
updated_at: 2026-10-22
---

# 悬浮窗比例预览裁掉操作按钮与状态

## 现在的行为

外观预览从当前悬浮窗截图中裁取中间区域；把宽窗调整为正方形时，两侧按钮被裁去，
与实际窗口的紧凑布局不符。预览也只能显示打开设置时的状态。

## 预期的行为

预览根据目标尺寸和选中状态重新绘制完整内容，等比例缩入可用空间。

## 复现方式

宽形悬浮窗打开设置，调整长宽比到 1.0，比较预览与实际方形窗的两侧按钮。

## 原因是什么

窗口呈现与绘制耦合，设置页复用截图而非目标布局。截图裁切无法表达布局重排。

## 怎么修复的

提取纯 Pillow 的 WidgetRenderer，窗口呈现与预览共同调用，预览不创建窗口或更改听写状态。
预览支持待命、聆听和校对，最大比例时整体缩入画布。紧凑布局控制声波条数并缩短准备提示。

## 验证结果

150 种尺寸/状态组合覆盖文字与声波边界、按钮命中区互不重叠、确定性绘制。
设置页检查三状态图像不同、正方形和最宽最大预览尺寸；已目视检查状态总览与设置页截图。

## 风险和后续

预览展示静态帧，不模拟实时音量、动画或桌面背景毛玻璃；几何布局与正式窗口共用。

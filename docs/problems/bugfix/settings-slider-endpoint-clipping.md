---
id: bugfix-settings-slider-endpoint-clipping
type: bugfix
title: 设置页滑块在最小值时左端圆点被裁切
status: fixed
severity: low
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [settings, slider, tkinter, visual]
related_files: [voice2text/settings_window.py, scripts/check_settings.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_settings.py
  command: python scripts/check_settings.py
evidence:
  - type: user_quote
    ref: "这个箭头指向的位置，左侧有一点对滑块的遮挡"
created_at: 2026-09-19
updated_at: 2026-09-19
---

# 设置页滑块在最小值时左端圆点被裁切

## 现在的行为

长宽比等滑块位于最小值时，左端圆点靠近绘图区边界，边缘看起来像被遮挡。

## 预期的行为

滑块在最小值和最大值时，圆点都应完整显示在控件边框以内。

## 复现方式

打开设置页，将长宽比调到 1.00。问题稳定出现在滑块最左端。

## 原因是什么

圆点半径为 9px，轨道内部边距只有 8px，同时 Canvas 还有 1px 高亮边框。最小值时圆点越过有效绘图区，被 Canvas 边界裁切。调整标签列和控件外间距不会改变这个内部坐标。

## 怎么修复的

把滑块轨道的内部边距增加到 11px，确保圆点及边框完整落在 Canvas 内；撤销无效的标签列宽和外间距调整。为圆点添加稳定绘图标签，供回归检查读取实际边界。

## 验证结果

`python scripts/check_settings.py` 验证最小值圆点左边界位于 Canvas 内；`python scripts/check_all.py --quiet` 通过。

## 风险和后续

轨道可用长度缩短 6px，对调节精度无实质影响。仍需用户在实际 DPI 和字体倍率下确认视觉效果。

## 变更历史

- 本文档所在提交：修复滑块端点裁切并增加回归检查。

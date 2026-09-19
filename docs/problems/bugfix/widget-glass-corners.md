---
id: bugfix-widget-glass-corners
type: bugfix
title: 毛玻璃悬浮窗圆角锯齿与角落蓝底
status: fixed
severity: medium
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [widget, blur, layered-window, rounded-corner]
related_files: [voice2text/widget.py, voice2text/layered.py, scripts/check_widget.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_widget.py
  command: python scripts/check_widget.py --capture-dir <temporary-directory>
evidence:
  - type: user_quote
    ref: "悬浮窗的四角还是有些锯齿感，圆角边缘还有蓝色底填充角落"
created_at: 2026-09-19
updated_at: 2026-09-19
---

# 毛玻璃悬浮窗圆角锯齿与角落蓝底

## 现在的行为

旧实现把系统模糊、圆角区域和内容表面放在同一窗口，系统区域的硬裁剪会从逐像素抗锯齿边缘露出，形成锯齿和半透明蓝色角块。

## 预期的行为

圆角外部完全透明，缩放、移动、显隐和不同背景下均只显示平滑轮廓。

## 复现方式

把悬浮窗置于高对比条纹背景上，观察四角和圆弧边缘。

## 原因是什么

Windows 原生模糊区域使用整数像素区域，无法与 UpdateLayeredWindow 的超采样 alpha 边缘共用同一裁剪边界。

## 怎么修复的

使用内缩的独立窗口承载系统模糊，前层继续由超采样 alpha 绘制圆角，并用细边带覆盖模糊层的硬边界。前后两层同步尺寸、位置、层级和显隐。

## 验证结果

脚本覆盖 0.5、1.0、1.5 缩放、拖动、显隐、持续重绘、GDI 资源稳定性和模糊失败回退；真实桌面高对比背景截图未见角落底色泄漏。

## 风险和后续

系统关闭透明效果时自动回退普通深蓝表面，不提供背景模糊。

## 变更历史

- 2026-09-19: 分离模糊承载面与抗锯齿内容面。

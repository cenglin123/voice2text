---
id: bugfix-settings-slider-range
type: bugfix
title: 设置页缩放滑条无法达到配置支持的范围
status: fixed
severity: low
liveness: active
last_confirmed: "2026-09-18"
confirmed_count: 1
tags: [gui, settings]
related_files: [voice2text/settings_window.py, voice2text/config.py]
verification:
  level: manual
evidence:
  - type: conversation_context
    ref: "设置布局优化时，核对 Slider 的固定 0~100 映射与 config.py 的缩放 0.5~1.5 约定，确认范围不一致。"
created_at: 2026-09-18
updated_at: 2026-09-18
---

# 设置页缩放滑条无法达到配置支持的范围

## 复现与原因

原窗口大小滑条拖到最右只能设置 100%，最左则允许 0%；原不透明度滑条也允许 0%。两个控件共用固定的 0~100 映射，未采用配置约定的范围。

## 修复与预期

滑条接受独立上下限，窗口大小限制为 50%~150%，不透明度限制为 30%~100%；鼠标和键盘调整均受边界限制。数值显式显示百分号。

## 验证

本次运行临时 Tk 验证脚本，把两个滑条分别拖到轨道外两端，断言得到 50/150 与 30/100；在临时目录保存配置，确认最大值分别为 1.5 与 1.0。没有写入用户配置。

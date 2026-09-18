---
id: bugfix-widget-drag-position
type: bugfix
title: 悬浮窗拖动时 ULW 旧坐标撤销 Tk 移动
status: fixed
severity: medium
liveness: active
last_confirmed: "2026-09-18"
confirmed_count: 1
tags: [gui, layered, drag]
related_files: [voice2text/widget.py, scripts/check_widget.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_widget.py
  command: python scripts/check_widget.py
evidence:
  - type: conversation_context
    ref: "毛玻璃实际截图中，geometry 请求的新位置被随后 ULW 使用的旧坐标抵消；加入位置断言验证。"
created_at: 2026-09-18
updated_at: 2026-09-18
---

# 悬浮窗拖动时 ULW 旧坐标撤销 Tk 移动

## 复现与原因

先请求 Tk geometry 移动，再立即以 winfo_x/y 的旧坐标调用 UpdateLayeredWindow，窗口回到旧位置。Expose 回调重贴旧帧也可与待处理 geometry 竞争。拖动的独立绘制入口还绕过了整体透明度处理。

## 修复

geometry 后先处理空闲布局任务，再经统一 _sync_surface 呈现；取消不必要的 Expose 重绘，ULW 自己保留表面。

## 验证与边界

运行 `python scripts/check_widget.py`，断言连续两次模拟拖动后坐标增加 (22, 10)、不触发听写，且提交帧的最大 alpha 不超过设置值。事件坐标相对于已移动窗口，第二次事件验证了这一语义。真实桌面测试背景截图确认新位置生效；本次不包含真人热键/麦克风验收。

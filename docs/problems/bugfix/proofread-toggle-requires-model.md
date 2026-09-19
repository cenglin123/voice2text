---
id: bugfix-proofread-toggle-requires-model
type: bugfix
title: 未安装校对模型时禁止开启二次校对
status: fixed
severity: low
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [settings, proofread, model-download]
related_files: [voice2text/settings_window.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_settings.py
  command: dist/build-runtime/python/python.exe -X utf8 scripts/check_settings.py
evidence:
  - type: user_quote
    ref: "如果没有安装校对模型，则尝试开启二次校对时，应该提示需先下载校对模型才能开启二次校对"
created_at: 2026-09-19
updated_at: 2026-09-19
---

## 原因与修复

设置页原先允许直接打开二次校对开关，保存时才把缺少模型的状态静默降级为关闭，用户无法得知原因。
现在设置页初始化时会根据本地 GGUF 是否存在决定开关状态；点击开启且模型缺失时立即恢复关闭并提示先下载。
保存时继续执行模型存在性校验，避免配置文件被其他路径写成不可用状态。

## 验证结果

设置页回归通过，包含控件布局、滑块端点、比例同步与保存；模块编译检查通过。真实缺模型弹窗交互仍需在桌面环境点击确认。

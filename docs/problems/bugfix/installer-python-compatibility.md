---
id: bugfix-installer-python-compatibility
type: bugfix
title: 安装器可能选中不兼容的系统 Python
status: fixed
severity: medium
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [installer, python]
related_files: [install.bat]
verification:
  level: manual
evidence:
  - type: conversation_context
    ref: "发行独立审查：numpy 2.4.6 METADATA Requires-Python >=3.11，而原探测允许3.10"
created_at: 2026-09-19
updated_at: 2026-09-19
---

## 原因与修复

源码安装器原本只探测 Python ≥3.10，未检查64位及 tkinter；这可能选中不支持固定依赖和GUI的解释器。
所有探测统一限定 3.11–3.13、64位及 Tk；备用独立运行时也执行同样检查。
离线分发包直接使用包内运行时，避免受系统 Python 影响。

## 验证与边界

修正后的源码安装器在 Windows 10 + Python 3.13 虚拟机安装完成、全部依赖导入通过。
独立 Python 3.11.9 本地导入和基础模型加载通过。未宣称所有支持版本均经过真机测试。

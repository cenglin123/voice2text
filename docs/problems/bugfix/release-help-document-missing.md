---
id: bugfix-release-help-document-missing
type: bugfix
title: 分发版使用帮助仍尝试打开未打包的 README
status: fixed
severity: low
liveness: active
last_confirmed: "2026-09-21"
confirmed_count: 1
tags: [release, tray, help]
related_files:
  - voice2text/main.py
  - scripts/build_release.py
  - scripts/check_release.py
  - scripts/check_session.py
verification:
  level: automated
  kind: regression-test
  path: scripts/check_release.py
  command: .venv\Scripts\python.exe scripts\check_release.py
evidence:
  - type: error_log
    ref: "FileNotFoundError: [WinError 2] ... voice2text-v0.1.2-windows-x64\\README.md"
created_at: 2026-09-21
updated_at: 2026-09-21
---

# 分发版使用帮助仍尝试打开未打包的 README

## 现在的行为

自包含分发包没有 `README.md`，托盘的“使用帮助”却固定打开该文件，点击后抛出
`FileNotFoundError`。

## 预期的行为

分发版打开包内实际存在的 `安装说明.txt`；源码环境仍可打开 `README.md`。安装说明应提供
项目主页和 GitHub Issues 反馈地址。

## 复现方式

解压 v0.1.2 自包含 ZIP，启动程序后在托盘菜单点击“使用帮助”。旧实现稳定尝试打开分发目录下
不存在的 `README.md`。

## 原因是什么

发行脚本使用白名单复制运行文件，并单独生成 `安装说明.txt`，不会复制仓库根目录的
`README.md`；运行时帮助入口没有按发行布局同步调整。

## 怎么修复的

帮助入口按 `安装说明.txt`、`README.md` 的顺序选择实际存在的文件，并在两者均缺失或系统无法
打开文件时输出可读错误。线上安装包和离线自包含包生成的安装说明都加入固定的项目主页和
Issues 地址。

## 验证结果

`scripts/check_session.py` 验证分发安装说明优先、源码 README 回退；
`scripts/check_release.py` 验证线上与离线 ZIP 均包含带 Issues 地址的安装说明。

## 风险和后续

实际打开动作仍由 Windows 文件关联处理；若用户删除 `.txt` 文件关联，程序会记录系统返回的
错误，但不会影响托盘主进程。

## 变更历史

- 2026-09-21: 修复帮助文档选择并补充发行内容回归。

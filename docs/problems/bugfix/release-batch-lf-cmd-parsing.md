---
id: bugfix-release-batch-lf-cmd-parsing
type: bugfix
title: Linux 构建的分发批处理被 CMD 截断解析
status: fixed
severity: high
liveness: active
last_confirmed: "2026-10-22"
confirmed_count: 1
tags: [release, windows, batch, crlf]
related_files: [scripts/build_release.py, scripts/check_release.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_release.py
  command: .venv/Scripts/python.exe scripts/check_release.py
created_at: 2026-10-22
updated_at: 2026-10-22
evidence:
  - type: user_quote
    ref: "安装时报错：'only'、'UTF8'、'to' 不是内部或外部命令"
  - type: error_log
    ref: "发布包同一 install.bat：LF 在 CMD 出现 codepage/solate/ine_install 截断错误；CRLF 正常进入离线安装分支"
---

# Linux 构建的分发批处理被 CMD 截断解析

## 现在的行为

构建器在所有宿主上将四个 BAT 写为无 BOM、纯 CRLF，再生成源码基线。
发行校验拒绝独立 LF 或裸 CR，源码基线中的 BAT 与交付文件原始字节一致。

## 预期的行为

完整解压分发包后，中文安装与启动入口应正确调用包内脚本，使用自带运行时。

## 复现方式

将 v0.1.5 云端 ZIP 的 install.bat 原样写入隔离临时目录，创建 offline-bundle.txt，
将 PATH 指向空目录，stdin 设为 DEVNULL，再用 cmd.exe /d /c 执行。
出现截断命令与异常退出。仅转换 CRLF 后，正常打印离线验证提示，再因夹具缺少运行时退出。
此最小复现没有执行真实安装或联网。

## 原因是什么

Linux 检出为 LF，构建器直接复制 BAT；Windows cmd.exe 在该脚本的 LF 读取和跳转中
发生截断。原发行校验只验证导入、模型与 GUI，源码比较又归一化换行，漏掉实际安装入口。
安全中心指向 nul 的弹窗与该次错误解析同时发生；无需通过降低系统安全配置处理。

## 怎么修复的

构建阶段显式读取 UTF-8（兼容 BOM）并统一输出无 BOM CRLF，不依赖 Git 或构建宿主。
输出规范化发生在 source-baseline.zip 之前；所有构建类型共用这一过程。
v0.1.5 可用四文件补丁覆盖修复，配置和模型不变；完整修复包版本为 v0.1.6。

## 验证结果

回归覆盖 LF、CRLF、混合换行输入，包内与基线原始字节一致，以及 Windows CMD 安装与
启动调试路径。最终交付包还须实际运行安装入口，验证依赖、基础模型和本地快捷方式。
最终发行与独立复核证据见 docs/plans/completed/batch-release-crlf.md。

## 风险和后续

本修复解决安装/启动脚本解析，不扩展此前高 DPI 真机验收结论。
源码开发入口仍受本地检出换行影响；发行打包不依赖本地检出格式。

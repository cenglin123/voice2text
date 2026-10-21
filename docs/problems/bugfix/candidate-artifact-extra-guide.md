---
id: bugfix-candidate-artifact-extra-guide
type: bugfix
title: 候选包流程额外选择安装说明导致上传检查失败
status: fixed
severity: low
liveness: active
last_confirmed: 2026-10-22
confirmed_count: 1
tags: [release, workflow]
related_files: [.github/workflows/package-windows.yml, scripts/build_release.py]
verification:
  level: automated
  kind: workflow
  path: .github/workflows/package-windows.yml
  command: gh workflow run package-windows.yml --repo cenglin123/voice2text --ref main -f source_tag=v0.1.5 -f baseline_tag=v0.1.4
evidence:
  - type: error_log
    ref: "GitHub Actions 39637543938，upload / Check candidate contents：固定文件列表断言失败"
created_at: 2026-10-22
updated_at: 2026-10-22
---

# 候选包流程额外选择安装说明导致上传检查失败

## 复现与原因

组包脚本除了 ZIP 和 SHA 文件，还会生成独立 `安装说明.txt`。构建 job 选择 `out/*`，
上传 job 只接受 ZIP、SHA 和来源提交记录，因此首轮被固定清单检查拦截，未创建候选发行版。

## 修复

构建 job 显式传递 `out/*.zip`、`out/*.sha256` 和 `out/source.commit`，不放宽上传端清单门禁。
修复提交 `46e9873`；重跑记录为 Actions `39637990103`。

## 验证与边界

工作流 YAML 解析与本地完工检查通过；Actions `39637990103` 的构建与上传两个 job 均成功。
候选产物和 Windows 包内验证结果记入发行计划。
流程只生成隔离草稿，不能替代本机模型加载与 GUI 检查，也不会自动发布。

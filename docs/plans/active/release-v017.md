---
status: in_progress
mode: phased
created_at: 2026-10-22
---

# 打包发布 v0.1.7

用户明确要求打包发布自动更新与输入焦点失败提示。

| 阶段 | 状态 | 验收 |
|---|---|---|
| 源码与发行复核 | completed | 已独立验收功能，版本与指南、默认开关对齐；完工检查 |
| 云端候选构建 | pending | 固定源码标签，复用 v0.1.6 已校验运行时/基础模型；requirements 不变 |
| Windows 候选安装验收 | pending | 下载候选、SHA/CRC、源码与基线、CRLF、实际 CMD 安装、离线模型、设置与通知 |
| 正式发布与文档闭环 | pending | Latest 版本、资产大小/摘要与本地一致；CURRENT/部署记录对齐 |

不带用户 config.json 或可选校对 GGUF；不触发本机现用程序真实自更新。
候选只创建草稿，下载回 Windows 独立目录验收后才转正式版。
包内新增自动更新默认开启；验证其调度时用假的 GitHub 响应，不访问真实更新接口或安装现用目录。

## 复核与证据

- 既有功能由非 fork reviewer `auto_update_review`（gpt-6-luna）独立验收；本轮其复核版本、
  指南、干净默认配置与隔离构建流程无阻塞。安装说明补充焦点失败原因卡的使用说明。
- `python scripts/check_all.py --quiet` 通过；本地用户配置保持排除。

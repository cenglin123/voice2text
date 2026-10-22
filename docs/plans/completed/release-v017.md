---
status: done
mode: phased
created_at: 2026-10-22
---

# 打包发布 v0.1.7

用户明确要求打包发布自动更新与输入焦点失败提示。

| 阶段 | 状态 | 验收 |
|---|---|---|
| 源码与发行复核 | completed | 已独立验收功能，版本与指南、默认开关对齐；完工检查 |
| 云端候选构建 | completed | 固定源码标签，复用 v0.1.6 已校验运行时/基础模型；requirements 不变 |
| Windows 候选安装验收 | completed | 下载候选、SHA/CRC、源码与基线、CRLF、实际 CMD 安装、离线模型、设置与通知 |
| 正式发布与文档闭环 | completed | Latest 版本、资产大小/摘要与本地一致；CURRENT/部署记录对齐 |

不带用户 config.json 或可选校对 GGUF；不触发本机现用程序真实自更新。
候选只创建草稿，下载回 Windows 独立目录验收后才转正式版。
包内新增自动更新默认开启；验证其调度时用假的 GitHub 响应，不访问真实更新接口或安装现用目录。

## 复核与证据

- 既有功能由非 fork reviewer `auto_update_review`（gpt-6-luna）独立验收；本轮其复核版本、
  指南、干净默认配置与隔离构建流程无阻塞。安装说明补充焦点失败原因卡的使用说明。
- `python scripts/check_all.py --quiet` 通过；本地用户配置保持排除。

- Actions `39809851842` 从标签 `v0.1.7` 成功生成隔离草稿，基线为 v0.1.6；正在下载回 Windows 验收。

- 最终 ZIP 471,885,665 字节，SHA-256 为
  `7de5073fb34fa7de4d17333f677bac943a89cd0fd548eccd45bdf0d0401187fe`。
  下载回 Windows 独立目录后，摘要/CRC、源码标签、四 BAT 原始 CRLF/基线、配置隐私范围通过。
- 包内实际中文 CMD 安装完成依赖、ASR/标点模型与本地快捷方式创建，禁用 Python 网络的
  模型加载通过；设置默认自动更新开启/校对关闭，原因卡不激活且 idle保留/loading清除，
  托盘与假 Latest 调度、跨实例24h记账通过。未对现用目录触发真实自动更新。
- 正式 Latest 已发布为 v0.1.7，ZIP 与 SHA256 两资产完整；高 DPI/混合屏真机范围仍按 CURRENT 限制。

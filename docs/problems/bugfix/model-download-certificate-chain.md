---
id: bugfix-model-download-certificate-chain
type: bugfix
title: Python 证书链失败导致模型下载无法完成
status: mitigated
severity: medium
liveness: active
last_confirmed: "2026-09-19"
confirmed_count: 1
tags: [installer, download, tls]
related_files: [scripts/download_models.py, scripts/check_download_models.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_download_models.py
  command: python scripts/check_download_models.py
evidence:
  - type: error_log
    ref: "VM Python 3.13: CERTIFICATE_VERIFY_FAILED unable to get local issuer certificate; 系统 curl 同地址返回成功"
created_at: 2026-09-19
updated_at: 2026-09-19
---

## 原因与修复

虚拟机 urllib 对 GitHub、Hugging Face 下载出现证书链错误；系统 curl 保持验证时可以访问官方地址。
确切证书配置根因未确认。只在 Python 证书验证异常时尝试系统 curl，保留 TLS 校验、超时、
非零退出与最小文件长度检查，成功后才把临时文件改名。其他网络错误继续原有多源回退。

## 验证与边界

模拟证书失败、安全选项、短文件拒绝及普通网络错误不触发 curl 的回归通过。
虚拟机重跑完成全部模型安装，但该次官方请求正常，不能据此宣称实际触发过 curl 回退下载。
ModelScope 的标点备用地址观察到404，官方源可用；基础离线包已携带标点模型，安装不依赖这个地址。

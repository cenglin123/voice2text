---
id: bugfix-debug-audio-cleanup
type: bugfix
title: 调试录音在退出后可能残留于磁盘
status: fixed
severity: high
liveness: active
last_confirmed: "2026-09-22"
confirmed_count: 1
tags: [audio, privacy, cleanup, debug]
related_files: [voice2text/capture.py, voice2text/main.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: conversation_context
    ref: "发行前审计确认 debug_capture.wav 由 stop 写入，但 shutdown 没有删除"
created_at: 2026-09-22
updated_at: 2026-09-22
---

# 调试录音在退出后可能残留于磁盘

## 现在的行为

开启 `debug_dump_wav` 后，停止听写会把麦克风音频写入项目目录的
`debug_capture.wav`；正常退出和下次启动都不会清理。

## 预期的行为

调试录音只在当前运行期间供排查使用，程序退出后不得持久化；异常退出留下的文件应在下次
启动时删除。

## 复现方式

开启调试录音，完成一次听写并退出程序。旧实现中 `debug_capture.wav` 仍然存在。

## 原因是什么

采集模块只有写入逻辑，主程序 `shutdown` 只停止音频流，没有对应的文件生命周期清理。

## 怎么修复的

采集对象初始化时删除上次异常退出的遗留文件；正常关闭时先停止采集，再调用清理方法删除
本次文件。删除失败只记录采集错误，不阻断退出流程。

## 验证结果

`python scripts/check_session.py` 的 75 项测试通过，新增回归覆盖启动清除遗留文件和显式清理
当前调试录音。`python scripts/check_all.py --quiet` 纳入该回归。

## 风险和后续

进程被强制终止时无法执行退出清理，因此依靠下次启动删除遗留文件。

## 变更历史

- 2026-09-22: 增加启动与退出两层调试录音清理。

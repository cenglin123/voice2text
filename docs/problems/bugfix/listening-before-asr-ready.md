---
id: bugfix-listening-before-asr-ready
type: bugfix
title: 识别流尚未就绪时悬浮窗提前显示正在聆听
status: fixed
severity: high
liveness: active
last_confirmed: "2026-09-23"
confirmed_count: 1
tags: [startup, asr, audio-buffer, widget-state]
related_files: [voice2text/asr.py, voice2text/main.py, voice2text/widget.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: .venv/Scripts/python.exe -X utf8 scripts/check_session.py
evidence:
  - type: user_quote
    ref: "模型加载需要一定的时间才能开始工作，用户如果以为可以用而直接说话，开头的几句话会丢失"
created_at: 2026-09-23
updated_at: 2026-09-23
---

# 识别流尚未就绪时悬浮窗提前显示正在聆听

## 现在的行为

开始会话后，应用创建并启动识别线程，但没有等待该线程完成识别流创建便继续进入活动态。
界面可能先显示“正在聆听”，而识别线程仍在完成首次初始化。

## 预期的行为

准备阶段明确显示“准备中，请稍候”。麦克风音频从会话启动起进入队列；只有识别流确认创建成功后，
应用才进入活动态、播放开始提示音并显示“正在聆听”。

## 复现方式

在首次识别流创建较慢的环境中启动一次听写，并观察悬浮窗状态和开始提示音早于识别线程就绪。
具体初始化耗时受机器和模型运行时影响。

## 原因是什么

`ASRSessionWorker.start()` 只表示线程已调度，不表示 `recognizer.create_stream()` 已完成。原启动流程
将前者当成就绪信号，缺少工作线程到会话控制器的显式握手。

## 怎么修复的

识别 worker 增加一次性就绪事件，在识别流创建成功后置位；创建失败也会唤醒等待方并携带错误。
会话先启动麦克风，让准备阶段音频缓存在队列中，再启动 worker 并等待就绪。就绪后才设置 active、
播放提示音并切换为聆听状态；失败或 8 秒超时则停止采集、递增会话代数以拦截迟到回调，并
保持未活动状态。

## 验证结果

`scripts/check_session.py` 通过 79 项测试，覆盖识别流创建前不可就绪、创建失败、应用级调用顺序
以及未就绪时不进入 active。悬浮窗专项检查通过。真实首次初始化耗时仍需用户设备验证。

## 风险和后续

识别模型构造仍在麦克风启动之前完成；正常路径由启动预加载处理。此次修复覆盖识别流创建和
worker 调度窗口，并确保这段准备时间内已经采集的音频不会因消费者尚未就绪而丢失。

## 变更历史

- 2026-09-23: 增加识别流就绪握手与准备态语义。

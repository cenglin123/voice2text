---
id: bugfix-selected-microphone-defaulted-to-silent-device
type: bugfix
title: 录音使用系统静音默认设备而非真实麦克风
status: fixed
severity: high
liveness: active
last_confirmed: 2026-09-23
confirmed_count: 1
tags: [audio, microphone, sounddevice, VAC, settings]
related_files: [voice2text/capture.py, voice2text/config.py, voice2text/main.py, voice2text/settings_window.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: user_quote
    ref: "识别出的语音变成 Trial；其它语音识别也出现相同结果，更换外置麦克风后恢复正常"
  - type: conversation_context
    ref: "外部设备排查显示 PortAudio 默认输入为近静音虚拟声卡，真实阵列麦克风有正常电平"
created_at: 2026-09-23
updated_at: 2026-09-23
---

# 录音使用系统静音默认设备而非真实麦克风

## 现在的行为

应用始终隐式使用 PortAudio 默认输入。安装虚拟声卡或回环设备后，系统默认项可能指向近静音
端点，导致语音识别收到静音并输出错误文本。

## 预期的行为

用户可以在设置页明确选择实际麦克风。设备拔除或选择失效时，应用应指出设备不可用，不得
静默切换回另一个未知的默认设备。

## 复现方式

将 Windows/PortAudio 默认录音设备设为近静音虚拟端点，再使用 voice2text 听写。选择实际麦克风
后重试；切换设备后索引变化时仍应使用对应设备。

## 原因是什么

不同引擎都输出同一无关词，且切换到有正常输入电平的外置麦克风后恢复，指向录音设备路由问题，
而非单独某个识别模型。应用此前没有设备选择配置。

## 怎么修复的

设置页列出 PortAudio 输入设备，使用设备名称与 host API 组成稳定选择器保存；每次打开采集流时
重新解析当前索引，以适应热插拔。若选择器失效或匹配歧义，明确停止本次听写并提示重新选择。
保持空选择时仍使用系统默认输入。应用不会自动修改 Windows 全局默认设备。

## 验证结果

`python scripts/check_session.py` 覆盖不同 host API 下的同名设备、准确解析、失效选择器与歧义拒绝；
82 项回归通过。当前设备上的真实麦克风电平与用户界面选择仍需手工确认。

## 风险和后续

应用选择只影响 voice2text。微信等其它应用仍使用 Windows 系统默认录音设备；需要修复它们的输入时，
应在 Windows 声音设置中选择实际麦克风。

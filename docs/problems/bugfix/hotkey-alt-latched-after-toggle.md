---
id: bugfix-hotkey-alt-latched-after-toggle
type: bugfix
title: Alt+V 多次切换后 Alt 修饰键可能残留按下状态
status: mitigated
severity: high
liveness: active
last_confirmed: 2026-09-21
confirmed_count: 3
tags: [热键, Alt, keyboard, suppress, 输入]
related_files: [voice2text/hotkey.py, voice2text/main.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: user_quote
    ref: "快捷键 ALT + V 使用中，开关几次以后，有时候会造成 ALT 被系统视为长按状态"
  - type: conversation_context
    ref: "HotkeyListener 仅清除切换 Event；suppress=True 的热键没有针对残留系统修饰键状态的补救"
  - type: user_quote
    ref: "识别没有问题了，但是快捷键的反应有点慢"
created_at: 2026-09-20
updated_at: 2026-09-21
---

# Alt+V 多次切换后 Alt 修饰键可能残留按下状态

## 现在的行为

使用 Alt+V 多次开始和停止听写后，Windows 偶尔仍把 Alt 视为按下。后续按键可能触发
应用菜单或被当作 Alt 组合键。残留问题缓解后，真机反馈快捷键状态切换仍有可感知延迟。

## 预期的行为

热键完成后，系统不得残留 Alt 按下状态；同时 Alt+V 的 `V` 必须继续被全局热键吞掉，避免
进入输入法或目标应用。

## 复现方式

在任意可编辑应用中连续以 Alt+V 开始、停止多次，观察后续普通按键是否出现 Alt 菜单行为。
该问题为偶发状态残留，自动测试以模拟 Windows 仍报告 Alt 按下的分支覆盖。

## 原因是什么

`keyboard.add_hotkey(..., suppress=True)` 负责抑制组合键透传。原实现收到回调后只清除内部
切换 Event，没有在操作系统仍报告 Alt 按下时补充 key-up，因此无法修复低级钩子偶发遗漏的
修饰键释放。热键回调只设置 Event，Tk 主线程原来每 150ms 轮询一次，因此组合键释放后还会
额外等待 0–150ms 才进入开始或停止流程。
低级热键监听已经把主键保持在 armed 状态到 key-up，但输入活动守卫仍按“当前修饰键是否按下”
判断重复的 V；先松 Alt 后 Windows 产生 V repeat 时，会被误判为手动编辑并中断会话。

## 怎么修复的

处理热键切换 Event 时检查左、右 Alt 的系统按下状态。只有仍按下时，才向对应虚拟键发送
key-up；正常物理释放后不发送任何事件。清理发生在主线程轮询阶段，通常已晚于用户实际松键，
并保留原有 `suppress=True` 行为。
主线程轮询周期从 150ms 调整为 30ms，最坏调度等待缩短 80%；诊断模式记录
`hotkey_dispatch.latency_ms`，用于区分热键调度和后续识别/校对耗时。
输入活动守卫同步记录已成立组合键的主键，直到该主键 key-up；期间的自动重复即使发生在 Alt
释放之后也仍属于停止热键，真正松开后再次单独按 V 才按手动编辑处理。

## 验证结果

`python scripts/check_session.py` 通过 74 项测试，覆盖左 Alt 残留时发送一次 key-up、正常
释放时不注入事件、热键调度延迟计算、先松 Alt 后的 V repeat，以及不超过 30ms 的轮询上限。真实键盘钩子行为受输入法、
键盘驱动和 Windows 版本影响，仍需在用户的常用应用中连续切换验收。

## 风险和后续

在用户罕见地持续按住 Alt 超过主线程轮询周期时，本修复会提前清除其系统 Alt 状态；对完成的
Alt+V 热键是期望行为。若仍有残留，应采集运行输出并补充键盘扫描码级诊断。

## 变更历史

- 待提交：为残留 Alt 状态增加主线程 key-up 兜底和回归测试。
- 待提交：将热键轮询周期降至 30ms，并增加调度延迟诊断。
- 2026-09-22: 活动守卫沿用 armed 主键状态，避免热键自动重复被误判为手动编辑。

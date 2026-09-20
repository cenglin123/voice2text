---
id: bugfix-weixin-volatile-input-and-punctuation-gate
type: bugfix
title: 微信富文本输入框会话中断与锁句标点误覆盖
status: mitigated
severity: high
liveness: active
last_confirmed: 2026-09-20
confirmed_count: 1
tags: [微信, Weixin, UIA, RuntimeId, 标点, 上屏]
related_files: [voice2text/target.py, voice2text/asr.py, voice2text/main.py, scripts/check_session.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
evidence:
  - type: user_quote
    ref: "有时候能识别 weixin 有时候识别不到；添加标点时会把文字变成‘。禾日当午，，地禾下土…’"
  - type: conversation_context
    ref: "目标锁定对普通 UIA 控件持续比较 RuntimeId；微信 Chrome WebView 的动态节点与 ChatGPT 桌面端同类"
created_at: 2026-09-20
updated_at: 2026-09-20
---

# 微信富文本输入框会话中断与锁句标点误覆盖

## 现在的行为

微信对话框中的听写有时无法开始，或已开始后在流式上屏期间中断。停顿锁句时，用户还
观察到原文中的汉字被删改，并出现不对应的标点。

## 预期的行为

开始时必须确认微信光标位于可编辑输入框；会话期间同一原生输入焦点应持续可用。标点层
只能在最终 ASR 原文已安全同步到该输入框后运行，且绝不改写原文字符。

## 复现方式

在微信对话输入框按快捷键听写，经过一次停顿触发锁句。动态 WebView UIA 节点重建时，
旧实现可能把同一输入框误判为不同控件。若最终原文同步失败，旧实现仍继续调用锁句标点。

## 原因是什么

已确认：目标锁定将微信按普通 UIA 控件处理并持续比较 RuntimeId；微信的
`Chrome_WidgetWin_1` 富文本输入区会在更新期间重建 UIA 节点，RuntimeId 不稳定。

已确认：锁句流程未将“最终 ASR 原文写入成功”作为标点和提交的前置条件。上屏状态无法
确认时继续使用标点版本，会在错误的屏幕基线执行尾部替换。用户示例中的模型改写本身已被
字符一致性投影拒绝；本次进一步阻断其在原文未同步时抵达输入层的路径。

## 怎么修复的

1. 将 `weixin` 的 `Chrome_WidgetWin_1` 纳入动态 UIA 目标：开始时仍要求 UIA 可编辑验证，
   验证后仅锁定稳定的原生窗口和焦点 HWND；用户主动切换仍由输入活动守卫和原生焦点检查
   立即停止上屏。
2. 让部分上屏回调显式返回写入结果。最终锁句原文返回失败时，ASR 工作线程不调用标点和
   提交回调；锁句回调也只在标点文本成功写入后才提交记账。
3. 加入微信目标身份、原文同步失败不触发标点、以及用户提供的汉字改写样本回归测试。

## 验证结果

`python scripts/check_session.py` 通过 40 项测试，其中包含微信动态 UIA 模拟和标点事务
门禁。尚未在真实微信客户端完成本轮手工冒烟，发行前应在微信输入框完成一次开始、停顿锁句、
停止和校对的端到端验证。

## 风险和后续

- 微信客户端若改变顶层窗口类名，仍会在开始时安全拒绝，不会向未验证控件盲写。
- 最终 ASR 解码自身可能修正流式 partial 的文字；这属于识别结果变化，不是标点层改写，
  后续可通过真实样本评估是否需要调整 endpoint 策略。

## 变更历史

- 待提交：增加微信动态 UIA 身份和锁句原文同步门禁。

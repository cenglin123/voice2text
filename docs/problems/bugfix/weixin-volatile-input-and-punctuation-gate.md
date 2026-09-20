---
id: bugfix-weixin-volatile-input-and-punctuation-gate
type: bugfix
title: 微信富文本输入框会话中断与锁句标点误覆盖
status: investigating
severity: high
liveness: active
last_confirmed: 2026-09-20
confirmed_count: 5
tags: [微信, Weixin, UIA, RuntimeId, 标点, 上屏]
related_files: [voice2text/target.py, voice2text/asr.py, voice2text/input.py, voice2text/keysender.py, voice2text/main.py, scripts/check_session.py]
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
  - type: user_quote
    ref: "真机 v0.1.1 仍输出‘？禾日当午，，滴禾下土，，知盘中餐，，粒皆辛苦。’，日志 punctuation_restore=applied"
  - type: user_quote
    ref: "仓库当前源码真机仍输出‘。禾日当午。。滴禾下土。。知盘中餐？？粒皆辛苦。’"
  - type: user_quote
    ref: "无损光标插入版真机仍输出‘锄禾日当午。。滴禾下土。。知盘中餐？？利决心。’"
  - type: user_quote
    ref: "句末追加版真机输出‘锄禾日当午汗滴禾下土谁知盘中餐？？粒皆辛苦。’"
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

根因尚未确认。此前关于富文本吞字、组合区覆盖、跨线程焦点和 HWND 重建的说法均为假设，
没有真实事件或句柄快照支持，不能当作已确认事实。多轮模拟回归通过后，用户真机仍复现。
外部同类项目的实现指出部分 Electron/Chromium 编辑器会丢弃持续时间为零的 Unicode 按键，
而本项目此前的慢速路径虽然按字符分批，却仍在同一次 `SendInput` 中发送按下和抬起。这个差异
与现象吻合，但必须经真机验证后才能确认为根因。新增显式启用的阶段文本与焦点诊断，并使用
固定文本探针隔离模型和输入链路。

## 怎么修复的

1. 将 `weixin` 的 `Chrome_WidgetWin_1` 纳入动态 UIA 目标：开始时仍要求 UIA 可编辑验证，
   验证后仅锁定稳定的原生窗口和焦点 HWND；用户主动切换仍由输入活动守卫和原生焦点检查
   立即停止上屏。
2. 让部分上屏回调显式返回写入结果。最终锁句原文返回失败时，ASR 工作线程不调用标点和
   提交回调；锁句回调也只在标点文本成功写入后才提交记账。
3. 加入微信目标身份、原文同步失败不触发标点、以及用户提供的汉字改写样本回归测试。
4. endpoint 锁句只接受在最后一个已显示 partial 后追加的最终文本；若最终解码删除或替换
   已显示字符，则使用屏幕 partial 作为标点输入和提交基线。
5. 句首标点或同一字符边界出现多个新增标点时，将整个标点结果判为不安全并保留原文。
6. 停顿标点改为从句末向前移动光标并只插入标点，再把光标恢复到句末；整个事务不发送退格，
   也不重打任何已上屏汉字。二次校对若只是新增标点，同样走这条无损路径。
7. 微信启用端点缓冲模式：partial 只更新内存，不触碰编辑框；每次停顿后将完整、已加标点的
   句子按单字符慢速顺序写入一次。停止后的二次校对若需要修改已有内容则保留原文并报告未应用。
   其他已验证编辑器仍保留逐字实时刷新和句中标点。
8. 慢速路径把每个 UTF-16 码元的按下与抬起拆成两次系统调用，默认保持按下 10ms，并在码元间
   等待 20ms；这轮调整来自公开项目的已验证兼容策略，当前仍标记为待真机确认。

## 验证结果

`python scripts/check_session.py` 通过 54 项测试，其中包含微信动态 UIA、锁句最终文本丢字、
句首/重复标点，以及微信端点缓冲模式在 partial 阶段零写入、endpoint 仅一次慢速整句写入、
校对阶段零覆盖；新增检查确认慢速路径的按下和抬起分离。尚未在真实微信客户端完成本轮
真实按键时长方案的手工冒烟。

## 风险和后续

- 微信客户端若改变顶层窗口类名，仍会在开始时安全拒绝，不会向未验证控件盲写。
- 锁句不再采用最终 ASR 对已显示字符的修正，安全性优先于 endpoint 最终假设的少量精度收益。

## 变更历史

- 待提交：增加微信动态 UIA 身份和锁句原文同步门禁。
- 待提交：以最后显示 partial 为不可回退基线，并拒绝句首或重复新增标点。
- 待提交：纯标点变化改为只插入标点的无损光标事务。
- 待提交：微信禁用回溯式编辑，仅追加句末符号并拒绝校对覆盖。
- 待提交：微信改为 partial 内存缓冲、endpoint 慢速整句写入。
- 待提交：慢速 Unicode 注入增加真实按键保持时间和字符间隔。

---
id: bugfix-weixin-volatile-input-and-punctuation-gate
type: bugfix
title: 微信富文本输入框会话中断与锁句标点误覆盖
status: investigating
severity: high
liveness: active
last_confirmed: 2026-09-23
confirmed_count: 9
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
  - type: error_log
    ref: "诊断显示 punctuation/projected/injection 文本均正确，但微信屏幕仍出现重复标点和丢字"
  - type: error_log
    ref: "受保护粘贴已上屏，但恢复阶段报‘尚未调用 CoInitialize’，且端点缓冲使文字停止后才显示"
  - type: error_log
    ref: "实时上屏已正确，但每次原剪贴板恢复都报告 CLIPBRD_E_CANT_CLOSE"
created_at: 2026-09-20
updated_at: 2026-09-23
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

显式诊断已确认 ASR endpoint、标点模型、字符投影和注入层收到的整句文本完全正确；相同会话
在微信 `Qt51514QWindowIcon` 输入框屏幕上仍出现重复标点与丢字。因此故障位于微信接收
`VK_PACKET` 的外部输入边界，不在识别或标点恢复。增加真实按键保持时间后仍复现，说明继续
调整 Unicode 事件节奏不能解决这个 Qt 输入框兼容问题。

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
9. 微信端点整句不再走 `VK_PACKET`，改用受保护剪贴板事务粘贴。临时文本声明禁止进入剪贴板
   历史和云同步；粘贴完成后仅当剪贴板序号仍属于本事务时恢复原始 IDataObject，避免覆盖用户
   同时复制的新内容。
10. 工作线程改用配对的 `OleInitialize/OleUninitialize`，满足 OLE 剪贴板调用要求；原内容恢复
    失败只输出诊断，不再把已经完成的粘贴误判为上屏失败。取消微信端点缓冲，partial 变化尾部
    和停顿标点实时通过受保护粘贴更新。
11. 恢复仍存活的原 IDataObject 时只调用 `OleSetClipboard`；不再用 `OleFlushClipboard` 强制
    立即物化全部格式，避免真机持续触发 `CLIPBRD_E_CANT_CLOSE`。
12. UIA 基类统一通过 `GetPattern(PatternId.ValuePattern)` 查询 ValuePattern；微信与 ChatGPT
    可能将焦点控件报告为 WindowControl/CustomControl，因此按进程名使用原生焦点锁定，避免
    把 UIA 控件类型误当作可编辑性的可靠依据。仍要求 UIA 能返回焦点控件；未知应用继续严格验证。
13. 目标捕获把业务校验异常原样报告，意外 UIA 异常则附带底层原因，避免故障被统一吞成无细节提示。

## 验证结果

`python scripts/check_session.py` 通过 82 项测试，其中包含微信 WindowControl UIA、锁句最终文本丢字、
句首/重复标点、partial 实时受保护粘贴、停顿标点插入和校对阶段零覆盖；另检查隐私格式、原始
IDataObject 恢复以及恢复异常不影响已完成上屏。尚未在真实微信客户端完成本轮 OLE 修复后的
手工冒烟。

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
- 待提交：微信 Qt 输入框改用受保护剪贴板事务。
- 待提交：修复 OLE 初始化并恢复微信 partial 实时上屏。
- 待提交：恢复原 IDataObject 时移除不必要的强制物化。
- 2026-09-23: 兼容微信/ChatGPT WebView 的 WindowControl 与 ValuePattern 基类查询，并保留 UIA 失败原因。

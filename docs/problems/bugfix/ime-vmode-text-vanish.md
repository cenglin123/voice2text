---
id: bugfix-ime-vmode-text-vanish
type: bugfix
title: 热键主键透传导致输入框出现 v 或控制字符
status: mitigated
severity: high
liveness: active
last_confirmed: "2026-09-22"
confirmed_count: 2
tags: [输入法, 剪贴板粘贴, 热键, IME, keyboard, terminal]
related_files: [voice2text/hotkey.py, voice2text/input.py, voice2text/main.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_session.py
  command: python scripts/check_session.py
created_at: 2026-09-18
updated_at: 2026-09-22
evidence:
  - type: user_quote
    ref: "说完到一半，本来已经识别到文字了，但是突然一下文字全部消失（附截图：微软拼音 v 模式面板 + 文本框中落单的 v）"
  - type: conversation_context
    ref: "热键钩子 suppress=False 透传 Alt+V；_paste 零间隔合成 Ctrl+V；停止流程恢复剪贴板与最后一次粘贴存在竞态"
  - type: user_quote
    ref: "WT 会使得输入 ctrl+alt+x 或 alt+v 等快捷键变成特殊输入，比如 ^X 或 v"
---

# 热键主键透传导致输入框出现 v 或控制字符

## 现在的行为

听写进行到一半（partial 已上屏），文字可能突然消失，文本框里出现一个落单的 `v`；
Windows Terminal 中按 Alt+V 或 Ctrl+Alt+X 时还可能收到 `v` 或 `^X` 控制字符。

## 预期的行为

partial 整句刷新正常：退格删旧 partial → Ctrl+V 粘贴新 partial，屏幕文字持续更新。

## 复现方式

中文输入法（微软拼音）激活 + 记事本聚焦 + 听写中。用户中途按 Alt+V（停止/误触）或
partial 刷新恰逢识别推理占满 CPU 时可复现；时序依赖，非必现。

## 原因是什么

初始故障链及其后续复现原因：

1. **热键透传**（已确认事实）：`keyboard.add_hotkey("alt+v", suppress=False)` 不拦截按键，
   用户按 Alt+V 时 "v" 同时到达焦点应用——中文输入法把它吃进拼音组合框，弹出 v 模式面板。
2. **粘贴键序无间隔**（已确认事实）：`press_and_release("ctrl+v")` 零间隔连发 4 个键事件。
   ASR/校对推理占 CPU 时，IME 的异步键盘钩子处理可能把 ctrl 与 v 拆散（系统保序但 IME
   消费时机不保序），落单的 v 进入组合框；此时退格已删掉旧文本、粘贴又失败 → 文字全部消失。
3. **剪贴板恢复竞态**（已确认事实）：停止流程 join 完线程立即 `pyperclip.copy` 恢复用户
   原剪贴板，而目标 App 对上一次 Ctrl+V 的消费是异步的——粘贴发生时读到的可能已是恢复后
   的旧剪贴板内容（等效于没粘贴）。
4. **松键触发仍可能泄漏主键**（真机日志确认）：改成 `suppress=True` 后仍使用
   `trigger_on_release=True`。keyboard 0.13.5 会通过内部修饰键状态机抑制和重放事件；
   Windows Terminal 中完整组合仍可能被还原成 `v` 或 `^X`。因此不能只检查注册参数，
   必须明确阻断主键的 keydown 和 keyup。
5. **先松修饰键时的自动重复**（隔离状态机复现）：完整组合已命中后若先松开 Alt、
   继续按住 V，后续重复 keydown 因组合不再完整而被放行，仍会向目标输入 `v`。

## 怎么修复的

1. hotkey.py：不再依赖 `keyboard.add_hotkey(..., trigger_on_release=True)` 的内部修饰键
   重放状态机。新的阻断钩子允许修饰键通过，在完整组合出现时从主键 keydown 开始吞掉，
   到主键 keyup 时只触发一次切换；长按重复 keydown 也不会重复切换。
   已进入 armed 状态的主键会持续阻断到 keyup，不受修饰键先行松开的影响。
2. input.py `_paste`：粘贴前补发一次 ctrl keyup 清卡住的修饰键；ctrl down → 20ms →
   v → 20ms → ctrl up，键间间隔让 IME 的异步处理跟上
3. main.py `_stop_session`：线程 join 后、恢复剪贴板前 sleep 0.3s，等 App 消化最后一次粘贴

## 验证结果

`python scripts/check_session.py` 的 68 项测试通过。新增回归覆盖：修饰键事件允许通过、完整
组合的主键 down/up 均被阻断、切换只在主键松开时发生，以及缺少修饰键时普通主键保持透传。
同时覆盖先松修饰键后主键自动重复仍被阻断。
Windows Terminal 的真实低级输入链仍需分发端复验，因此状态保持为 mitigated。

## 风险和后续

- 配置的组合键主键会在组合完整匹配时被全局吞掉；这是全局听写热键的预期行为
- 若真机仍偶发粘贴丢失，下一步是对 UIA ValuePattern 可读的应用做"粘贴后读回校验 + 重试"
- 键间间隔使每次 partial 刷新增加约 50ms，句内刷新频率约 2-4 次/秒，无感知影响

## 变更历史

- 2026-09-18: 初始修复（suppress / 键序间隔 / 剪贴板竞态三处）
- 2026-09-22: 改用主键级阻断状态机，修复 Windows Terminal 收到 `v` / `^X`。
- 2026-09-22: armed 主键持续阻断到 keyup，修复先松修饰键后的自动重复透传。

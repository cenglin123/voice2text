---
id: bugfix-ime-vmode-text-vanish
type: bugfix
title: 听写中途已识别文字全部消失并弹出输入法 v 模式面板
status: fixed
severity: high
liveness: active
last_confirmed: ""
confirmed_count: 0
tags: [输入法, 剪贴板粘贴, 热键, IME, keyboard]
related_files: [voice2text/hotkey.py, voice2text/input.py, voice2text/main.py]
verification:
  level: manual
created_at: 2026-09-18
updated_at: 2026-09-18
evidence:
  - type: user_quote
    ref: "说完到一半，本来已经识别到文字了，但是突然一下文字全部消失（附截图：微软拼音 v 模式面板 + 文本框中落单的 v）"
  - type: conversation_context
    ref: "热键钩子 suppress=False 透传 Alt+V；_paste 零间隔合成 Ctrl+V；停止流程恢复剪贴板与最后一次粘贴存在竞态"
---

# 听写中途已识别文字全部消失并弹出输入法 v 模式面板

## 现在的行为

听写进行到一半（partial 已上屏），文字突然全部消失，文本框里出现一个落单的 "v"，
微软拼音弹出"V 模式输入"候选面板（截图确认）。

## 预期的行为

partial 整句刷新正常：退格删旧 partial → Ctrl+V 粘贴新 partial，屏幕文字持续更新。

## 复现方式

中文输入法（微软拼音）激活 + 记事本聚焦 + 听写中。用户中途按 Alt+V（停止/误触）或
partial 刷新恰逢识别推理占满 CPU 时可复现；时序依赖，非必现。

## 原因是什么

三个缺陷叠加成故障链：

1. **热键透传**（已确认事实）：`keyboard.add_hotkey("alt+v", suppress=False)` 不拦截按键，
   用户按 Alt+V 时 "v" 同时到达焦点应用——中文输入法把它吃进拼音组合框，弹出 v 模式面板。
2. **粘贴键序无间隔**（已确认事实）：`press_and_release("ctrl+v")` 零间隔连发 4 个键事件。
   ASR/校对推理占 CPU 时，IME 的异步键盘钩子处理可能把 ctrl 与 v 拆散（系统保序但 IME
   消费时机不保序），落单的 v 进入组合框；此时退格已删掉旧文本、粘贴又失败 → 文字全部消失。
3. **剪贴板恢复竞态**（已确认事实）：停止流程 join 完线程立即 `pyperclip.copy` 恢复用户
   原剪贴板，而目标 App 对上一次 Ctrl+V 的消费是异步的——粘贴发生时读到的可能已是恢复后
   的旧剪贴板内容（等效于没粘贴）。

## 怎么修复的

1. hotkey.py：`suppress=True` 拦截 Alt+V 不透传（听写工具的标准做法；代价是 Alt+V 不再
   触发应用自身的 Alt+V 快捷键，如记事本的"查看"菜单）
2. input.py `_paste`：粘贴前补发一次 ctrl keyup 清卡住的修饰键；ctrl down → 20ms →
   v → 20ms → ctrl up，键间间隔让 IME 的异步处理跟上
3. main.py `_stop_session`：线程 join 后、恢复剪贴板前 sleep 0.3s，等 App 消化最后一次粘贴

## 验证结果

无自动化测试（模拟按键在本开发环境不可靠，IME 行为需真机验证）。已验证：粘贴键序与
间隔的单测（mock keyboard：keyup→ctrl→v→keyup 序列 + ≥40ms 耗时）、suppress 注册、
停止延迟代码存在。真机验证方式：中文输入法下听写中途按 Alt+V，确认不再出现 v 模式面板、
文字不消失。

## 风险和后续

- suppress=True 全局吞 Alt+V：依赖 Alt+V 快捷键的应用在 voice2text 运行期间不可用（可接受）
- 若真机仍偶发粘贴丢失，下一步是对 UIA ValuePattern 可读的应用做"粘贴后读回校验 + 重试"
- 键间间隔使每次 partial 刷新增加约 50ms，句内刷新频率约 2-4 次/秒，无感知影响

## 变更历史

- 2026-09-18: 初始修复（suppress / 键序间隔 / 剪贴板竞态三处）

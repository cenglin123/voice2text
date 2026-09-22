---
id: bugfix-terminal-tui-input
type: bugfix
title: Windows Terminal / OpenCode TUI 听写已启动但没有文字
status: mitigated
severity: high
liveness: active
last_confirmed: "2026-09-22"
confirmed_count: 5
tags: [terminal, tui, opencode, uia, sendinput, clipboard, uipi, elevation]
related_files: [voice2text/target.py, voice2text/input.py, voice2text/clipboard_tx.py, scripts/check_session.py, scripts/check_elevation_guard.py]
verification:
  level: automated
  kind: regression-test
  path: scripts/check_elevation_guard.py
  command: python scripts/check_elevation_guard.py
evidence:
  - type: user_quote
    ref: "悬浮窗变红，但 TUI 不出现文字"
  - type: error_log
    ref: "windowsterminal 的 partial_write 连续记录 ok 且耗时约 0.1ms，但终端没有显示文字"
  - type: error_log
    ref: "改用受保护 Ctrl+V 后 partial_write 中位数约 170ms 且全部记录 ok，但终端仍没有文字；Alt+V 首次捕获报告无法验证目标输入控件"
  - type: error_log
    ref: "真机探针：pythonw(本软件)=非提权、用户 WT=提权；同机 WT 1.24 defaults 绑定 ctrl+shift+v→paste，绑定不是原因"
created_at: 2026-09-19
updated_at: 2026-09-22
---

# Windows Terminal / OpenCode TUI 听写已启动但没有文字

## 现在的行为

热键和识别会话已经启动，悬浮窗进入红色聆听状态，但 Windows Terminal 输入区没有文字。运行日志中的目标恢复、识别、标点和 `partial_write` 均显示成功。修复后，管理员终端场景会在开始听写时直接报"目标窗口以管理员权限运行……"并拒绝开始，不再静默丢字。

## 预期的行为

终端 TUI 与普通编辑框一样接收离线识别结果；无法注入时明确告知用户原因与出路。

## 复现方式

聚焦 OpenCode TUI 或管理员终端的输入区，按快捷键开始听写并说话。

## 原因是什么

这个问题分为四层，按发现顺序：

1. 终端是自绘界面，通常不暴露稳定的 UIA Edit/ValuePattern；TUI 重绘还可能更换 UIA RuntimeId。普通文本框的可编辑检测会在首批注入前拒绝终端。
2. 目标身份修复后，Windows Terminal 可以开始听写，但不会消费 `VK_PACKET` Unicode 注入。`SendInput` 返回成功只代表事件已提交到系统输入队列，不能证明目标应用已接收文字。因此日志会出现 `partial_write [ok]`，界面却没有文本。
3. 首次剪贴板修复只按进程切换传输方式，却仍发送 Ctrl+V。用户真机日志显示该路径耗时已经符合剪贴板事务特征，但 Windows Terminal 仍没有文字；同时，部分启动状态下顶层宿主窗口类未命中终端类白名单，导致 Alt+V 已触发却在捕获阶段被普通 UIA 校验拒绝。
4. **根因（2026-09-22 真机实锤）：提权失配 + UIPI**。本机开启 `FilterAdministratorToken`（内置 Administrator 也默认普通权限令牌），本软件 pythonw 非提权，而用户的 Windows Terminal 是提权实例；非提权进程向提权窗口 SendInput 的按键被系统静默丢弃，OpenClipboard 不受 UIPI 限制照样成功，于是识别、剪贴板、注入全部"成功"，终端一个字不出现。此前所有"发送 ok 但无文字"的真机日志都发生在提权终端上。同理，"右键在终端中打开"若由提权的父进程派生也会继承提权令牌。

## 怎么修复的

- 对已知 Windows 终端窗口类使用稳定的原生窗口、进程、线程和焦点句柄身份；不保存随 TUI 重绘变化的 UIA RuntimeId。普通应用仍要求可写 UIA 控件，避免扩大盲写范围。
- Windows Terminal 的文字传输改用受保护剪贴板粘贴：临时内容不进入 Win+V 和云剪贴板历史，粘贴后恢复用户原剪贴板。终端改发专用的 Ctrl+Shift+V 粘贴组合键；微信等普通 GUI 输入框继续使用 Ctrl+V。
- 终端识别同时增加 `windowsterminal` 进程名兜底，不再只依赖可能随系统版本、启动方式和窗口状态变化的 XAML 宿主窗口类。
- 捕获阶段新增提权失配检测（`target.self_elevated` / `target.process_elevated`）：自己非提权而目标明确提权，或查询被系统以 `ACCESS_DENIED` 拒绝时，拒绝开始听写并提示"以管理员身份重新启动本软件，或改用非管理员窗口"；进程退出、无效句柄等其他查询失败按未知放行，避免误拦普通窗口。

## 验证结果

- 自动回归：`scripts/check_elevation_guard.py` 9 项全过（提权组合矩阵、令牌与进程句柄所有权、拒绝访问与其他查询失败的区分）；仓库 `check_session.py` 68 项全过，证明既有终端目标测试不受影响。
- 真机探针：本机 pythonw=非提权、用户 WT(管理员)=提权、新开 WT=非提权，判定与预期一致；WT 1.24 `defaults.json` 确认 `ctrl+shift+v`→paste 默认绑定存在，排除绑定假设。
- Windows Terminal 的实际语音输入仍需用户做最终体验验收：管理员终端应出现明确的拒绝提示；非提权终端应正常上屏。

## 风险和后续

- 非提权终端的真实听写尚未复验（排查期间机器锁屏无法抢前台）。若非提权 WT 仍无文字，下一杠杆是把组合键换成 `shift+insert`（WT 1.24 默认第二粘贴绑定，绕开 Ctrl+Shift 输入语言切换 chord 与 IME 干扰面）。
- 受保护粘贴比单次 `VK_PACKET` 注入慢，但通常仍低于当前约 250ms 的识别更新周期。若用户自行取消 Windows Terminal 的 Ctrl+Shift+V 粘贴绑定，这一路径将无法工作。
- 实测：提权窗口聚焦时低级键盘钩子仍能收到热键（用户日志中听写可启动/停止），与 pitfalls"管理员窗口收不到热键"的旧记录存在张力，待真机复核后再修订该条。

## 变更历史

- 2026-09-19: 增加终端目标路径并移除 TUI RuntimeId 依赖。
- 2026-09-22: Windows Terminal 改用受保护剪贴板粘贴，修复输入事件提交成功但界面无文字的回归。
- 2026-09-22: 根据分发端日志改用 Ctrl+Shift+V，并增加进程名终端识别兜底。
- 2026-09-22: 真机定位根因为提权失配（UIPI）；捕获阶段增加提权失配拒绝与管理员指引，新增 check_elevation_guard 回归。
- 2026-09-22: 仅将明确的 ACCESS_DENIED 视为高权限目标，其他令牌查询失败保持未知并放行。

# 当前任务状态

> 只记录此刻状态、下一步和接手所需事实；历史过程查 Git 与 CHANGELOG。

## 当前任务

主分支处于 **v0.1.2 发布后的输入兼容与安全收口**。

- GitHub 最新正式发行版是 `v0.1.2`，基础包自带独立 Python、依赖、语音模型和标点模型；
  校对模型由设置页单独下载。
- 主分支在该 Release 之后新增了 Windows Terminal 目标识别与 Ctrl+Shift+V、热键主键全程
  suppress、UIPI 权限失配拒绝、剪贴板竞争保护等修复。现有 `v0.1.2` ZIP 不包含这些提交。
- 代码版本号仍是 `0.1.2`，一键更新不会发现同版本源码变化。发布这些修复时必须提升版本号、
  重新构建自包含包并创建新 Release。
- 用户本地 `config.json` 有未提交修改；继续排除提交和分发产物。

## 当前代码状态

- 默认通过 `VK_PACKET` 实时上屏；微信使用受保护 Ctrl+V，Windows Terminal 使用受保护
  Ctrl+Shift+V。剪贴板事务在删除待替换文字前完成稳定快照和临时发布，并用序列号保护用户
  并发复制、半发布失败与恢复边界。
- 目标捕获锁定顶层窗口与实际焦点身份。Windows Terminal 和 WPS 使用原生焦点路径；WPS
  允许已捕获的跨进程编辑控件。非提权程序遇到明确提权的顶层或焦点进程时拒绝开始。
- 热键状态机从主键命中到 key-up 全程阻断透传；输入活动守卫在修饰键先释放时仍把主键重复
  识别为本次热键，避免误报手动编辑。
- 停顿锁句调用本地标点模型且只允许插入标点；停止后可选 Qwen GGUF 统一校对。
- 设置、托盘、悬浮窗、自包含安装、一键更新和可选校对模型下载均已实现。

## 当前验证

- `scripts/check_session.py`：74 项通过。
- `scripts/check_elevation_guard.py`：10 项通过。
- `python scripts/check_all.py --quiet`：通过；包含治理同步、发行结构、一键更新、会话与权限检查。
- 自动检查只使用模拟目标或脚本自建窗口。微信、WPS、Windows Terminal、麦克风和不同权限
  组合仍以用户真机结果为最终验收。

## 下一步

1. 用当前源码复验非提权 Windows Terminal、微信连续 partial、WPS 表格单元格及连续热键切换。
2. 真机通过后提升版本号，重建自包含 ZIP/SHA-256，并发布包含这些修复的新版本。
3. 继续 Windows 10 虚拟机的 GUI、真实听写和可选校对模型下载验收。
4. 清理退出时可能遗留的 `debug_capture.wav`，满足临时音频退出清理约束。

## 已知取舍

- 1.7B 校对模型可能引入同音字错误；可换 4B GGUF，速度会下降。
- 听写期间稳定前缀保留，模型尚未稳定的尾部允许退格修正；停止后才统一改写内容。
- 剪贴板预检与发布失败时保留原正文并停止会话；临时文本发布成功后的跨进程粘贴无法成为
  原子操作，失败时关闭会话以避免按错误账本继续删除。
- Windows 10 原生毛玻璃使用非公开合成接口，能力不足时回退深蓝绘制；Windows 11 待实机验证。

## 交接入口

1. [AGENTS.md](../AGENTS.md)
2. [系统概览](overview.md)
3. [部署与发行](deployment.md)
4. [环境陷阱](pitfalls.md)
5. [性能可靠性计划](plans/active/performance-reliability.md)
6. [Windows 分发验证计划](plans/active/windows-release-validation.md)

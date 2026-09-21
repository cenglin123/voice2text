# 项目记忆索引

> Agent 启动或 compact 恢复时应读取本文件——本文件的索引段是**经验类知识的统一检索入口**。
> 关键摘要已内联在 AGENTS.md「项目记忆」段——本文件是详细版本。
> **索引段由 `python scripts/maintain.py` 自动重建——覆盖 `.agents/memory/` 记忆条目与 `docs/problems/bugfix/` 文档；agent 只负责经验的沉淀与检索，禁止手工编辑标记段内容。**

## 记忆条目索引

<!-- memory-index:start -->
> 本段由 `python scripts/maintain.py` 自动重建，禁止手工编辑。
> 最近重建：2026-09-21 17:59

### user
- [role.md](user/role.md) — 用户画像 · 更新于 2026-09-15 · active

### bugfix（docs/problems/bugfix/）
- [设置快捷键时修饰键捕获错误](../../docs/problems/bugfix/settings-modifier-capture.md) — fixed · medium · active · 更新于 2026-09-21
- [分发版使用帮助仍尝试打开未打包的 README](../../docs/problems/bugfix/release-help-document-missing.md) — fixed · low · active · 更新于 2026-09-21
- [微信富文本输入框会话中断与锁句标点误覆盖](../../docs/problems/bugfix/weixin-volatile-input-and-punctuation-gate.md) — investigating · high · active · 更新于 2026-09-21
- [Alt+V 多次切换后 Alt 修饰键可能残留按下状态](../../docs/problems/bugfix/hotkey-alt-latched-after-toggle.md) — mitigated · high · active · 更新于 2026-09-21
- [WPS 自绘编辑区无法通过 UIA 可编辑验证](../../docs/problems/bugfix/wps-custom-editor-target-detection.md) — investigating · high · active · 更新于 2026-09-20
- [未安装校对模型时禁止开启二次校对](../../docs/problems/bugfix/proofread-toggle-requires-model.md) — fixed · low · active · 更新于 2026-09-19
- [Python 证书链失败导致模型下载无法完成](../../docs/problems/bugfix/model-download-certificate-chain.md) — mitigated · medium · active · 更新于 2026-09-19
- [安装器可能选中不兼容的系统 Python](../../docs/problems/bugfix/installer-python-compatibility.md) — fixed · medium · active · 更新于 2026-09-19
- [设置页滑块在最小值时左端圆点被裁切](../../docs/problems/bugfix/settings-slider-endpoint-clipping.md) — fixed · low · active · 更新于 2026-09-19
- [连续说话时校对完全不生效（无标点、语气词残留）](../../docs/problems/bugfix/proofread-not-applied-continuous-speech.md) — fixed · high · active · 更新于 2026-09-19
- [听写失焦后文字或校对可能写到其他位置](../../docs/problems/bugfix/session-target-lock.md) — fixed · high · active · 更新于 2026-09-19
- [设置窗口四角出现向内的蓝色块](../../docs/problems/bugfix/settings-corner-mask-inset.md) — fixed · low · active · 更新于 2026-09-19
- [OpenCode TUI 听写已启动但没有文字](../../docs/problems/bugfix/terminal-tui-input.md) — fixed · high · active · 更新于 2026-09-19
- [毛玻璃悬浮窗圆角锯齿与角落蓝底](../../docs/problems/bugfix/widget-glass-corners.md) — fixed · medium · active · 更新于 2026-09-19
- [悬浮窗拖动时 ULW 旧坐标撤销 Tk 移动](../../docs/problems/bugfix/widget-drag-position.md) — fixed · medium · active · 更新于 2026-09-18
- [设置页缩放滑条无法达到配置支持的范围](../../docs/problems/bugfix/settings-slider-range.md) — fixed · low · active · 更新于 2026-09-18
- [听写中途已识别文字全部消失并弹出输入法 v 模式面板](../../docs/problems/bugfix/ime-vmode-text-vanish.md) — fixed · high · active · 更新于 2026-09-18
<!-- memory-index:end -->

## 记忆规则

### 写入条件

- `user/role.md`：首次透露偏好 / 用户明确要求 / ≥2 次同模式反馈
- `project/`：用户说"我要做 X 项目" / 多轮对话深入且跨会话
- `feedback/`：用户明确评价输出 / 同一类修正 ≥2 次
- `docs/problems/bugfix/`：bugfix 文档（何时写、怎么写见 AGENTS.md「Bugfix 沉淀」段与该目录 `_template.md`，此处不重复定义）

### 写入前查重

新建记忆文件或 bugfix 文档前，先读上方索引确认是否已有相似条目：
- 高相似 → 更新现有文件（bugfix 文档一事一篇除外——同根因再犯时**修订原文档**补充条件，不新开第二篇）
- 中等相似（同主题不同视角）→ 新文件引用旧文件
- 低相似 → 正常新增

### 确认 touch（读入方向）

记忆文件（`user/`、`project/`、`feedback/` 等）的 frontmatter 约定与 bugfix 文档一致：`liveness: active | dormant | archived`、`last_confirmed`、`confirmed_count`。新建记忆文件时带上这三个字段；touch 时更新后两个。

任务前检索命中某条记忆条目或 bugfix 文档并**实际遵循**后，在完工清单「记忆自检」项更新其 frontmatter：`last_confirmed` 更新为当日、`confirmed_count` +1。未实际遵循不 touch。

字段缺失时维护统计以 git 最后提交时间兜底——git 修改 ≠ 确认有效，只补日期，不虚增计数。口径以 AGENTS.md 完工检查清单「记忆自检」项为准。

**时间戳来源**：
- 首选：frontmatter 中的 `last_confirmed` 字段（agent 显式写入）
- 兜底：`git log -1 --format=%ai -- <文件路径>`（最后提交时间）
- 注意：git 提交时间 ≠ 确认有效，仅用于补全缺失的日期字段

### 维护分工

- **Agent 负责**：经验的沉淀（写入 / 更新记忆文件与 bugfix 文档）与检索（任务前读索引）；更新记忆后同步 AGENTS.md「项目记忆」内联摘要
- **脚本负责**：MEMORY.md 索引段由 `python scripts/maintain.py` 每次维护自动重建

`.agents/memory/` 持续 30 天无更新 → 维护报告提示"记忆目录空转"（基于 git 提交时间）

# CHANGELOG

## 2026-09-15

### 初始化文档体系

#### 变更内容
- 建立 agent-first 文档结构：AGENTS.md（含同步副本）+ docs/ 全套 + plans/ + 记忆系统 + 维护脚本；git 仓库与 pre-commit hook 就绪。出生档案见 docs/plans/completed/initialization.md

---

<!--
说明：
- 日期节倒序，最新在前。日期格式 `## YYYY-MM-DD`，可附冒号 + 标题，如 `## 2026-04-17：初始化`。
- 同一天的多次修改合并到同一个日期节，用 `###` 区分主题。
- 写入前不要读全文，用 `python scripts/changelog.py titles/show/add/recent` 查看标题树、局部读取、追加和近期浏览。
- 当前工作状态写在 docs/CURRENT.md；CHANGELOG 只记录历史变更。
-->

> 本文档的治理规则见 AGENTS.md「文档维护原则」段。

### 开发计划独立审计与修订

#### 变更内容
- 审计子代理核查结论 needs rework：llama-cpp-python PyPI 无 Windows wheel（blocker，改用 abetlen 索引+随包携带）、Python 本体自包含（embeddable Python）、可编辑检测定案 uiautomation、partial 整句刷新策略；另修 8 项 minor（阶段1占位入口、热键自检判定、Qwen3 关思考模式+10s 超时、停止时终校、临时文件清理、剪贴板仅文本、模型 URL 钉死、托盘依赖前置）。计划/overview/pitfalls/deployment/AGENTS 同步修订

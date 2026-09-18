# CHANGELOG

## 2026-09-18

### 修复：听写中途文字消失+输入法v模式面板

#### 变更内容
- 三缺陷叠加：热键Alt+V透传进输入法（改suppress=True）、合成Ctrl+V零间隔被IME拆散（键间加间隔+清修饰键）、停止时剪贴板恢复与最后一次粘贴竞态（join后延迟0.3s）。档案见 docs/problems/bugfix/ime-vmode-text-vanish.md

### 校对交互重构：停止后统一校对

#### 变更内容
- 用户决策：听写期间屏幕文字只增不改，Alt+V 停止后按锁定句分块（≤60字）统一校对并替换。同时修复连续说话校对不生效：endpoint 阈值 1.5s→0.8s、prompt 强化、照抄检测加温重试；替换记账改为 replace_committed_range。档案见 bugfix/proofread-not-applied-continuous-speech.md

### 上屏机制重构：Unicode 注入替代剪贴板

#### 变更内容
- 用户报告 Win+V 剪贴板历史被 partial 刷屏。新默认路径：SendInput KEYEVENTF_UNICODE（VK_PACKET）字符直发光标处，不经剪贴板、绕过输入法；剪贴板+Ctrl+V 降级为 config.input_clipboard=true 兜底；剪贴板保存/恢复逻辑与停止延迟随之删除。App 级全链验证剪贴板零写入



---

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

### 阶段1完成：项目骨架与一键安装

#### 变更内容
- 交付 requirements.txt（依赖全钉死实测版本）、install.bat（venv/embeddable 双路径自包含，处理 Store 假 python、._pth 隔离、pip 可重入、PYTHONNOUSERSITE 隔离）、run.bat（解释器探活）、scripts/download_models.py（多源 fallback+断点续传）、voice2text 包骨架（config/main 占位）。venv 与 embeddable 分支均全链路实测；独立 reviewer 两轮审查通过（修复 embeddable 隔离 blocker、3.9 死循环回归等）。已知关键事实：sherpa-onnx 1.13.x 模块名为 sherpa_onnx；Qwen3-1.7B Q4_K_M 来自 unsloth 仓

### 阶段2完成：热键与音频采集

#### 变更内容
- 交付 hotkey.py（keyboard 钩子+首按自检+Event 信号）、capture.py（16k 直采/设备默认采样率回退重采样、回调拷贝入队、3s 看门狗、调试 wav）、main.py 常驻循环。reviewer 两轮审查：修复直采路径入队回调缓冲区视图（blocker）、中途拔麦克风看门狗等 6 项；环境限制（沙箱注入不可靠/无麦克风）列入用户验收

### 阶段3完成：流式识别与实时上屏

#### 变更内容
- 交付 asr.py（StreamingASR+worker线程：partial去重/endpoint锁句/尾句/COM/异常兜底）、input.py（TextInserter：UIA检测/黑名单归一化/整句刷新记账/脱管机制/会话闸门/剪贴板恢复）、main.py（会话代数/懒加载顺序/worker错误善后）。真ASR全链验证（TTS wav→识别→模拟屏幕逐字一致）。reviewer pass with issues：修3 major（剪贴板占用杀worker、焦点切出切回重复上屏、join超时旧worker污染）+5 minor

### 阶段4完成：停顿检测与二次校对

#### 变更内容
- 交付 proofread.py（Qwen3 /no_think+门禁+软超时+COM）、TextInserter.replace_committed（按句替换唯一入口+锁串行化）、main 接线（停止顺序修正：ASR→校对→关闸，尾句全链走完）。真实模型验证：语气词清除+标点补全，单句 0.4-1.1s；App 级两语音全链最终屏幕为整洁书面语。reviewer pass with issues：修 COM 初始化 major + 6 minor

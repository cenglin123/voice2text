---
id: bugfix-proofread-not-applied-continuous-speech
type: bugfix
title: 连续说话时校对完全不生效（无标点、语气词残留）
status: fixed
severity: high
liveness: active
last_confirmed: ""
confirmed_count: 0
tags: [校对, Qwen, endpoint, 分句]
related_files: [voice2text/proofread.py, voice2text/config.py, voice2text/main.py]
verification:
  level: manual
created_at: 2026-09-18
updated_at: 2026-09-18
evidence:
  - type: user_quote
    ref: "有一个问题就是没有标准符号全是文字连空格都没有啊这句话就是我刚才用语音输入输入的"
  - type: conversation_context
    ref: "本地复现：45 字无语气词长句 proofread 返回与原文完全相同（模型照抄）"
---

# 连续说话时校对完全不生效（无标点、语气词残留）

## 现在的行为

真机连续说话（子句间自然停顿 < 1.5s）后停止，上屏文本保持 ASR 原始输出：
无标点、无空格、语气词（"哈嗯"）残留，二次校对从未生效。

## 预期的行为

校对后的整洁书面语（标点、去语气词、顺句）。

## 复现方式

中文连续听写一段 40 字以上、中间无 1.5s 以上停顿的话 → 按 Alt+V → 观察文本未优化。

## 原因是什么

两个独立原因叠加（均已确认）：

1. **分句阈值过高**：endpoint rule2 = 1.5s，而自然子句停顿多为 0.3~0.8s——连续说话
   永不锁句，全部文本滞留为 partial，校对无输入。
2. **模型照抄长句**：停止后尾句统一校对时，45 字的无语气词长句让 Qwen3-1.7B 原样
   照抄输入（temperature 0.3 下复现稳定），照抄结果与原文相同，替换被"无实质变化"
   检查跳过。带语气词/错别字的短句则正常（模型"有活干"）。

## 怎么修复的

1. endpoint_pause_seconds 1.5 → 0.8（config 默认值与 config.json）
2. 校对 prompt 强化：明确"无论句子多长必须加标点，绝不能照抄"+ 增加长句示例
3. 照抄检测重试：结果与原文相同且原文无标点时，temperature 加温到 0.8 重试一次
4. 交互重构（用户决策）：听写期间屏幕文字只增不改；停止后把锁定句按 ≤60 字分块，
   逐块统一校对并替换（main._finalize_proofread），校对后台线程删除——分块同时
   规避了长文本照抄问题，替换记账改为 replace_committed_range（块内多句合并替换）

## 验证结果

本地复现用户的连续语音场景（TTS 0.5s 子句停顿 + 立即停止）：停止后统一校对生效，
最终屏幕含标点、语气词清除；多句范围替换记账逐字正确（含后续句与 partial 保留）。
已知残留：1.7B 校对可能引入同音字错误（"全是文字"→"诠释文字"），属模型能力边界，
可换更大 GGUF 改善。真机复验方式：连续听写一句话按 Alt+V，观察停止后文本自动变为
带标点版本。

## 风险和后续

- 停止后有数秒校对等待期（取决于文本量），期间按 Alt+V 会排队到校对结束后生效
- 分块替换在屏幕上逐块跳动数次，若体验差可改为全部块完成后一次性替换
- 阶段 5 评估：换 Qwen3-4B 对比校对质量/速度

## 变更历史

- 2026-09-18: 初始修复（阈值/prompt/重试）+ 交互重构（停止后统一校对）

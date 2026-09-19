"""二次校对：Qwen3-1.7B（GGUF, llama-cpp-python）清理语音转录文本。

行为（用户决策：听写期间屏幕文字只增不改，Alt+V 停止后才统一校对）：
- 听写中：endpoint 锁句仅用于分段记账，不做校对替换
- 停止后：main 把锁定句按 ≤60 字分块，逐块调用本模块校对并替换
- 延迟预算由调用方执行（proofread_timeout_seconds）；本模块用 max_tokens 限制最坏生成时长

Qwen3 注意（docs/pitfalls.md）：默认开启思考模式——0.3.35 的 chat API 无
chat_template_kwargs，用 /no_think 后缀关闭 + 防御性剥离 <think> 段。
"""

from __future__ import annotations

import os
import re
import threading

import llama_cpp

from voice2text.config import AppConfig

_NO_THINK = "/no_think"
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_UNCLOSED = re.compile(r"<think>.*$", re.DOTALL)  # max_tokens 截断在思考段内
_OUTPUT_PREFIX = re.compile(r"^(?:输出|校对后|结果)[：:]\s*")
_HAS_PUNCT = re.compile(r"[，。？！、；：,.?!]")
_HAS_TERMINAL = re.compile(r"[。？！.!?]$")
_HAS_CJK = re.compile(r"[\u3400-\u9fff]")

SYSTEM_PROMPT = (
    "你是语音转录校对器。输入是一句中文语音识别的原始结果，可能包含错别字"
    "（尤其同音字）、赘余语气词（嗯、啊、呃、那个、就是说之类）、口语不连贯、"
    "且没有标点。请输出校对后的句子：修正错别字、删除赘余语气词、理顺语句、"
    "添加合适的标点。要求：保持原意和原语言，不增删实质内容，不改数字和专有名词；"
    "无论句子多长，都必须添加标点断句，绝不能原样照抄输入；"
    "只输出校对后的句子本身，不要任何解释或前缀。\n"
    "示例：\n"
    "输入：嗯那个我们明天上午九点在会议室碰头讨论一下方案\n"
    "输出：我们明天上午九点在会议室碰头，讨论一下方案。\n"
    "输入：这个项目整体来说进展是比较顺利的但是在细节上还有很多需要打磨的地方\n"
    "输出：这个项目整体来说进展是比较顺利的，但是在细节上还有很多需要打磨的地方。"
)

CHUNK_CHARS = 60  # 分块校对上限：小模型对更长文本会照抄原文（实测 bug）


def chunk_sentences(sentences: list[str], max_chars: int = CHUNK_CHARS) -> list[tuple[int, int, str]]:
    """把锁定句列表切成连续块，返回 (起始句序号, 结束句序号, 块文本)。

    单句超过 max_chars 时独立成块（不截断——截断会破坏语义）。
    """
    chunks: list[tuple[int, int, str]] = []
    i = 0
    while i < len(sentences):
        j = i
        parts: list[str] = []
        while j < len(sentences):
            part = sentences[j]
            if parts and sum(len(p) for p in parts) + len(part) > max_chars:
                break
            parts.append(part)
            j += 1
        chunks.append((i, j - 1, "".join(parts)))
        i = j
    return chunks


PUNCT_SYSTEM_PROMPT = (
    "你负责给中文句子添加标点符号。在合适的位置插入逗号、句号、问号等，"
    "不得增加、删除或改写任何文字。只输出加标点后的句子。\n"
    "示例：\n输入：我们明天上午九点在会议室碰头讨论一下方案\n输出：我们明天上午九点在会议室碰头，讨论一下方案。"
)

_NO_PUNCT = re.compile(r"[，。？！、；：,.?!《》“”\"'\s]+")


class Proofreader:
    """加载 GGUF 并执行校对。Llama 实例非线程安全——用锁串行化。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._lock = threading.Lock()
        self.last_outcome = "not_run"
        self._llm = llama_cpp.Llama(
            model_path=str(cfg.llm_model_path),
            n_ctx=1024,  # 分块校对足够（系统提示 ~250 token + 块文本 + 输出）
            n_threads=min(8, os.cpu_count() or 4),
            verbose=False,
        )

    def proofread(self, text: str) -> str | None:
        """兼容调用入口；并发调用方应使用 proofread_with_outcome。"""
        result, outcome = self.proofread_with_outcome(text)
        self.last_outcome = outcome
        return result

    def proofread_with_outcome(self, text: str) -> tuple[str | None, str]:
        """校对一块文本。返回校正文本；失败/可疑时返回 None（调用方保留原文）。

        两段式：先清理（错字/语气词/顺句）；原文无标点而结果仍无标点时
        （复合指令超出 1.7B 遵循度，实测），再走一次"只加标点"专责任务，
        并校验去标点后文字与清理结果一致（防模型改字）。
        """
        text = text.strip()
        if not text:
            return None, "empty"
        result = self._generate(text, SYSTEM_PROMPT, temperature=0.3)
        # 清理任务失败或仍未给出标点时，始终再走一次只加标点的窄任务。
        # 这条路径只允许插入标点，因此可以安全地从原文直接降级。
        base = result or text
        if not _HAS_PUNCT.search(base):
            punctuated = self._generate(base, PUNCT_SYSTEM_PROMPT, temperature=0.3)
            if punctuated is not None and _HAS_PUNCT.search(punctuated):
                if _NO_PUNCT.sub("", punctuated) == _NO_PUNCT.sub("", base):
                    return self._ensure_terminal(punctuated), "punctuation_model_success"
        if result is not None and _HAS_PUNCT.search(result):
            return self._ensure_terminal(result), "cleanup_success"
        # 清理输出无标点且窄任务未成功时，不能把可能改写过的清理结果直接上屏。
        # 降级必须回到原始识别文本，只允许补一个句末符号。
        result = text
        # 两次本地模型调用都失败时也不能把无标点原文原样留下；只补句末符号，
        # 不猜测内部断句，不改变任何识别文字。
        return self._ensure_terminal(result), "terminal_fallback"

    @staticmethod
    def _ensure_terminal(text: str) -> str:
        """只给中文自然语言兜底补句末符号，数字、URL、路径等保持原样。"""
        if _HAS_CJK.search(text) and not _HAS_TERMINAL.search(text):
            return text + "。"
        return text

    def _generate(self, text: str, system: str, temperature: float) -> str | None:
        max_tokens = min(512, len(text) * 3 + 64)
        try:
            with self._lock:
                out = self._llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": text + " " + _NO_THINK},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
        except Exception:  # noqa: BLE001 —— 推理异常保留原文
            return None
        try:
            raw = out["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return None
        cleaned = _THINK_BLOCK.sub("", raw)
        cleaned = _THINK_UNCLOSED.sub("", cleaned).strip()
        cleaned = _OUTPUT_PREFIX.sub("", cleaned).strip()
        # 模型偶发无视"不要解释"——常见形式是引号包裹，尽力剥壳
        for wrapper in (('"', '"'), ('"', '"'), ("「", "」")):
            if cleaned.startswith(wrapper[0]) and cleaned.endswith(wrapper[1]) and len(cleaned) >= 2:
                cleaned = cleaned[1:-1].strip()
        if not self._plausible(text, cleaned):
            return None
        return cleaned

    @staticmethod
    def _plausible(original: str, result: str) -> bool:
        """结果合理性门禁：防模型复读任务说明、跑题替换、输出空壳。"""
        if not result:
            return False
        if len(result) > len(original) * 3 + 30:  # 校对只会变短或近似等长
            return False
        # 跑题防护：校对结果应与原文高度同源——字符 bigram 重叠率过低视为跑题
        if len(original) >= 4:
            grams = {original[i : i + 2] for i in range(len(original) - 1)}
            hits = sum(1 for i in range(len(result) - 1) if result[i : i + 2] in grams)
            total = max(len(result) - 1, 1)
            if hits / total < 0.3:
                return False
        return True

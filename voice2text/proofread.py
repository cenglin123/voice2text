"""二次校对：Qwen3-1.7B（GGUF, llama-cpp-python）清理语音转录文本。

职责（docs/overview.md「为什么校对要等停顿」）：
- 输入 endpoint 锁定的句子（原始 ASR 输出：无标点、可能含同音错字、赘余语气词）
- 输出整洁书面语：修正错别字、删语气词、理顺、加标点
- 延迟预算由调用方执行（proofread_timeout_seconds）；本模块用 max_tokens 限制最坏生成时长

Qwen3 注意（docs/pitfalls.md）：默认开启思考模式——0.3.35 的 chat API 无
chat_template_kwargs，用 /no_think 后缀关闭 + 防御性剥离 <think> 段。
"""

from __future__ import annotations

import os
import queue
import re
import threading

import llama_cpp

from voice2text.config import AppConfig

_NO_THINK = "/no_think"
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_UNCLOSED = re.compile(r"<think>.*$", re.DOTALL)  # max_tokens 截断在思考段内
_OUTPUT_PREFIX = re.compile(r"^(?:输出|校对后|结果)[：:]\s*")

SYSTEM_PROMPT = (
    "你是语音转录校对器。输入是一句中文语音识别的原始结果，可能包含错别字"
    "（尤其同音字）、赘余语气词（嗯、啊、呃、那个、就是说之类）、口语不连贯、"
    "且没有标点。请输出校对后的句子：修正错别字、删除赘余语气词、理顺语句、"
    "添加合适的标点。要求：保持原意和原语言，不增删实质内容，不改数字和专有名词；"
    "只输出校对后的句子本身，不要任何解释或前缀。\n"
    "示例：\n"
    "输入：嗯那个我们明天上午九点在会议室碰头讨论一下方案\n"
    "输出：我们明天上午九点在会议室碰头，讨论一下方案。"
)


class Proofreader:
    """加载 GGUF 并执行单句校对。Llama 实例非线程安全——用锁串行化。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._timeout = cfg.proofread_timeout_seconds
        self._lock = threading.Lock()
        self._llm = llama_cpp.Llama(
            model_path=str(cfg.llm_model_path),
            n_ctx=1024,  # 单句校对足够（系统提示 ~200 token + 句子 + 输出）
            n_threads=min(8, os.cpu_count() or 4),
            verbose=False,
        )

    def proofread(self, text: str) -> str | None:
        """校对一句。返回校正文本；失败/可疑时返回 None（调用方保留原文）。

        延迟控制：max_tokens 按输入长度收紧（中文≈1 token/字），
        单句生成上限约 len*3+64 token，配合调用方超时兜底。
        """
        text = text.strip()
        if not text:
            return None
        max_tokens = min(512, len(text) * 3 + 64)
        try:
            with self._lock:
                out = self._llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text + " " + _NO_THINK},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.3,
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


class ProofreadWorker(threading.Thread):
    """校对工作线程：串行消费句子，逐句回调；超时跳过保留原文。

    Llama 生成不可中断——超时由"调用方放弃等待"实现：worker 内部对单句
    计时，超过 timeout 的结果直接丢弃（生成自然结束后继续处理队列）。
    """

    def __init__(self, proofreader: Proofreader, timeout: float, on_result) -> None:
        super().__init__(daemon=True, name="proofread-worker")
        self._proofreader = proofreader
        self._timeout = timeout
        self._on_result = on_result
        self._queue: "queue.Queue[tuple[int, str] | None]" = queue.Queue()
        self.error: str | None = None

    def submit(self, index: int, text: str) -> None:
        self._queue.put((index, text))

    def finish(self) -> None:
        """请求收尾：处理完已提交的句子后退出（Alt+V 停止路径）。"""
        self._queue.put(None)

    def run(self) -> None:
        # 回调链会走到 uiautomation（COM）——与 ASR worker 相同，线程各自初始化
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._run_loop()
        except Exception as exc:  # noqa: BLE001
            self.error = f"校对线程异常退出：{exc}"

    def _run_loop(self) -> None:
        import time

        while True:
            item = self._queue.get()
            if item is None:
                return
            index, text = item
            t0 = time.monotonic()
            corrected = self._proofreader.proofread(text)
            if time.monotonic() - t0 > self._timeout:
                corrected = None  # 超时丢弃（生成已完成，只是结果不再采用）
            self._on_result(index, text, corrected)

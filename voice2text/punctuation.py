"""停顿锁句时的本地标点恢复，只允许插入标点，不允许改写识别文字。"""

from __future__ import annotations

import re

import sherpa_onnx

from voice2text.config import AppConfig

_PUNCTUATION = re.compile(r"[，。？！、；：,.!?;:]")


def _project_punctuation(original: str, result: str) -> str | None:
    """把模型新增标点投影回原文，保留原文全部字符及空格。"""
    required = [char for char in original if not char.isspace()]
    additions: dict[int, list[str]] = {}
    source_index = 0
    for char in result:
        if char.isspace():
            continue
        if source_index < len(required) and char == required[source_index]:
            source_index += 1
        elif _PUNCTUATION.fullmatch(char):
            # 句首标点和同一字符边界的连续标点通常是模型错位；宁可保留无标点
            # 原文，也不能把“？…”或“，，”写入用户正在编辑的文本。
            if source_index == 0 or source_index in additions:
                return None
            additions.setdefault(source_index, []).append(char)
        else:
            return None
    if source_index != len(required):
        return None

    projected = "".join(additions.get(0, ()))
    source_index = 0
    for char in original:
        projected += char
        if not char.isspace():
            source_index += 1
            projected += "".join(additions.get(source_index, ()))
    return projected


class PunctuationRestorer:
    """封装 sherpa-onnx CT-Transformer 标点模型。"""

    def __init__(self, cfg: AppConfig) -> None:
        model = sherpa_onnx.OfflinePunctuationModelConfig(
            ct_transformer=str(cfg.punctuation_model_path),
            num_threads=1,
            debug=False,
            provider="cpu",
        )
        self._engine = sherpa_onnx.OfflinePunctuation(
            sherpa_onnx.OfflinePunctuationConfig(model=model)
        )

    def restore(self, text: str) -> tuple[str, str]:
        """返回（结果，状态）。结果若改变了非标点字符则拒绝。"""
        if not text.strip():
            return text, "empty"
        try:
            result = self._engine.add_punctuation(text)
        except Exception:  # noqa: BLE001 —— 标点失败不应中断识别
            return text, "error"
        projected = _project_punctuation(text, result) if result else None
        if projected is None:
            return text, "unsafe_change"
        return projected, "applied" if projected != text else "unchanged"

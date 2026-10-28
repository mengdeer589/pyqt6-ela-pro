"""外部 ``usage`` → :class:`ElaChatStats` 的归一化（``pyqt6_ela_pro.chat`` 内部模块）。

四路词元**互不重叠**：``prompt`` 只含未命中缓存的输入。OpenAI / DeepSeek 的
``prompt_tokens`` 包含缓存命中部分，原样连同 ``cache_read_tokens`` 一起填进去，
``ElaChatSessionStats`` 的四路和与 :func:`~pyqt6_ela_pro.chat._pricing.stats_cost`
都会把缓存算两遍（上下文圆环偏高、花费偏贵）。本模块是外部 usage 的唯一转换
入口（``binder`` 与 ``journal`` 共用）。
"""

from __future__ import annotations

from dataclasses import replace

from .message import ElaChatStats, _as_float, _as_int


def _positive(*values) -> int:
    """取第一个正整数值（``None`` / 0 / 非法值跳过）。"""
    for value in values:
        number = _as_int(value)
        if number > 0:
            return number
    return 0


def stats_from_usage(usage, ttftMs: float = 0.0, tps: float = 0.0) -> ElaChatStats:
    """把后端 ``usage`` 归一成互不重叠的四路用量。

    - 有 ``prompt_tokens``（OpenAI / DeepSeek 形态）：它**包含**缓存命中，先扣掉
      再落库；缓存值超过原始 prompt 时截断（脏数据不能把四路和顶爆）；
    - 只有 ``input_tokens``（Anthropic 形态）：它本身不含缓存，原样使用，并补读
      ``cache_read_input_tokens``；
    - 传 :class:`ElaChatStats` 原样返回，只补缺失的 ``ttft`` / ``tps``
      （宿主管这叫「已归一化」的数据，不要二次扣减）。
    """
    if isinstance(usage, ElaChatStats):
        stats = usage
        if ttftMs and not stats.ttft_ms:
            stats = replace(stats, ttft_ms=_as_float(ttftMs))
        if tps and not stats.tps:
            stats = replace(stats, tps=_as_float(tps))
        return stats

    details = getattr(usage, "prompt_tokens_details", None)
    completionDetails = getattr(usage, "completion_tokens_details", None)
    cacheRead = _positive(
        getattr(usage, "prompt_cache_hit_tokens", 0),
        getattr(details, "cached_tokens", 0),
        getattr(usage, "cache_read_input_tokens", 0),
    )
    cacheWrite = _positive(
        getattr(usage, "cache_creation_input_tokens", 0),
        getattr(details, "cache_write_tokens", 0),
    )
    reasoning = _positive(
        getattr(usage, "reasoning_tokens", 0),
        getattr(completionDetails, "reasoning_tokens", 0),
    )
    rawPrompt = _as_int(getattr(usage, "prompt_tokens", 0))
    inputPrompt = _as_int(getattr(usage, "input_tokens", 0))
    if rawPrompt > 0 or not inputPrompt:
        # OpenAI / DeepSeek：prompt 含缓存，扣成「未命中缓存」才是一路
        raw = max(0, rawPrompt)
        cacheRead = min(cacheRead, raw)
        cacheWrite = min(cacheWrite, raw - cacheRead)
        prompt = raw - cacheRead - cacheWrite
        completion = _as_int(getattr(usage, "completion_tokens", 0))
    else:
        # Anthropic：input_tokens 本身不含缓存
        prompt = max(0, inputPrompt)
        completion = _as_int(getattr(usage, "output_tokens", 0))
    return ElaChatStats(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=_as_int(getattr(usage, "total_tokens", 0)),
        reasoning_tokens=reasoning,
        cache_read_tokens=cacheRead,
        cache_write_tokens=cacheWrite,
        ttft_ms=_as_float(ttftMs),
        tps=_as_float(tps),
    )

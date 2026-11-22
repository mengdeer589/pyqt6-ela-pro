"""外部 ``usage`` → :class:`ElaChatStats` 的归一化（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .message import ElaChatStats, _as_float, _as_int


def _get(value, key, default=0):
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _positive(*values) -> int:
    """取第一个正整数值（``None`` / 0 / 非法值跳过）。"""
    for value in values:
        number = _as_int(value)
        if number > 0:
            return number
    return 0


def stats_from_usage(usage, ttftMs: float = 0.0, tps: float = 0.0) -> ElaChatStats:
    """把后端 ``usage`` 归一成互不重叠的四路用量。
    OpenAI / DeepSeek 形态（有 ``prompt_tokens``）先扣掉缓存命中；Anthropic 形态
    （只有 ``input_tokens``）本身不含缓存。传 ``ElaChatStats`` 原样返回，只补缺失的
    """
    if isinstance(usage, ElaChatStats):
        stats = usage
        if ttftMs and not stats.ttft_ms:
            stats = replace(stats, ttft_ms=_as_float(ttftMs))
        if tps and not stats.tps:
            stats = replace(stats, tps=_as_float(tps))
        return stats

    details = _get(usage, "prompt_tokens_details", None)
    completionDetails = _get(usage, "completion_tokens_details", None)
    cacheRead = _positive(
        _get(usage, "prompt_cache_hit_tokens", 0),
        _get(details, "cached_tokens", 0),
        _get(usage, "cache_read_input_tokens", 0),
    )
    cacheWrite = _positive(
        _get(usage, "cache_creation_input_tokens", 0),
        _get(details, "cache_write_tokens", 0),
    )
    reasoning = _positive(
        _get(usage, "reasoning_tokens", 0),
        _get(completionDetails, "reasoning_tokens", 0),
    )
    rawPrompt = max(0, _as_int(_get(usage, "prompt_tokens", 0)))
    inputPrompt = max(0, _as_int(_get(usage, "input_tokens", 0)))
    if rawPrompt > 0 or not inputPrompt:
        # OpenAI / DeepSeek：prompt 含缓存，扣成「未命中缓存」才是一路
        raw = max(0, rawPrompt)
        cacheRead = min(cacheRead, raw)
        cacheWrite = min(cacheWrite, raw - cacheRead)
        prompt = raw - cacheRead - cacheWrite
        completion = max(0, _as_int(_get(usage, "completion_tokens", 0)))
    else:
        # Anthropic：input_tokens 本身不含缓存
        prompt = max(0, inputPrompt)
        completion = max(0, _as_int(_get(usage, "output_tokens", 0)))
    return ElaChatStats(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=max(0, _as_int(_get(usage, "total_tokens", 0))),
        reasoning_tokens=reasoning,
        cache_read_tokens=cacheRead,
        cache_write_tokens=cacheWrite,
        ttft_ms=_as_float(ttftMs),
        tps=_as_float(tps),
    )

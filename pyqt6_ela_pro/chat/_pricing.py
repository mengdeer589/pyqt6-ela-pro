"""模型定价与花费换算（``pyqt6_ela_pro.chat`` 内部模块）。

定价表不烤进库（价格会变、分上下文长度阶梯），这里只提供纯换算函数，价格表由
宿主持有并传入。口径对齐 opencode ``calculateCost``：按输入侧总量
（``prompt + cache_read + cache_write``）选**超过阈值**的档，输出与 reasoning
同价，最后除以 1e6；空定价表 / 缺字段按 0 计。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

#: 与 ``chat/__init__.py`` 的导出保持一致；``selectPricing`` 是内部选档步骤。
__all__ = [
    "ModelPricing",
    "cost_from_parts",
    "formatCost",
    "stats_cost",
]


def _finite(value, default: float = 0.0) -> float:
    """容错取有限浮点数（NaN / inf / 非法值一律归 ``default``）。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return max(0.0, out)


@dataclass(frozen=True)
class ModelPricing:
    """单个模型的每百万词元价格（美元）。缺省项按 0 计。"""

    #: 输入（未命中缓存）
    input_per_m: float = 0.0
    #: 输出（**含 reasoning**，两者同价）
    output_per_m: float = 0.0
    #: 缓存读命中
    cache_read_per_m: float = 0.0
    #: 缓存写
    cache_write_per_m: float = 0.0
    #: 上下文长度阶梯 ``((阈值词元数, 该档价格), ...)``，按阈值升序
    tiers: Tuple[Tuple[int, "ModelPricing"], ...] = field(default_factory=tuple)

    def isFree(self) -> bool:
        """是否全零（无定价 / 本地模型；有阶梯档位时按非空处理）。"""
        return not (
            self.input_per_m
            or self.output_per_m
            or self.cache_read_per_m
            or self.cache_write_per_m
            or self.tiers
        )


def _normalize_tiers(tiers) -> tuple:
    """容错整理阶梯：丢弃非法项并按阈值升序排列。"""
    items = []
    try:
        source = tiers or ()
        iter(source)
    except TypeError:
        # ``tiers=5`` 这类不可迭代值：空阶梯，而不是把 TypeError 穿透到调用方
        return ()
    for item in source:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        threshold, price = item[0], item[1]
        if not isinstance(price, ModelPricing):
            continue
        try:
            threshold = int(threshold)
        except (TypeError, ValueError, OverflowError):
            continue
        if threshold > 0:
            items.append((threshold, price))
    items.sort(key=lambda pair: pair[0])
    return tuple(items)


def selectPricing(
    promptTokens: int, pricing: Optional[ModelPricing]
) -> Optional[ModelPricing]:
    """按输入侧总量选定价档（取超过阈值的那一档）。

    判据是 ``used > threshold``，恰好等于阈值仍算基础档；``tiers`` 自身不参与
    选档（避免递归）。``pricing`` 为 ``None`` / 全零返回 ``None``。
    """
    if pricing is None:
        return None
    try:
        used = int(promptTokens)
    except (TypeError, ValueError, OverflowError):
        used = 0
    if used < 0:
        used = 0
    selected = pricing
    for threshold, price in _normalize_tiers(pricing.tiers):
        if used > threshold:
            selected = price
        else:
            break
    return None if selected.isFree() else selected


def stats_cost(stats, pricing: Optional[ModelPricing] = None) -> float:
    """把 :class:`~pyqt6_ela_pro.chat.message.ElaChatStats` 换算成美元花费。

    ``completion`` 已含 reasoning（不重复加）；``stats`` / ``pricing`` 为
    ``None`` 返回 0.0。
    """
    if stats is None or pricing is None:
        return 0.0
    prompt = _finite(getattr(stats, "prompt_tokens", 0))
    completion = _finite(getattr(stats, "completion_tokens", 0))
    cache_read = _finite(getattr(stats, "cache_read_tokens", 0))
    cache_write = _finite(getattr(stats, "cache_write_tokens", 0))
    return cost_from_parts(
        prompt,
        completion,
        cacheRead=cache_read,
        cacheWrite=cache_write,
        pricing=pricing,
    )


def cost_from_parts(
    promptTokens,
    completionTokens,
    cacheRead=0,
    cacheWrite=0,
    pricing: Optional[ModelPricing] = None,
) -> float:
    """按四路词元明细换算花费（``stats_cost`` 的低层入口）。

    ``reasoning`` 不单独计价（已含在 ``completionTokens`` 里）。
    """
    if pricing is None:
        return 0.0
    prompt = _finite(promptTokens)
    completion = _finite(completionTokens)
    cacheRead = _finite(cacheRead)
    cacheWrite = _finite(cacheWrite)
    tier = selectPricing(prompt + cacheRead + cacheWrite, pricing)
    if tier is None:
        return 0.0
    total = (
        prompt * _finite(tier.input_per_m)
        + completion * _finite(tier.output_per_m)
        + cacheRead * _finite(tier.cache_read_per_m)
        + cacheWrite * _finite(tier.cache_write_per_m)
    )
    return total / 1_000_000.0


def formatCost(usd) -> str:
    """美元金额格式化（``< 1`` 美元给 4 位小数；非法值回 ``"$0.00"``）。"""
    value = _finite(usd)
    if value <= 0:
        return "$0.00"
    if value < 1:
        text = f"{value:.4f}"
        if text == "1.0000":
            # 0.99999 这类：四位小数进位成 "1.0000"，看起来像整一美元
            text = f"{value:.5f}"
        return f"${text}"
    if value < 1000:
        return f"${value:.2f}"
    return f"${value:.0f}"

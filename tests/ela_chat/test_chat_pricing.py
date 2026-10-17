"""定价换算的阶梯边界与公开 API 边界。

两条已修的缺陷：

1. **阶梯边界文档与代码不符** —— ``selectPricing`` 的判据是 ``used > threshold``，
   而 docstring 写「取最大的**满足**档」。恰好等于阈值时（``200_000``）代码走基础档，
   按「满足」的说法应该走 200k 档 —— 差一倍价格。行为保留（它与本模块示例里
   「超过 200k 的部分按贵价计」一致），改的是文档。
2. **``_pricing.__all__`` 与包级导出不对称** —— 列了 ``selectPricing``（无外部消费者、
   无文档）却漏了 ``cost_from_parts``（``chat`` 包确实导出了、AGENTS.md 也记载了）。
"""

from __future__ import annotations

import pytest

import pyqt6_ela_pro.chat as chat_pkg
from pyqt6_ela_pro.chat import _pricing
from pyqt6_ela_pro.chat._pricing import ModelPricing, cost_from_parts, stats_cost

BASE = ModelPricing(input_per_m=3.0, output_per_m=15.0)
TIER_200K = ModelPricing(input_per_m=6.0, output_per_m=22.5)
WITH_TIER = ModelPricing(
    input_per_m=3.0, output_per_m=15.0, tiers=((200_000, TIER_200K),)
)


class _Usage:
    def __init__(
        self,
        prompt_tokens,
        completion_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.cache_read_tokens = cache_read_tokens
        self.cache_write_tokens = cache_write_tokens


class TestTierBoundary:
    """``used > threshold``：恰好等于阈值仍走基础档。"""

    def test_exactly_at_threshold_uses_the_base_tier(self):
        assert stats_cost(_Usage(200_000), WITH_TIER) == pytest.approx(0.6)

    def test_one_past_threshold_uses_the_tier(self):
        assert stats_cost(_Usage(200_001), WITH_TIER) == pytest.approx(1.200006)

    def test_just_below_threshold_uses_the_base_tier(self):
        assert stats_cost(_Usage(199_999), WITH_TIER) == pytest.approx(0.599997)

    def test_no_tier_configured(self):
        assert stats_cost(_Usage(500_000), BASE) == pytest.approx(1.5)

    def test_cache_read_tokens_count_toward_the_tier(self):
        """输入侧总量含缓存读，所以缓存也能把用量顶进阶梯档（单价随之翻倍）。"""
        usage = _Usage(199_000, cache_read_tokens=2_000)
        # 199_000 + 2_000 = 201_000 > 200_000 -> 进阶梯档，prompt 按 6.0 计
        assert stats_cost(usage, WITH_TIER) == pytest.approx(1.194)
        # 若缓存不计入档位选择，单价会停在 3.0 —— 少算一半
        assert cost_from_parts(
            199_000, 0, cacheRead=2_000, pricing=WITH_TIER
        ) == pytest.approx(199_000 * 6.0 / 1e6)

    def test_cache_write_tokens_count_toward_the_tier(self):
        """缓存写同样计入档位选择（与 opencode 的 ``prompt + read + write`` 一致）。"""
        usage = _Usage(199_000, cache_write_tokens=2_000)
        assert stats_cost(usage, WITH_TIER) == pytest.approx(199_000 * 6.0 / 1e6)

    def test_tiers_are_sorted_regardless_of_input_order(self):
        shuffled = ModelPricing(
            input_per_m=3.0,
            output_per_m=15.0,
            tiers=(
                (500_000, ModelPricing(input_per_m=12.0, output_per_m=30.0)),
                (200_000, TIER_200K),
            ),
        )
        assert cost_from_parts(600_000, 0, pricing=shuffled) == pytest.approx(7.2)

    def test_nested_tiers_do_not_recurse(self):
        inner = ModelPricing(
            input_per_m=6.0,
            output_per_m=22.5,
            tiers=((900_000, ModelPricing(input_per_m=99.0, output_per_m=99.0)),),
        )
        outer = ModelPricing(
            input_per_m=3.0, output_per_m=15.0, tiers=((200_000, inner),)
        )
        assert cost_from_parts(1_000_000, 0, pricing=outer) == pytest.approx(6.0)


class TestPublicSurfaceIsConsistent:
    def test_module_all_matches_the_package_exports(self):
        assert set(_pricing.__all__) <= set(chat_pkg.__all__)

    def test_cost_from_parts_is_exported(self):
        assert "cost_from_parts" in _pricing.__all__
        assert "cost_from_parts" in chat_pkg.__all__
        assert chat_pkg.cost_from_parts is cost_from_parts

    def test_internal_tier_step_is_not_advertised(self):
        assert "selectPricing" not in _pricing.__all__
        assert not hasattr(chat_pkg, "selectPricing")

    def test_documented_public_names_all_resolve(self):
        for name in _pricing.__all__:
            assert hasattr(chat_pkg, name), name


class TestDegenerateInputs:
    @pytest.mark.parametrize(
        "args",
        [
            (0, 0, 0, 0, None),
            (0, 0, 0, 0, ModelPricing()),
        ],
        ids=["no-pricing", "free-pricing"],
    )
    def test_zero_everything_costs_nothing(self, args):
        assert cost_from_parts(*args) == 0.0

    def test_stats_cost_tolerates_none(self):
        assert stats_cost(None, WITH_TIER) == 0.0

    def test_negative_and_nan_token_counts_are_zeroed(self):
        assert cost_from_parts(-100, -50, pricing=BASE) == 0.0
        assert cost_from_parts(float("nan"), float("inf"), pricing=BASE) == 0.0

    def test_free_model_reports_zero_not_a_wrong_amount(self):
        local = ModelPricing()
        assert local.isFree() is True
        assert cost_from_parts(1_000_000, 1_000_000, pricing=local) == 0.0


class TestFormatCost:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (0, "$0.00"),
            (0.0142, "$0.0142"),
            (0.5, "$0.5000"),
            (0.99999, "$0.99999"),
            (1.0, "$1.00"),
            (12.4, "$12.40"),
            (999.999, "$1000.00"),
            (1000.0, "$1000"),
            (1234.5, "$1234"),
        ],
        ids=repr,
    )
    def test_precision_bands(self, value, expected):
        assert _pricing.formatCost(value) == expected

    @pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf")])
    def test_invalid_values_fall_back(self, value):
        assert _pricing.formatCost(value) == "$0.00"

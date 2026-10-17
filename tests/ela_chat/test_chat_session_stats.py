"""``ElaChatSessionStats`` 聚合口径测试。

口径对齐 opencode ``getSessionContext``：**「当前用量」= 最后一条有 tokens 的
助手消息的最后一步**（多步工具轮里就是最近一次 LLM 调用），不是整轮 merge、
也不是全会话求和；累计成本才跨消息求和。
"""

from __future__ import annotations

import math

import pytest

from pyqt6_ela_pro.chat import (
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatSessionStats,
    ElaChatStats,
    ElaChatWidget,
)


def _assistant(mid, parts=(), created_at=0.0, stats=None):
    return ElaChatMessage(
        id=mid,
        role=ElaChatRoleType.Assistant,
        created_at=created_at,
        stats=stats,
        parts=tuple(parts),
    )


def _step(step, stats):
    return ElaChatPart(
        id=f"p{step}", kind=ElaChatPartKindType.Stats, stats=stats, step=step
    )


class TestFromMessages:
    def test_empty(self):
        stats = ElaChatSessionStats.fromMessages([])
        assert (stats.message_count, stats.total_tokens) == (0, 0)
        assert stats.total_cost_usd == 0.0
        assert stats.usage_percent is None
        assert stats.last_activity == 0.0

    def test_role_counts_include_system_in_total(self):
        messages = [
            ElaChatMessage(id=1, role=ElaChatRoleType.User, text="hi"),
            _assistant(2),
            _assistant(3),
            ElaChatMessage(id=4, role=ElaChatRoleType.System, text="sys"),
        ]
        stats = ElaChatSessionStats.fromMessages(messages)
        assert stats.message_count == 4
        assert stats.user_messages == 1
        assert stats.assistant_messages == 2

    def test_latest_step_of_last_message_with_tokens(self):
        """多步：取**最后一步**的四路原始用量，不是 merge 的总和。"""
        message = _assistant(
            1,
            [
                _step(
                    1,
                    ElaChatStats(
                        prompt_tokens=100, completion_tokens=10, total_tokens=110
                    ),
                ),
                _step(
                    2,
                    ElaChatStats(
                        prompt_tokens=200,
                        completion_tokens=20,
                        total_tokens=220,
                        reasoning_tokens=5,
                        cache_read_tokens=1000,
                        cache_write_tokens=50,
                    ),
                ),
            ],
            created_at=123.0,
        )
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.input_tokens == 200
        assert stats.output_tokens == 20
        assert stats.reasoning_tokens == 5
        assert stats.cache_read_tokens == 1000
        assert stats.cache_write_tokens == 50
        # 四路和**不含 reasoning**：它是 completion 的子集（`ElaChatStats` 文档），
        # 再加一遍就是双计，上下文占用会偏高
        assert stats.total_tokens == 200 + 20 + 1000 + 50
        assert stats.last_activity == 123.0

    def test_skips_messages_without_tokens(self):
        """零 tokens 的助手消息跳过（对齐 ``lastAssistantWithTokens``），但成本仍累计。"""
        older = _assistant(
            1,
            [
                _step(
                    1,
                    ElaChatStats(prompt_tokens=7, completion_tokens=3, total_tokens=10),
                )
            ],
            created_at=1.0,
        )
        newest = _assistant(2, [_step(1, ElaChatStats(cost_usd=0.5))], created_at=2.0)
        stats = ElaChatSessionStats.fromMessages([older, newest])
        assert stats.total_tokens == 10
        # last_activity 取「有 tokens」的那条，而不是时间上最后一条
        assert stats.last_activity == 1.0
        assert stats.total_cost_usd == pytest.approx(0.5)

    def test_falls_back_to_total_tokens_when_details_missing(self):
        """旧数据没有四路明细、只有服务端 ``total_tokens`` 时按其折算。"""
        message = _assistant(1, [_step(1, ElaChatStats(total_tokens=42))])
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.total_tokens == 42
        assert (stats.input_tokens, stats.output_tokens) == (0, 0)

    def test_message_level_stats_without_parts(self):
        """没有分段（如 ``fromDict`` 恢复的消息）时退回消息级 stats。"""
        message = _assistant(
            1,
            stats=ElaChatStats(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            created_at=9.0,
        )
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.total_tokens == 10
        assert stats.last_activity == 9.0

    def test_total_cost_sums_all_messages_once(self):
        with_stats = _assistant(1, stats=ElaChatStats(cost_usd=0.5))
        parts_only = _assistant(2, [_step(1, ElaChatStats(cost_usd=0.25))])
        stats = ElaChatSessionStats.fromMessages([with_stats, parts_only])
        assert stats.total_cost_usd == pytest.approx(0.75)

    def test_percent_needs_limit(self):
        message = _assistant(
            1,
            [
                _step(
                    1,
                    ElaChatStats(prompt_tokens=150_000, total_tokens=150_000),
                )
            ],
        )
        assert ElaChatSessionStats.fromMessages([message]).usage_percent is None
        assert ElaChatSessionStats.fromMessages([message], 200_000).usage_percent == 75
        # 超过上限夹到 100
        assert ElaChatSessionStats.fromMessages([message], 100_000).usage_percent == 100
        # 非法 limit 视为未提供
        assert ElaChatSessionStats.fromMessages([message], -5).usage_percent is None

    def test_non_finite_tokens_are_guarded(self):
        """``inf`` / ``nan`` 词元不能把聚合炸掉（``int(inf)`` -> ``OverflowError``）。"""
        message = _assistant(
            1,
            [
                _step(
                    1,
                    ElaChatStats(
                        prompt_tokens=math.inf,
                        cache_read_tokens=10,
                        total_tokens=10,
                        cost_usd=math.nan,
                    ),
                )
            ],
        )
        stats = ElaChatSessionStats.fromMessages([message], 200_000)
        assert stats.total_tokens == 10
        assert stats.input_tokens == 0
        assert math.isfinite(stats.total_cost_usd)
        assert stats.usage_percent == 0  # 10 / 200000 -> 0.005% -> round 0

    def test_exported_from_package(self):
        import pyqt6_ela_pro

        assert pyqt6_ela_pro.ElaChatSessionStats is ElaChatSessionStats


class TestViewIntegration:
    def test_view_session_stats_and_ring_feed(self, qapp, make):
        """``view.sessionStats()`` 接真实消息 API；同一份口径可直接喂输入区圆环。"""
        chat = make(ElaChatWidget)
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, "hi")
        messageId = view.addMessage(ElaChatRoleType.Assistant, "")
        view.beginStep(messageId)
        view.setStepStats(
            messageId,
            ElaChatStats(
                prompt_tokens=900_000, completion_tokens=1000, total_tokens=901_000
            ),
        )
        stats = view.sessionStats(1_000_000)
        assert (
            stats.message_count,
            stats.user_messages,
            stats.assistant_messages,
        ) == (2, 1, 1)
        assert stats.total_tokens == 901_000
        assert stats.usage_percent == 90

        chat.chatInput().setContextUsage(
            stats.total_tokens, 1_000_000, stats.total_cost_usd
        )
        assert chat.chatInput().contextUsagePercent() == 90

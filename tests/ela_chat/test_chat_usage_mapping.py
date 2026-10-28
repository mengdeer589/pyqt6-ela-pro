"""外部 usage 的四路归一化（``chat/_usage.py``）。

OpenAI / DeepSeek 的 ``prompt_tokens`` **包含**缓存命中；原样连同
``cache_read_tokens`` 一起落库，会让 ``sessionStats().total_tokens`` 与
``stats_cost()`` 把缓存算两遍（上下文圆环偏高、花费偏贵）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from pyqt6_ela_pro.chat import (
    ElaChatMockUsage,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStreamBinder,
    ElaChatTurnJournal,
    ElaChatWidget,
    ModelPricing,
    stats_cost,
)
from pyqt6_ela_pro.chat._usage import stats_from_usage


def _openai_usage(**overrides):
    """OpenAI 形态：``prompt_tokens`` 含 ``cached_tokens``。"""
    values = dict(
        prompt_tokens=1000,
        completion_tokens=100,
        total_tokens=1100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=800),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class _Worker(QObject):
    """journal 只需要这四条信号。"""

    chunkReceived = pyqtSignal(object)
    toolStarted = pyqtSignal(dict)
    toolEnded = pyqtSignal(dict, str)
    statsReady = pyqtSignal(object, float, float)


class TestOpenAIShape:
    def test_prompt_excludes_cached_tokens(self):
        stats = stats_from_usage(_openai_usage())
        assert (stats.prompt_tokens, stats.cache_read_tokens) == (200, 800)
        # 服务端原始总值保持不变
        assert stats.total_tokens == 1100

    def test_deepseek_hit_tokens(self):
        """DeepSeek 的 ``prompt_cache_hit_tokens`` 同样是 prompt 的子集。"""
        usage = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=100,
            total_tokens=1100,
            prompt_cache_hit_tokens=800,
        )
        stats = stats_from_usage(usage)
        assert (stats.prompt_tokens, stats.cache_read_tokens) == (200, 800)

    def test_cache_write_is_deducted(self):
        usage = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            prompt_cache_hit_tokens=60,
            cache_creation_input_tokens=30,
        )
        stats = stats_from_usage(usage)
        assert stats.prompt_tokens == 10
        assert (stats.cache_read_tokens, stats.cache_write_tokens) == (60, 30)

    def test_cache_overflow_is_clamped(self):
        """脏数据（缓存 > prompt）按 prompt 截断，不能把四路和顶爆。"""
        usage = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=1,
            prompt_cache_hit_tokens=999,
        )
        stats = stats_from_usage(usage)
        assert stats.prompt_tokens == 0
        assert stats.cache_read_tokens == 10

    def test_mock_backend_usage_shape(self):
        usage = ElaChatMockUsage(promptTokens=128, completionTokens=96, cachedTokens=64)
        stats = stats_from_usage(usage)
        assert (stats.prompt_tokens, stats.cache_read_tokens) == (64, 64)


class TestAnthropicShape:
    def test_input_tokens_are_already_exclusive(self):
        usage = SimpleNamespace(
            input_tokens=200,
            output_tokens=100,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=50,
        )
        stats = stats_from_usage(usage)
        assert stats.prompt_tokens == 200
        assert stats.completion_tokens == 100
        assert stats.cache_read_tokens == 800
        assert stats.cache_write_tokens == 50
        assert stats.total_tokens == 0  # 服务端没给 total


class TestCanonicalPassthrough:
    def test_ela_stats_is_not_deducted_twice(self):
        canonical = ElaChatStats(
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=1100,
            cache_read_tokens=800,
        )
        stats = stats_from_usage(canonical, ttftMs=120, tps=42)
        assert (stats.prompt_tokens, stats.cache_read_tokens) == (200, 800)
        assert (stats.ttft_ms, stats.tps) == (120.0, 42.0)


class TestSessionAndCost:
    def test_session_total_equals_true_context(self, qapp, make):
        chat = make(ElaChatWidget)
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, "hi")
        messageId = view.addMessage(ElaChatRoleType.Assistant, "")
        view.beginStep(messageId)
        view.setStepStats(messageId, stats_from_usage(_openai_usage()))

        stats = view.sessionStats(1_000_000)
        assert stats.total_tokens == 1100  # 200 + 100 + 800
        assert stats.input_tokens == 200
        assert stats.cache_read_tokens == 800
        assert stats.usage_percent == 0

    def test_stats_cost_does_not_charge_cached_input_twice(self):
        pricing = ModelPricing(input_per_m=3.0, output_per_m=15.0, cache_read_per_m=0.3)
        stats = stats_from_usage(_openai_usage())
        expected = (200 * 3.0 + 100 * 15.0 + 800 * 0.3) / 1_000_000
        assert stats_cost(stats, pricing) == pytest.approx(expected)

    def test_high_cache_hit_context_is_not_doubled(self, qapp, make):
        """下游报告场景：prompt 142466（命中 141696）+ completion 134。"""
        usage = SimpleNamespace(
            prompt_tokens=142_466,
            completion_tokens=134,
            total_tokens=142_600,
            prompt_cache_hit_tokens=141_696,
        )
        chat = make(ElaChatWidget)
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, "hi")
        messageId = view.addMessage(ElaChatRoleType.Assistant, "")
        view.beginStep(messageId)
        view.setStepStats(messageId, stats_from_usage(usage))

        stats = view.sessionStats(262_144)
        assert stats.input_tokens == 770
        assert stats.cache_read_tokens == 141_696
        assert stats.total_tokens == 142_600
        assert stats.usage_percent == 54


class TestIngestionParity:
    def test_binder_and_journal_map_identically(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat)
        messageId = chat.beginAssistantMessage()
        turn = binder.beginTurn()
        binder.stats(_openai_usage(), ttftMs=120, tps=42)
        binder.finish(turn)
        live = chat.chatView().message(messageId).stats

        worker = _Worker()
        journal = ElaChatTurnJournal(messageId=2).begin(1)
        journal.connectWorker(worker)
        worker.statsReady.emit(_openai_usage(), 120.0, 42.0)
        replayed = journal.message().stats

        fields = (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "ttft_ms",
            "tps",
        )
        assert [getattr(live, name) for name in fields] == [
            getattr(replayed, name) for name in fields
        ]
        assert live.prompt_tokens == 200
        assert live.cache_read_tokens == 800
        worker.deleteLater()
        qapp.processEvents()

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
    ElaChatToolCall,
    ElaChatToolStatusType,
    ElaChatWidget,
)


def _assistant(mid, parts=(), created_at=0.0, stats=None, **fields):
    return ElaChatMessage(
        id=mid,
        role=ElaChatRoleType.Assistant,
        created_at=created_at,
        stats=stats,
        parts=tuple(parts),
        **fields,
    )


def _step(step, stats):
    return ElaChatPart(
        id=f"p{step}", kind=ElaChatPartKindType.Stats, stats=stats, step=step
    )


def _tool(step, name="read", status=ElaChatToolStatusType.Done, with_call=True, mid=0):
    call = (
        ElaChatToolCall(id=f"t{mid}-{step}-{name}", name=name, status=status)
        if with_call
        else None
    )
    return ElaChatPart(
        id=f"tool-{mid}-{step}-{name}",
        kind=ElaChatPartKindType.Tool,
        tool_call=call,
        step=step,
    )


def _reasoning(mid, ms):
    return ElaChatPart(
        id=f"r{mid}", kind=ElaChatPartKindType.Reasoning, duration_ms=ms, step=1
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

    def test_context_tokens_helper_excludes_reasoning(self):
        stats = ElaChatStats(
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=1100,
            reasoning_tokens=80,
            cache_read_tokens=800,
            cache_write_tokens=50,
        )
        assert stats.contextTokens() == 1150

    def test_parts_less_message_falls_back_to_message_fields(self):
        """旧格式只有消息级字段：工具与思考耗时要照样统计。"""
        message = _assistant(
            1,
            tool_calls=(
                ElaChatToolCall(
                    id="t1", name="Read", status=ElaChatToolStatusType.Done
                ),
            ),
            reasoning="想",
            reasoning_ms=12.0,
        )
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.tool_calls == 1
        assert stats.tool_rounds == 1
        assert stats.tool_counts == {"read": 1}
        assert stats.reasoning_ms == pytest.approx(12.0)

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


class TestToolStats:
    def test_defaults_when_no_tools(self):
        stats = ElaChatSessionStats.fromMessages([])
        assert (stats.tool_calls, stats.tool_rounds) == (0, 0)
        assert (stats.tool_errors, stats.tool_aborted, stats.tool_unsettled) == (
            0,
            0,
            0,
        )
        assert stats.tool_counts == {}
        assert stats.reasoning_ms == 0.0

    def test_calls_statuses_and_name_counts(self):
        message = _assistant(
            1,
            [
                _tool(1, "read"),
                _tool(1, "Read"),  # 名字大小写归一后并入同一键
                _tool(1, "grep", status=ElaChatToolStatusType.Error),
                _tool(2, "edit", status=ElaChatToolStatusType.Aborted),
                _tool(2, "shell", status=ElaChatToolStatusType.Running),
                _tool(2, "shell", status=ElaChatToolStatusType.Pending),
            ],
        )
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.tool_calls == 6
        assert stats.tool_errors == 1
        assert stats.tool_aborted == 1
        assert stats.tool_unsettled == 2
        assert stats.tool_counts == {"read": 2, "grep": 1, "edit": 1, "shell": 2}
        # done 可由差额推得：6 - 1 - 1 - 2
        assert stats.tool_calls - (
            stats.tool_errors + stats.tool_aborted + stats.tool_unsettled
        ) == 2

    def test_rounds_dedup_by_step_across_messages(self):
        """轮数 = 有工具调用的**步骤数**：同 step 并行多个算一轮、消息内去重。"""
        first = _assistant(1, [_tool(1, "read"), _tool(1, "grep"), _tool(2, "edit")])
        second = _assistant(2, [_tool(1, "read")])
        stats = ElaChatSessionStats.fromMessages([first, second])
        assert stats.tool_calls == 4
        assert stats.tool_rounds == 3  # 2 + 1（两条消息的 step 各自从 1 起）

    def test_unknown_status_and_empty_name(self):
        """未知状态仍计总数；空名字不进分组表（分组表以名为键，空键无意义）。"""
        message = _assistant(
            1,
            [
                _tool(1, "read", status="weird"),
                _tool(1, "", status=ElaChatToolStatusType.Done),
            ],
        )
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.tool_calls == 2
        assert (stats.tool_errors, stats.tool_aborted, stats.tool_unsettled) == (
            0,
            0,
            0,
        )
        assert stats.tool_counts == {"read": 1}

    def test_tool_part_without_call_is_skipped(self):
        """坏数据（工具段缺 ``tool_call``）：不计数、也不占轮数。"""
        message = _assistant(1, [_tool(1, "read", with_call=False), _tool(2, "grep")])
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.tool_calls == 1
        assert stats.tool_rounds == 1
        assert stats.tool_counts == {"grep": 1}

    def test_reasoning_ms_sums_all_messages(self):
        messages = [
            _assistant(1, [_reasoning(1, 250.0), _step(1, ElaChatStats())]),
            _assistant(2, [_reasoning(2, 125.5)]),
        ]
        stats = ElaChatSessionStats.fromMessages(messages)
        assert stats.reasoning_ms == pytest.approx(375.5)

    def test_reasoning_ms_guards_non_finite(self):
        """``inf`` 时长按未知处理（``_as_float`` 归零），不能污染合计。"""
        message = _assistant(1, [_reasoning(1, math.inf), _reasoning(1, 10.0)])
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.reasoning_ms == pytest.approx(10.0)

    def test_tool_fields_do_not_disturb_usage_aggregation(self):
        """新字段与旧口径互不干扰：tokens / 成本 / last_activity 不变。"""
        message = _assistant(
            1,
            [
                _tool(1, "read"),
                _step(
                    1,
                    ElaChatStats(prompt_tokens=100, completion_tokens=10, total_tokens=110),
                ),
            ],
            created_at=5.0,
        )
        stats = ElaChatSessionStats.fromMessages([message])
        assert stats.total_tokens == 110
        assert stats.last_activity == 5.0
        assert stats.tool_calls == 1


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

    def test_view_session_stats_counts_real_tool_calls(self, qapp, make):
        """真实 API 路径：``addToolCall`` / ``setToolCallResult`` 后工具统计到位。"""
        chat = make(ElaChatWidget)
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, "查一下")
        messageId = view.addMessage(ElaChatRoleType.Assistant, "")
        view.beginStep(messageId)
        readId = view.addToolCall(messageId, "read", '{"path": "a.txt"}')
        view.setToolCallResult(messageId, readId, "ok", ok=True)
        grepId = view.addToolCall(messageId, "grep", '{"pattern": "x"}')
        view.setToolCallResult(messageId, grepId, "boom", ok=False)

        stats = view.sessionStats()
        assert stats.tool_calls == 2
        # 同一 step 里并发两个调用算一轮
        assert stats.tool_rounds == 1
        assert stats.tool_counts == {"read": 1, "grep": 1}
        assert stats.tool_errors == 1
        assert stats.tool_unsettled == 0

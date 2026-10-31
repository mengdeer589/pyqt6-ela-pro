"""ElaChatPart 步骤化时间线测试：分段顺序、每步工具面板、步骤统计与快照派生。"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro.chat import (
    ElaChatReasoningStyleType,
    ElaChatBubble,
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatView,
    ElaChatWidget,
    ReasoningBlock,
    StatsBadge,
)
from pyqt6_ela_pro.tooltips import _tooltip_dict


class TestPartModel:
    def test_kind_constants(self):
        assert ElaChatPartKindType.Reasoning == "reasoning"
        assert ElaChatPartKindType.Text == "text"
        assert ElaChatPartKindType.Tool == "tool"
        assert ElaChatPartKindType.Stats == "stats"
        # 合成上下文（steer 回执 / 断流续写标记）、压缩、审批
        assert ElaChatPartKindType.Synthetic == "synthetic"
        assert ElaChatPartKindType.Compaction == "compaction"
        assert ElaChatPartKindType.Permission == "permission"
        assert set(ElaChatPartKindType.All) == {
            "reasoning",
            "text",
            "tool",
            "stats",
            "synthetic",
            "compaction",
            "permission",
            "notice",
        }

    def test_defaults_and_helpers(self):
        part = ElaChatPart(id="p1", kind=ElaChatPartKindType.Text, text="a")
        assert part.status == ElaChatStatusType.Done
        assert part.step == 1
        assert part.tool_call is None
        assert part.stats is None
        assert part.duration_ms == 0.0
        assert part.withText("b").text == "b"
        assert part.withStatus(ElaChatStatusType.Streaming).status == "streaming"
        assert part.withDuration(120).duration_ms == 120.0

    def test_message_with_parts_derives_fields(self):
        tool = ElaChatToolCall(id="t1", name="read")
        stats = ElaChatStats(total_tokens=9)
        parts = (
            ElaChatPart(
                id="r1",
                kind=ElaChatPartKindType.Reasoning,
                text="想",
                duration_ms=300.0,
            ),
            ElaChatPart(id="x1", kind=ElaChatPartKindType.Text, text="正文"),
            ElaChatPart(id="x2", kind=ElaChatPartKindType.Text, text="续"),
            ElaChatPart(id="t1", kind=ElaChatPartKindType.Tool, tool_call=tool, step=2),
            ElaChatPart(id="s1", kind=ElaChatPartKindType.Stats, stats=stats, step=2),
        )
        message = ElaChatMessage(id=1, role=ElaChatRoleType.Assistant).withParts(parts)
        assert message.text == "正文续"
        assert message.reasoning == "想"
        assert message.reasoning_ms == 300.0
        assert message.tool_calls == (tool,)
        assert message.stats is stats
        assert message.stepCount == 2
        assert message.stepParts(2) == [parts[3], parts[4]]
        assert message.part("x1") is parts[1]
        assert message.partsOfKind(ElaChatPartKindType.Text) == [parts[1], parts[2]]


class TestStreamBuffers:
    """流式分片缓冲：在途分片不写回 ``part.text``，落定时才并入。

    契约（完整反转后）：``parts()`` / ``text()`` / ``reasoning()`` 全是
    **纯读取**。``part.text`` 只含已落定内容，因此可安全直接序列化；
    「当前可见全文」由 ``bubble.text()`` / ``partText()`` 给出。
    """

    def test_in_flight_text_not_written_back_to_part(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginText()
        bubble.appendText("第一段")
        bubble.appendText("续")
        # 实时可见全文（含在途）
        assert bubble.text() == "第一段续"
        assert bubble.partText(bubble.parts()[0]) == "第一段续"
        # 落定值仍为空
        assert bubble.parts()[0].text == ""
        # 回合结束后才落定
        bubble.endStream()
        assert bubble.parts()[0].text == "第一段续"
        assert bubble.text() == "第一段续"

    def test_parts_read_is_idempotent(self, qapp, make):
        """读一次与读一百次结果相同 —— 快照可安全重复落库。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginText()
        bubble.appendText("x")
        first = [(p.id, p.status, p.text) for p in bubble.parts()]
        for _ in range(5):
            assert [(p.id, p.status, p.text) for p in bubble.parts()] == first
        assert bubble.parts()[0].text == "", "重复读把在途分片物化进了 part.text"
        bubble.endStream()

    def test_set_text_discards_pending_buffer(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.appendText("旧")
        bubble.setText("新")
        assert bubble.text() == "新"
        assert bubble.parts()[0].text == "新"

    def test_leading_whitespace_does_not_open_text_part(self, qapp, make):
        """纯空白分片不开正文段；首个非空白分片到来时连空白一起开段。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.appendText("\n\n")
        assert [
            part for part in bubble.parts() if part.kind == ElaChatPartKindType.Text
        ] == []
        bubble.appendText("正文")
        bubble.endStream()
        texts = [
            part.text for part in bubble.parts() if part.kind == ElaChatPartKindType.Text
        ]
        assert texts == ["\n\n正文"]

    def test_whitespace_only_stream_leaves_no_text_part(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.appendText("\n\n")
        bubble.endStream()
        assert [
            part for part in bubble.parts() if part.kind == ElaChatPartKindType.Text
        ] == []
        assert bubble.text() == ""

    def test_mid_text_whitespace_is_preserved(self, qapp, make):
        """中段空白照常保留（只有「开段前的空白」被延迟，不能被吞掉）。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.appendText("hello")
        bubble.appendText(" ")
        bubble.appendText("world")
        bubble.endStream()
        assert bubble.text() == "hello world"

    def test_multiple_text_parts_settle_independently(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginText()
        bubble.appendText("A")
        bubble.endText()
        bubble.beginText()
        bubble.appendText("B")
        # 第一段已落定，第二段仍在途
        assert bubble.text() == "AB"
        texts = [
            part.text for part in bubble.parts() if part.kind == ElaChatPartKindType.Text
        ]
        assert texts == ["A", ""]
        bubble.endStream()
        texts = [
            part.text for part in bubble.parts() if part.kind == ElaChatPartKindType.Text
        ]
        assert texts == ["A", "B"]

    def test_reasoning_not_written_back_until_end(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginReasoning()
        bubble.appendReasoning("思考")
        bubble.appendReasoning("续")
        # reasoning() 是纯读取的实时全文；part.text 此刻仍为空
        assert bubble.reasoning() == "思考续"
        reasons = [
            part.text
            for part in bubble.parts()
            if part.kind == ElaChatPartKindType.Reasoning
        ]
        assert reasons == [""]
        bubble.endReasoning(800.0)
        reasons = [
            part.text
            for part in bubble.parts()
            if part.kind == ElaChatPartKindType.Reasoning
        ]
        assert reasons == ["思考续"], "endReasoning 未把缓冲落定进 part.text"
        assert bubble.reasoning() == "思考续"

    def test_reasoning_block_flushes_on_read_and_end(self, qapp, make):
        block = make(ReasoningBlock)
        for chunk in ("a", "b", "c"):
            block.appendText(chunk)
        assert block.text() == "abc"
        block.appendText("d")
        block.end(500)
        # 收起态只保留数据，不把全文灌进 word-wrap 标签（bug #17）
        assert block.text() == "abcd"
        assert block.label().text() == ""
        block.setOpened(True)
        assert "abcd" in block.label().text()


class TestBubbleParts:
    def test_step_timeline_order_and_kinds(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginReasoning()
        bubble.appendReasoning("分析")
        bubble.endReasoning(900)
        bubble.addToolCall("read", '{"path": "a.py"}')
        bubble.beginStep()
        bubble.beginText()
        bubble.appendText("回答")
        stats = ElaChatStats(total_tokens=3)
        bubble.setStepStats(stats)

        kinds = [part.kind for part in bubble.parts()]
        assert kinds == [
            ElaChatPartKindType.Reasoning,
            ElaChatPartKindType.Tool,
            ElaChatPartKindType.Text,
            ElaChatPartKindType.Stats,
        ]
        assert [part.step for part in bubble.parts()] == [1, 1, 2, 2]
        assert bubble.reasoning() == "分析"
        assert bubble.text() == "回答"
        assert bubble.stats() is stats

    def test_multiple_text_parts_keep_viewers(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginText()
        bubble.appendText("第一段")
        bubble.beginText()
        bubble.appendText("第二段")
        texts = [part for part in bubble.parts() if part.kind == ElaChatPartKindType.Text]
        assert len(texts) == 2
        assert bubble.text() == "第一段第二段"
        assert len(bubble.textViewers()) == 2

    def test_end_text_then_viewer_reuses_last_part(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.appendText("内容")
        bubble.endStream()
        assert bubble.markdownViewer() is not None
        texts = [part for part in bubble.parts() if part.kind == ElaChatPartKindType.Text]
        assert len(texts) == 1

    def test_set_text_replaces_last_part(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginText()
        bubble.appendText("旧内容")
        bubble.endText()
        bubble.setText("新内容")
        texts = [part for part in bubble.parts() if part.kind == ElaChatPartKindType.Text]
        assert len(texts) == 1
        assert bubble.text() == "新内容"

    def test_step_tool_panels_isolated_counts(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        first = bubble.addToolCall("read", '{"path": "a"}')
        assert bubble.toolPanel().counts() == (0, 1)
        bubble.setToolCallResult(first, "ok")
        assert bubble.toolPanel().counts() == (1, 1)

        bubble.beginStep()
        second = bubble.addToolCall("shell", '{"command": "ls"}')
        panels = bubble.toolPanels()
        assert len(panels) == 2
        assert panels[0].counts() == (1, 1)
        assert panels[1].counts() == (0, 1)
        assert bubble.toolPanel() is panels[1]

        bubble.setToolCallResult(second, "失败了", ok=False)
        assert panels[1].counts() == (1, 1)
        assert panels[1].title() == "工具调用 (1)"
        assert panels[0].counts() == (1, 1)

    def test_duplicate_tool_call_id_updates_not_appends(self, qapp, make):
        """同一调用 id 重复上报（参数分片）只更新参数，不追加重复分段。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        callId = bubble.addToolCall("read", '{"path": "a"}', toolCallId="dup")
        again = bubble.addToolCall("read", '{"path": "b"}', toolCallId="dup")

        assert (callId, again) == ("dup", "dup")
        assert bubble.toolCallCount() == 1
        calls = bubble.toolCalls()
        assert len(calls) == 1
        assert "b" in calls[0].arguments

    def test_begin_step_empty_noop(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.beginStep() == 1
        bubble.beginText()
        bubble.appendText("x")
        assert bubble.beginStep() == 2
        assert bubble.stepIndex() == 2

    def test_step_stats_footer_merges_by_default(self, qapp, make):
        """默认 footer 模式：原始分步保留，界面只显示最后一个徽标且为汇总。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        first = ElaChatStats(prompt_tokens=1, completion_tokens=2, total_tokens=3)
        second = ElaChatStats(prompt_tokens=4, completion_tokens=5, total_tokens=9)
        bubble.setStepStats(first)
        bubble.beginStep()
        bubble.setStepStats(second)

        stats_parts = [
            part for part in bubble.parts() if part.kind == ElaChatPartKindType.Stats
        ]
        assert len(stats_parts) == 2
        # parts 保留每步原始数字（不汇总）
        assert [part.stats for part in stats_parts] == [first, second]
        badges = [bubble._part_widgets[part.id] for part in stats_parts]
        assert all(isinstance(badge, StatsBadge) for badge in badges)
        # 仅最后一个徽标可见，数值为各步求和
        assert badges[0].isHidden() is True
        assert badges[1].isHidden() is False
        assert badges[1].stats().prompt_tokens == 5
        assert badges[1].stats().completion_tokens == 7
        assert badges[1].stats().total_tokens == 12
        assert bubble.statsBadge() is badges[1]
        assert bubble.stats().total_tokens == 12
        assert bubble.statsMode() == "footer"

        # None 移除当前步骤记录（含内容区徽标），前一步恢复显示
        bubble.setStepStats(None)
        remaining = [
            part.stats for part in bubble.parts() if part.kind == ElaChatPartKindType.Stats
        ]
        assert remaining == [first]
        assert bubble.stats() is first
        assert bubble.statsBadge() is badges[0]
        assert badges[0].isHidden() is False

    def test_stats_mode_steps_shows_each_step(self, qapp, make):
        """steps 模式恢复每步各自显示（服务端原值，不汇总）。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setStatsMode("steps")
        bubble.setStepStats(ElaChatStats(total_tokens=1))
        bubble.beginStep()
        bubble.setStepStats(ElaChatStats(total_tokens=2))

        stats_parts = [
            part for part in bubble.parts() if part.kind == ElaChatPartKindType.Stats
        ]
        badges = [bubble._part_widgets[part.id] for part in stats_parts]
        assert [badge.isHidden() for badge in badges] == [False, False]
        assert [badge.stats().total_tokens for badge in badges] == [1, 2]
        # 快照仍为整轮汇总
        assert bubble.stats().total_tokens == 3

        # 非法值回落 footer
        bubble.setStatsMode("bogus")
        assert bubble.statsMode() == "footer"
        assert badges[0].isHidden() is True
        assert badges[1].stats().total_tokens == 3

    def test_set_parts_builds_stats_badges_lazily(self, qapp, make):
        """历史回放 footer 模式只建最后一个徽标；切 steps 才补齐其余。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        parts = [
            ElaChatPart(
                id=f"s{index}",
                kind=ElaChatPartKindType.Stats,
                status=ElaChatStatusType.Done,
                stats=ElaChatStats(total_tokens=index + 1),
                step=1,
            )
            for index in range(3)
        ]
        assert bubble.setParts(parts) is True
        stats_parts = [
            part for part in bubble.parts() if part.kind == ElaChatPartKindType.Stats
        ]
        badges = [bubble._part_widgets.get(part.id) for part in stats_parts]
        assert sum(isinstance(badge, StatsBadge) for badge in badges) == 1
        assert isinstance(badges[-1], StatsBadge)
        assert bubble.statsBadge() is badges[-1]

        bubble.setStatsMode("steps")
        badges = [bubble._part_widgets.get(part.id) for part in stats_parts]
        assert all(isinstance(badge, StatsBadge) for badge in badges)
        assert [badge.stats().total_tokens for badge in badges] == [1, 2, 3]

    def test_set_parts_restores_text_without_streaming(self, qapp, make):
        """历史正文一次性 setMarkdown，不走流式缓冲。"""
        text = "# 标题\n\n正文 `code`\n\n```python\nprint(1)\n```"
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        assert bubble.setParts(
            [ElaChatPart(id="t1", kind=ElaChatPartKindType.Text, text=text)]
        )
        part = bubble.parts()[0]
        assert part.text == text
        viewer = bubble._part_widgets[part.id]
        assert viewer.toPlainText().strip()
        assert viewer.isStreaming() is False

    def test_stats_mode_none_hides_and_falls_back_duration(self, qapp, make):
        """none 模式不显示徽标，端到端耗时回退到底部 meta。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setStatsMode("none")
        bubble.setStepStats(ElaChatStats(total_tokens=5))
        part = next(p for p in bubble.parts() if p.kind == ElaChatPartKindType.Stats)
        badge = bubble._part_widgets[part.id]

        assert bubble.statsBadge() is None
        assert badge.isHidden() is True
        bubble.setDuration(12300)
        assert "耗时 12.3s" in bubble.meta()._label.text()

        bubble.setStatsMode("footer")
        assert bubble.statsBadge() is badge
        assert bubble.meta().duration() == 0.0

    def test_step_stats_inline_moves_to_step_end(self, qapp, make):
        """统计先到、工具后到时，内容区徽标移到步骤末尾（流式进行中）。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.setStepStats(ElaChatStats(total_tokens=10))
        part = next(p for p in bubble.parts() if p.kind == ElaChatPartKindType.Stats)
        badge = bubble._part_widgets[part.id]
        bubble.addToolCall("read", '{"path": "a"}')

        layout = bubble._parts_layout
        assert layout.itemAt(layout.count() - 1).widget() is badge
        assert bubble.statsBadge() is badge
        assert badge.stats().total_tokens == 10

    def test_end_stream_docks_last_stats_to_footer(self, qapp, make):
        """steps 模式下回合结束时最后一步停靠底部，中间步骤仍在各自步骤末尾。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setStatsMode("steps")
        bubble.beginStream()
        bubble.beginText()
        bubble.appendText("答案")
        bubble.setStepStats(ElaChatStats(total_tokens=5))
        inline_badge = bubble.statsBadge()
        assert inline_badge.parentWidget() is bubble._parts_container

        bubble.beginStep()
        bubble.setStepStats(ElaChatStats(total_tokens=6))
        docked_badge = bubble.statsBadge()
        bubble.endStream()

        assert docked_badge.parentWidget() is bubble._stats_host
        assert bubble._stats_layout.indexOf(docked_badge) == 0
        assert inline_badge.parentWidget() is bubble._parts_container
        # steps 模式不做汇总：各步显示服务端原值
        assert docked_badge.stats().total_tokens == 6
        assert inline_badge.stats().total_tokens == 5

    def test_footer_total_falls_back_to_four_way(self, qapp, make):
        """服务端没给 total_tokens（Anthropic 形态）时，总计用四路和。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setStepStats(
            ElaChatStats(
                prompt_tokens=200,
                completion_tokens=100,
                cache_read_tokens=800,
            )
        )
        assert "总计 1100" in bubble.statsBadge()._label.text()

    def test_end_stream_docks_merged_badge_to_footer(self, qapp, make):
        """footer 模式回合结束后只有一个底部徽标，数值为整轮汇总。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginText()
        bubble.appendText("答案")
        bubble.setStepStats(ElaChatStats(prompt_tokens=1, total_tokens=1))
        bubble.beginStep()
        bubble.setStepStats(ElaChatStats(prompt_tokens=2, total_tokens=2))
        bubble.endStream()

        badge = bubble.statsBadge()
        assert badge.parentWidget() is bubble._stats_host
        assert bubble._stats_layout.indexOf(badge) == 0
        assert badge.stats().prompt_tokens == 3
        assert badge.stats().total_tokens == 3
        hideable = [
            bubble._part_widgets[part.id]
            for part in bubble.parts()
            if part.kind == ElaChatPartKindType.Stats
        ]
        assert hideable[0].isHidden() is True

    def test_begin_text_after_end_stream_keeps_badge_docked(self, qapp, make):
        """回合结束后再追加正文，不把已停靠底部行的整轮徽标拽回时间线。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginText()
        bubble.appendText("答案")
        bubble.setStepStats(ElaChatStats(total_tokens=3))
        bubble.endStream()
        badge = bubble.statsBadge()
        assert badge.parentWidget() is bubble._stats_host

        bubble.beginText()
        bubble.appendText("追加")
        bubble.endText()

        assert badge.parentWidget() is bubble._stats_host

    def test_end_to_end_duration_in_badge_tooltip(self, qapp, make):
        """端到端耗时并入用量行 tooltip（与首字相邻），不再显示可见文本。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginText()
        bubble.appendText("答案")
        bubble.setStepStats(ElaChatStats(total_tokens=5, ttft_ms=120.0, tps=10.0))
        bubble.setDuration(7400)
        bubble.endStream()

        badge = bubble.statsBadge()
        # 徽标在父窗口显示后才会创建 ElaToolTip（隐藏态不建，bug #17）
        bubble.show()
        qapp.processEvents()
        tooltip = badge._label.toolTip()
        assert tooltip.startswith("首字 120 ms")
        assert "端到端 7.4s" in tooltip
        # 悬浮提示走库内 ElaToolTip（不是原生 QToolTip）
        ela_tooltip = _tooltip_dict.get(badge._label)
        assert ela_tooltip is not None
        assert ela_tooltip._text == tooltip
        assert "↑0" in badge._label.text()
        assert "↓0" in badge._label.text()
        assert "总计 5" in badge._label.text()
        # 可见耗时退场（由 tooltip 承载）
        assert bubble.meta().duration() == 0.0
        assert bubble.meta().isHidden()

    def test_badge_without_detail_has_no_empty_tooltip(self, qapp, make):
        """没有可展示明细时不绑空提示气泡（悬停会弹一个纯底板）。"""
        badge = make(StatsBadge)
        badge.setStats(ElaChatStats(total_tokens=8))
        assert badge._label.toolTip() == ""
        assert badge._label not in _tooltip_dict

        badge.setStats(ElaChatStats(total_tokens=8, ttft_ms=90.0))
        assert badge._label in _tooltip_dict
        assert _tooltip_dict[badge._label]._text == "首字 90 ms"

        badge.setStats(None)
        assert badge._label not in _tooltip_dict

    def test_hidden_badge_defers_tooltip_until_shown(self, qapp, make):
        """隐藏的用量徽标不建 ElaToolTip（footer 模式下大部分徽标永不显示）。"""
        host = make(QWidget)
        host.resize(240, 120)
        badge = StatsBadge(host)
        badge.setStats(ElaChatStats(total_tokens=8, ttft_ms=90.0))

        assert badge._label.toolTip() == "首字 90 ms"
        assert badge._label not in _tooltip_dict

        host.show()
        qapp.processEvents()
        assert badge._label in _tooltip_dict
        assert _tooltip_dict[badge._label]._text == "首字 90 ms"

    def test_set_parts_applies_stats_mode_once(self, qapp, make):
        """恢复重放逐段 setStepStats 时只在收尾统一摆一次徽标（bug #17）。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        parts = [
            ElaChatPart(
                id=f"stats-{index}",
                kind=ElaChatPartKindType.Stats,
                status=ElaChatStatusType.Done,
                stats=ElaChatStats(total_tokens=index + 1),
                step=1,
            )
            for index in range(5)
        ]
        calls: list = []
        original = bubble._apply_stats_mode

        def _spy() -> None:
            calls.append(1)
            original()

        bubble._apply_stats_mode = _spy
        assert bubble.setParts(parts) is True
        assert len(calls) == 1, f"setParts 重放触发了 {len(calls)} 次 _apply_stats_mode"

    def test_duration_falls_back_to_meta_without_badge(self, qapp, make):
        """没有用量徽标时，端到端耗时仍显示在底部 meta。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setDuration(12300)
        assert bubble.meta().duration() == 12300.0
        assert "耗时 12.3s" in bubble.meta()._label.text()

    def test_reasoning_resumes_in_same_step(self, qapp, make):
        """同一步骤内正文后又来思考：回到原思考块，不插到正文后面。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginReasoning()
        bubble.appendReasoning("第一段")
        bubble.endReasoning(100)
        bubble.beginText()
        bubble.appendText("正式回复")
        bubble.beginReasoning()
        bubble.appendReasoning("第二段")
        bubble.endReasoning(200)

        assert [part.kind for part in bubble.parts()] == [
            ElaChatPartKindType.Reasoning,
            ElaChatPartKindType.Text,
        ]
        assert bubble.reasoning() == "第一段第二段"
        assert bubble.parts()[0].duration_ms == 300.0
        assert "第二段" in bubble.reasoningBlock().text()

    def test_reasoning_after_step_starts_new_block(self, qapp, make):
        """换步骤后重新开始思考，创建新的思考块。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginReasoning()
        bubble.appendReasoning("第一步")
        bubble.endReasoning(100)
        bubble.beginStep()
        bubble.beginReasoning()
        bubble.appendReasoning("第二步")
        bubble.endReasoning(100)

        reasons = [
            part for part in bubble.parts() if part.kind == ElaChatPartKindType.Reasoning
        ]
        assert len(reasons) == 2
        assert [part.step for part in reasons] == [1, 2]

    def test_tool_lists_across_steps(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        first = bubble.addToolCall("read", '{"path": "a"}')
        bubble.beginStep()
        second = bubble.addToolCall("shell", '{"command": "ls"}')
        calls = bubble.toolCalls()
        assert [call.id for call in calls] == [first, second]
        assert bubble.toolCallCount() == 2
        bubble.clearToolCalls()
        assert bubble.toolCalls() == []
        assert bubble.toolPanels() == []
        assert bubble.toolPanel() is None

    def test_user_bubble_has_no_parts(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "hi")
        assert bubble.parts() == ()
        assert bubble.beginText() is None
        assert bubble.addToolCall("read") == ""
        assert bubble.setStepStats(ElaChatStats(total_tokens=1)) is None


class TestViewParts:
    def test_snapshot_parts_derived(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginReasoning(messageId)
        view.appendReasoning(messageId, "想")
        view.endReasoning(messageId, 500)
        view.addToolCall(messageId, "read", '{"path": "a"}')
        view.beginStep(messageId)
        view.beginText(messageId)
        view.appendText(messageId, "答")
        view.endText(messageId)
        stats = ElaChatStats(total_tokens=7)
        view.setStepStats(messageId, stats)

        message = view.message(messageId)
        assert [part.kind for part in message.parts] == [
            ElaChatPartKindType.Reasoning,
            ElaChatPartKindType.Tool,
            ElaChatPartKindType.Text,
            ElaChatPartKindType.Stats,
        ]
        assert message.reasoning == "想"
        assert message.reasoning_ms == 500.0
        assert message.text == "答"
        assert len(message.tool_calls) == 1
        assert message.stats is stats
        assert message.stepCount == 2

    def test_initial_assistant_text_creates_part(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "**hi**")
        message = view.message(messageId)
        assert len(message.parts) == 1
        assert message.parts[0].kind == ElaChatPartKindType.Text
        assert message.text == "**hi**"
        view.updateMessage(messageId, "**bye**")
        assert view.message(messageId).text == "**bye**"
        assert len(view.message(messageId).parts) == 1

    def test_begin_step_syncs_snapshot(self, qapp, make):
        """切步会结束当前正文段：快照要立刻拿到已落定文本。"""
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(messageId, "第一段")
        view.beginStep(messageId)
        assert view.message(messageId).text == "第一段"

    def test_compat_aliases(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(messageId, "a")
        view.setStepStats(messageId, ElaChatStats(total_tokens=1))
        # 快照 text 是落定值（流式期间为空）；实时文本走 bubble
        assert view.message(messageId).text == ""
        assert view.bubble(messageId).text() == "a"
        assert view.message(messageId).stats.total_tokens == 1
        view.endMessage(messageId)
        assert view.message(messageId).text == "a"

    def test_reasoning_style_applies_to_existing_and_future(self, qapp, make):
        view = make(ElaChatView)
        first = view.addMessage(ElaChatRoleType.Assistant, "hi")
        view.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        second = view.addMessage(ElaChatRoleType.Assistant, "hey")
        assert view.bubble(first).reasoningStyle() == ElaChatReasoningStyleType.Inline
        assert view.bubble(second).reasoningStyle() == ElaChatReasoningStyleType.Inline

    def test_snapshot_stats_merges_steps(self, qapp, make):
        """快照 stats 为整轮汇总，parts 中保留每步原始数字。"""
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(messageId, "答")
        view.setStepStats(
            messageId,
            ElaChatStats(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )
        view.beginStep(messageId)
        view.setStepStats(
            messageId,
            ElaChatStats(prompt_tokens=4, completion_tokens=5, total_tokens=9),
        )

        message = view.message(messageId)
        assert message.stats.prompt_tokens == 5
        assert message.stats.completion_tokens == 7
        assert message.stats.total_tokens == 12
        raw = [
            part.stats for part in message.parts if part.kind == ElaChatPartKindType.Stats
        ]
        assert [(item.prompt_tokens, item.total_tokens) for item in raw] == [
            (1, 3),
            (4, 9),
        ]

    def test_stats_mode_applies_to_existing_and_future(self, qapp, make):
        view = make(ElaChatView)
        first = view.addMessage(ElaChatRoleType.Assistant, "hi")
        view.setStepStats(first, ElaChatStats(total_tokens=1))
        assert view.bubble(first).statsMode() == "footer"

        view.setStatsMode("steps")
        assert view.statsMode() == "steps"
        assert view.bubble(first).statsMode() == "steps"
        second = view.addMessage(ElaChatRoleType.Assistant, "hey")
        assert view.bubble(second).statsMode() == "steps"

        view.setStatsMode("bogus")
        assert view.statsMode() == "footer"
        assert view.bubble(second).statsMode() == "footer"


class TestWidgetSteps:
    def test_step_passthrough(self, qapp, make):
        chat = make(ElaChatWidget)
        messageId = chat.beginAssistantMessage()
        assert chat.chatView().beginStep(messageId) == 1
        chat.chatView().beginText(messageId)
        chat.chatView().appendText(messageId, "A")
        assert chat.chatView().beginStep(messageId) == 2
        chat.chatView().appendText(messageId, "B")
        chat.chatView().setStepStats(messageId, ElaChatStats(total_tokens=2))
        chat.endAssistantMessage()

        message = chat.chatView().message(messageId)
        assert message.text == "AB"
        assert message.stepCount == 2
        assert message.stats.total_tokens == 2
        assert chat.stepCount(messageId) == 2
        assert chat.toolPanels(messageId) == []

    def test_stats_mode_passthrough(self, qapp, make):
        chat = make(ElaChatWidget)
        assert chat.chatView().statsMode() == "footer"
        chat.chatView().setStatsMode("none")
        assert chat.chatView().statsMode() == "none"
        messageId = chat.beginAssistantMessage()
        assert chat.chatView().bubble(messageId).statsMode() == "none"


class TestReasoningReopen:
    def test_reopened_reasoning_part_returns_to_streaming(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.beginReasoning()
        bubble.appendReasoning("第一段")
        bubble.endReasoning(100)
        assert bubble.parts()[0].status == "done"

        bubble.appendReasoning("第二段")
        assert bubble.parts()[0].status == "streaming"

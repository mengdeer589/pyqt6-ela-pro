"""会话 bundle 测试：ElaChatSessionInfo 序列化 + exportSession / importSession。"""

from __future__ import annotations

import json

import pytest

from pyqt6_ela_pro.chat import (
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatSessionInfo,
    ElaChatStats,
    ElaChatToolCall,
    ElaChatView,
    SESSION_SCHEMA_VERSION,
    ElaChatAttachment,
    jsonDumps,
    jsonLoads,
)


def _build_view(qapp, make) -> ElaChatView:
    """搭一份含用户 / 助手（思考 + 正文 + 工具 + 用量 + 附件 + 错误）的历史。"""
    view = make(ElaChatView)
    view.addMessage(ElaChatRoleType.User, "帮我分析目录")
    messageId = view.addMessage(ElaChatRoleType.Assistant, "")
    view.beginReasoning(messageId)
    view.appendReasoning(messageId, "先看目录结构。")
    view.endReasoning(messageId, 500.0)
    view.beginText(messageId)
    view.appendText(messageId, "目录里有 README 与 pyproject。")
    view.endText(messageId)
    callId = view.addToolCall(messageId, "read", '{"path": "README.md"}')
    view.setToolCallResult(messageId, callId, "内容", ok=True)
    view.setStepStats(messageId, ElaChatStats(total_tokens=123))
    view.setMessageAttachments(
        messageId, [ElaChatAttachment(name="a.txt", path="C:/tmp/a.txt", size=3)]
    )
    view.setMessageDuration(messageId, 1500.0)
    view.endMessage(messageId)

    failedId = view.addMessage(ElaChatRoleType.Assistant, "这条出错了")
    view.setMessageError(failedId, "接口超时")
    return view


class TestSessionInfoPersistence:
    def test_round_trip(self, qapp):
        info = ElaChatSessionInfo(
            id="s1",
            title="快速排序",
            created_at=123.5,
            message_count=3,
            work_dir="D:/workspace",
        )
        data = info.toDict()
        assert data == {
            "id": "s1",
            "title": "快速排序",
            "created_at": 123.5,
            "message_count": 3,
            "work_dir": "D:/workspace",
        }
        assert ElaChatSessionInfo.fromDict(data) == info

    def test_from_dict_tolerant(self, qapp):
        info = ElaChatSessionInfo.fromDict(
            {
                "id": 7,
                "message_count": "2",
                "unknown": 1,
                "active": True,  # 旧版本字段：直接忽略，不做迁移
            }
        )
        assert info.id == "7"
        assert info.title == "新话题"
        assert info.message_count == 2
        assert not hasattr(info, "active")
        assert ElaChatSessionInfo.fromDict(None) == ElaChatSessionInfo(id="")
        assert ElaChatSessionInfo.fromDict("x") == ElaChatSessionInfo(id="")


class TestExportSession:
    def test_structure_and_options(self, qapp, make):
        view = _build_view(qapp, make)
        view.setReasoningStyle("inline")
        view.setStatsMode("steps")
        view.setToolGrouping(False)
        view.setAvatarVisible(False)
        view.setUserBubbleMaxWidth(0.5)
        view.setContentMaxWidth(600)

        bundle = view.exportSession(
            session=ElaChatSessionInfo(id="s1", title="历史", message_count=99),
            extra={"model": "deepseek-v4"},
        )

        assert bundle["schema"] == SESSION_SCHEMA_VERSION
        assert bundle["session"]["id"] == "s1"
        assert bundle["session"]["title"] == "历史"
        assert bundle["session"]["message_count"] == view.count()  # 按实际重算
        assert bundle["extra"] == {"model": "deepseek-v4"}
        assert bundle["view"] == {
            "reasoning_style": "inline",
            "stats_mode": "steps",
            "tool_grouping": False,
            "avatar_visible": False,
            "user_bubble_ratio": 0.5,
            "content_max_width": 600,
        }
        assert len(bundle["messages"]) == view.count()
        assert [row["id"] for row in bundle["messages"]] == [
            message.id for message in view.messages()
        ]

    def test_default_session_and_extra(self, qapp, make):
        view = make(ElaChatView)
        bundle = view.exportSession()
        assert bundle["session"]["id"] == ""
        assert bundle["session"]["message_count"] == 0
        assert bundle["messages"] == []
        assert bundle["extra"] is None

        with pytest.raises(TypeError):
            view.exportSession(extra=["x"])
        with pytest.raises(TypeError):
            view.exportSession(session=123)


class TestImportSession:
    def test_bundle_is_json_serializable(self, qapp, make):

        source = _build_view(qapp, make)
        bundle = source.exportSession(
            session=ElaChatSessionInfo(id="s1", title="历史"),
            extra={"model": "deepseek-v4", "nested": {"n": 1}},
        )
        # 库内编解码：装了 orjson 走 orjson，否则标准库（输出同为紧凑 UTF-8）
        text = jsonDumps(bundle)
        again = jsonLoads(text)
        # 与标准库互通：宿主换后端落库的历史仍可读
        assert json.loads(text) == again

        target = make(ElaChatView)
        assert target.importSession(again) == source.count()
        assert [m.toDict() for m in target.messages()] == bundle["messages"]

    def test_replace_restores_ids_and_options(self, qapp, make):
        source = _build_view(qapp, make)
        source.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        source.setStatsMode("none")
        source.setToolGrouping(False)
        source.setAvatarVisible(False)
        source.setUserBubbleMaxWidth(0.5)
        source.setContentMaxWidth(600)
        bundle = source.exportSession(session=ElaChatSessionInfo(id="s1"))
        rows = bundle["messages"]

        target = make(ElaChatView)
        count = target.importSession(bundle)
        assert count == len(rows)
        # id 与分段 id 原样保留、内容逐字段一致
        assert [message.id for message in target.messages()] == [
            row["id"] for row in rows
        ]
        assert [message.toDict() for message in target.messages()] == rows
        # 外观选项一并恢复
        assert target.reasoningStyle() == ElaChatReasoningStyleType.Inline
        assert target.statsMode() == "none"
        assert target.toolGrouping() is False
        assert target.avatarVisible() is False
        assert target.userBubbleMaxWidth() == 0.5
        assert target.contentMaxWidth() == 600
        # 再次导出：消息与外观可完整往返
        again = target.exportSession()
        assert again["messages"] == rows
        assert again["view"] == bundle["view"]

    def test_append_when_clear_false(self, qapp, make):
        source = _build_view(qapp, make)
        bundle = source.exportSession()

        target = make(ElaChatView)
        existing = target.addMessage(ElaChatRoleType.User, "已有消息")
        count = target.importSession(bundle, clear=False)
        assert count == source.count()
        assert target.count() == 1 + count
        ids = [message.id for message in target.messages()]
        assert ids[0] == existing
        assert len(set(ids)) == len(ids)  # 追加时全部重新分配，不撞号
        assert target.messages()[-1].error == "接口超时"

    def test_invalid_bundle_raises(self, qapp, make):
        view = make(ElaChatView)
        with pytest.raises(ValueError):
            view.importSession(None)
        with pytest.raises(ValueError):
            view.importSession("nope")
        with pytest.raises(ValueError):
            view.importSession({"messages": "x"})

    def test_skips_bad_rows_and_missing_sections(self, qapp, make):
        view = make(ElaChatView)
        bundle = {
            "messages": [None, 123, {"id": 1, "role": "user", "text": "有效"}],
        }
        assert view.importSession(bundle) == 1
        assert view.message(1).text == "有效"
        # 缺 view / session 段不报错，也不改当前外观
        view.setStatsMode("steps")
        view.importSession({"messages": []})
        assert view.statsMode() == "steps"

    def test_clear_true_tolerates_id_overlap_with_current(self, qapp, make):
        """F21 回归：``clear=True`` 是整会话替换，与当前消息撞 id 不算冲突。

        旧实现在清空**之前**把「与现有消息撞号」也当坏 bundle，于是「往仍有
        消息的视图里恢复到上次保存状态」会抛 ValueError，必须先手动 clear。
        """
        source = _build_view(qapp, make)
        bundle = source.exportSession()
        rows = bundle["messages"]

        target = make(ElaChatView)
        for row in rows:
            target.addMessageFromDict(row)  # 先塞一份与 bundle 同 id 的消息

        count = target.importSession(bundle)

        assert count == len(rows)
        assert [message.id for message in target.messages()] == [
            row["id"] for row in rows
        ]

    def test_clear_true_still_rejects_in_batch_duplicates(self, qapp, make):
        """批内重复 id 仍是坏 bundle：抛异常且**一条都不落**。"""
        view = make(ElaChatView)
        row = {"id": 7, "role": "user", "text": "重复"}
        with pytest.raises(ValueError):
            view.importSession({"messages": [row, dict(row)]})
        assert view.count() == 0


class TestRestorePreserveIds:
    def test_conflict_raises_without_partial_write(self, qapp, make):
        view = make(ElaChatView)
        view.addMessage(ElaChatRoleType.User, "已有", messageId=5)
        with pytest.raises(ValueError):
            view.restoreMessages(
                [{"id": 5, "role": "user", "text": "撞号"}], preserveIds=True
            )
        assert view.count() == 1
        assert view.message(5).text == "已有"

    def test_duplicate_ids_in_batch_raise(self, qapp, make):
        view = make(ElaChatView)
        row = {"id": 7, "role": "user", "text": "重复"}
        with pytest.raises(ValueError):
            view.restoreMessages([row, dict(row)], preserveIds=True)
        assert view.count() == 0

    def test_preserve_ids_after_clear(self, qapp, make):
        source = _build_view(qapp, make)
        rows = source.exportSession()["messages"]
        view = make(ElaChatView)
        view.addMessage(ElaChatRoleType.User, "将被清空")
        view.clear()
        restored = view.restoreMessages(rows, preserveIds=True)
        assert restored == [row["id"] for row in rows]


class TestRestoreSettlesOpenState:
    """恢复出来的消息不能保留在途态（streaming / running 工具）。"""

    @staticmethod
    def _row(mid, *, status="streaming", call_status="running", error=""):
        part = ElaChatPart(
            id=f"t{mid}",
            kind=ElaChatPartKindType.Tool,
            status="streaming",
            tool_call=ElaChatToolCall(
                id=f"c{mid}",
                name="shell",
                arguments='{"command": "ls"}',
                status=call_status,
            ),
        )
        message = (
            ElaChatMessage(id=mid, role=ElaChatRoleType.Assistant)
            .withParts((part,))
            .withStatus(status)
        )
        if error:
            message = message.withError(error, "Timeout")
        return message.toDict()

    def test_shell_virtual_restore_settles_streaming_status(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        rows = [
            self._row(index + 1, status="streaming" if index == 0 else "done")
            for index in range(100)
        ]
        view.importSession({"schema": 1, "session": {"id": "s"}, "messages": rows})
        qapp.processEvents()

        assert view.message(1).status == "stopped"
        assert view.exportSession()["messages"][0]["status"] == "stopped"

    def test_restore_settles_running_tool_calls(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessageFromDict(self._row(1))
        message = view.message(messageId)
        assert message.tool_calls[0].status == "aborted"
        assert message.parts[0].status == "done"
        card = view.bubble(messageId)._tool_cards["c1"]
        assert card.status() == "aborted"

    def test_error_restore_settles_tool_as_error(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessageFromDict(
            self._row(1, status="error", error="接口超时")
        )
        message = view.message(messageId)
        assert message.status == "error"
        assert message.tool_calls[0].status == "error"

    def test_restore_empty_tool_id_is_normalized(self, qapp, make):
        part = ElaChatPart(
            id="p1",
            kind=ElaChatPartKindType.Tool,
            status="streaming",
            tool_call=ElaChatToolCall(
                id="", name="grep", arguments='{"pattern": "x"}', status="running"
            ),
        )
        row = (
            ElaChatMessage(id=1, role=ElaChatRoleType.Assistant)
            .withParts((part,))
            .withStatus("streaming")
            .toDict()
        )
        view = make(ElaChatView)
        messageId = view.addMessageFromDict(row)
        callId = view.message(messageId).parts[0].id
        assert view.message(messageId).tool_calls[0].id == callId

        view.setToolCallResult(messageId, callId, "命中 3 处", ok=True)
        call = view.message(messageId).tool_calls[0]
        assert call is not None and call.id == callId
        assert call.result == "命中 3 处"
        assert call.status == "done"

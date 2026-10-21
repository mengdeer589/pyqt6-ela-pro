"""回归测试：存储模块的**读路径**（序列化 -> JSON -> 恢复）。

契约：

- 每个数据类都有 ``toDict()`` / ``fromDict()``，输出纯 JSON 类型，可直接
  ``json.dumps(..., allow_nan=False)`` 落库；
- ``fromDict()`` 一律容错：缺字段取默认、多余字段忽略、类型不对就强转、
  ``NaN`` / ``inf`` 归零；
- ``fromDict`` 对助手消息**不信存储里的派生字段**，一律用 ``parts`` 经
  ``withParts()`` 重算；
- 未知 ``kind`` 的分段被**丢弃**（不降级成正文渲染出结构标记）；
- ``ElaChatBubble.setParts()`` 把分段**重放**到增量 API 上，因此恢复出来的
  界面与实时流式逐像素一致（工具归组 / 内联思考行 / 步骤用量徽标都自动正确），
  且**保留原 part.id**；
- id 冲突时 ``addMessageFromDict`` 抛 ValueError，**不静默重号**
  （重号会让后一条按 id 永远取不到）。
"""

from __future__ import annotations

import json

import pytest

from pyqt6_ela_pro.chat import ElaChatWidget
from pyqt6_ela_pro.chat.message import (
    SCHEMA_VERSION,
    ElaChatAttachment,
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)


# ------------------------------------------------------------------ 工具
def _chat(qapp) -> ElaChatWidget:
    chat = ElaChatWidget()
    chat.resize(800, 600)
    chat.show()
    qapp.processEvents()
    return chat


def _dump(data) -> str:
    """落库用的严格 JSON（``allow_nan=False`` 保证一定能写成文件）。"""
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def _load(raw: str):
    return json.loads(raw)


def _sample_parts() -> list:
    return [
        ElaChatPart(
            id="r1",
            kind=ElaChatPartKindType.Reasoning,
            text="先分析一下",
            duration_ms=1234.0,
            step=1,
        ),
        ElaChatPart(
            id="t1", kind=ElaChatPartKindType.Text, text="**结论**：可以。", step=1
        ),
        ElaChatPart(
            id="c1",
            kind=ElaChatPartKindType.Tool,
            tool_call=ElaChatToolCall(
                id="c1", name="read", arguments='{"p":"a"}', result="内容"
            ),
            step=1,
        ),
        ElaChatPart(
            id="c2",
            kind=ElaChatPartKindType.Tool,
            tool_call=ElaChatToolCall(id="c2", name="bash", arguments="ls", result="e"),
            step=2,
        ),
        ElaChatPart(
            id="s1",
            kind=ElaChatPartKindType.Stats,
            stats=ElaChatStats(prompt_tokens=11, total_tokens=42),
            step=2,
        ),
    ]


def _sample_message() -> ElaChatMessage:
    return (
        ElaChatMessage(
            id=7,
            role=ElaChatRoleType.Assistant,
            created_at=1700000000.5,
            title="模型名",
            timestamp="10:00:00",
            duration_ms=1800.0,
        )
        .withParts(_sample_parts())
        .withAttachments([ElaChatAttachment(name="a.png", size=2048, mime="image/png")])
    )


# ------------------------------------------------------------------ 序列化
class TestToDict:
    def test_output_is_strict_json(self):
        data = _sample_message().toDict()
        # allow_nan=False 的 dumps 通过 == 真的能写成文件
        assert json.loads(_dump(data)) == data

    def test_schema_version_present(self):
        assert ElaChatMessage.schemaOf(_sample_message().toDict()) == SCHEMA_VERSION

    def test_message_round_trip_is_exact(self):
        message = _sample_message()
        back = ElaChatMessage.fromDict(_load(_dump(message.toDict())))
        assert back == message, "序列化往返必须逐字段相等"

    def test_every_part_round_trips(self):
        for part in _sample_parts():
            assert ElaChatPart.fromDict(_load(_dump(part.toDict()))) == part

    def test_nested_round_trip(self):
        call = ElaChatToolCall(id="x", name="n", arguments="a", result="r")
        assert ElaChatToolCall.fromDict(_load(_dump(call.toDict()))) == call
        stats = ElaChatStats(prompt_tokens=1, ttft_ms=2.5, tps=3.25)
        assert ElaChatStats.fromDict(_load(_dump(stats.toDict()))) == stats
        att = ElaChatAttachment(name="f", path="/p", size=9, digest="d", mime="m")
        assert ElaChatAttachment.fromDict(_load(_dump(att.toDict()))) == att

    def test_tool_call_id_is_string(self):
        """id 必须是 str —— 混进 int 会在按 id 查找时分叉。"""
        data = {
            "id": 0,
            "role": "assistant",
            "status": "done",
            "parts": [
                {"id": 0, "kind": "tool", "tool_call": {"id": 5, "name": "read"}}
            ],
        }
        part = ElaChatMessage.fromDict(data).parts[0]
        assert isinstance(part.id, str)
        assert isinstance(part.tool_call.id, str)


class TestFromDictTolerance:
    @pytest.mark.parametrize("junk", [None, 0, "", [], "junk", 3.5, True])
    def test_non_dict_yields_default(self, junk):
        assert ElaChatMessage.fromDict(junk).role == ElaChatRoleType.Assistant
        assert ElaChatPart.fromDict(junk) is None
        assert ElaChatStats.fromDict(junk) is None
        assert ElaChatToolCall.fromDict(junk).name == ""

    def test_missing_fields_use_defaults(self):
        message = ElaChatMessage.fromDict({})
        assert message.id == 0
        assert message.role == ElaChatRoleType.Assistant
        assert message.status == ElaChatStatusType.Done
        assert message.parts == ()
        assert message.attachments == ()

    def test_unknown_fields_ignored(self):
        data = _sample_message().toDict()
        data["未来字段"] = {"a": 1}
        data["parts"][0]["未来字段"] = "x"
        assert ElaChatMessage.fromDict(data).parts[0].text == "先分析一下"

    def test_wrong_types_coerced(self):
        data = {
            "schema": "1",
            "id": "7",
            "role": "assistant",
            "duration_ms": "1800.5",
            "created_at": None,
            "parts": [
                {
                    "id": 9,
                    "kind": "text",
                    "text": 12345,
                    "duration_ms": "12.5",
                    "step": "2",
                }
            ],
        }
        message = ElaChatMessage.fromDict(data)
        assert message.id == 7
        assert message.duration_ms == 1800.5
        assert message.created_at == 0.0
        part = message.parts[0]
        assert part.id == "9"
        assert part.text == "12345"
        assert part.duration_ms == 12.5
        assert part.step == 2

    def test_nan_and_inf_neutralised(self):
        data = {
            "id": 1,
            "role": "assistant",
            "duration_ms": float("nan"),
            "parts": [
                {"id": "a", "kind": "text", "text": "t", "duration_ms": float("inf")}
            ],
        }
        message = ElaChatMessage.fromDict(data)
        assert message.duration_ms == 0.0
        assert message.parts[0].duration_ms == 0.0
        # 归零后才可能真的写成 JSON
        _dump(message.toDict())

    def test_bad_enum_falls_back(self):
        data = {
            "id": 1,
            "role": "外星角色",
            "status": "外星状态",
            "parts": [{"id": "a", "kind": "text", "text": "t", "status": "外星状态"}],
        }
        message = ElaChatMessage.fromDict(data)
        assert message.role == ElaChatRoleType.Assistant
        assert message.status == ElaChatStatusType.Done
        assert message.parts[0].status == ElaChatStatusType.Done

    def test_unknown_tool_status_preserved(self):
        """未知工具状态不能谎报成功 —— 宿主重启后可能还要补结果。"""
        data = {"id": "c", "name": "n", "status": "某种未来状态"}
        assert ElaChatToolCall.fromDict(data).status == "某种未来状态"

    @pytest.mark.parametrize(
        "status",
        [
            ElaChatToolStatusType.Pending,
            ElaChatToolStatusType.Running,
            ElaChatToolStatusType.Aborted,
        ],
    )
    def test_unsettled_tool_status_survives_restore(self, qapp, status):
        """恢复不能把「还在跑 / 被中止」悄悄变成「已完成」。"""
        chat = _chat(qapp)
        data = {
            "id": 0,
            "role": "assistant",
            "status": "done",
            "parts": [
                {
                    "id": "c1",
                    "kind": "tool",
                    "tool_call": {
                        "id": "c1",
                        "name": "read",
                        "result": "部分结果",
                        "status": status,
                    },
                }
            ],
        }
        messageId = chat.chatView().addMessageFromDict(data)
        qapp.processEvents()
        call = chat.chatView().message(messageId).tool_calls[0]
        assert call.status == status
        assert call.result == "部分结果"
        chat.deleteLater()
        qapp.processEvents()

    def test_unknown_part_kind_dropped(self):
        """未知 kind 必须丢弃，不能降级成正文把结构标记渲染出来。"""
        data = {
            "id": 1,
            "role": "assistant",
            "parts": [
                {"id": "p1", "kind": "未来类型", "text": "结构标记"},
                {"id": "p2", "kind": "text", "text": "正常"},
            ],
        }
        message = ElaChatMessage.fromDict(data)
        assert [p.id for p in message.parts] == ["p2"]
        assert message.text == "正常"

    def test_derived_fields_recomputed_not_trusted(self):
        """存储里被手改过的派生字段必须被 parts 重算覆盖。"""
        data = _sample_message().toDict()
        data["text"] = "被篡改的正文"
        data["reasoning"] = "被篡改的思考"
        data["stats"] = {"total_tokens": 999999}
        message = ElaChatMessage.fromDict(data)
        assert message.text == "**结论**：可以。"
        assert message.reasoning == "先分析一下"
        assert message.stats.total_tokens == 42

    def test_no_parts_falls_back_to_plain_fields(self):
        """用户消息没有 parts，此时才信存储里的派生字段。"""
        data = {"id": 1, "role": "user", "text": "提问", "reasoning": "x"}
        message = ElaChatMessage.fromDict(data)
        assert message.text == "提问"
        assert message.reasoning == "x"


# ------------------------------------------------------------------ 恢复
class TestRestore:
    def test_full_timeline_restored(self, qapp):
        message = _sample_message()
        chat = _chat(qapp)
        messageId = chat.chatView().addMessageFromDict(_load(_dump(message.toDict())))
        qapp.processEvents()

        back = chat.chatView().message(messageId)
        assert back.role == message.role
        assert back.text == message.text
        assert back.reasoning == message.reasoning
        assert back.reasoning_ms == message.reasoning_ms
        assert back.duration_ms == message.duration_ms
        assert back.title == message.title
        assert back.timestamp == message.timestamp
        assert back.error == message.error
        assert back.created_at == message.created_at
        assert back.attachments == message.attachments
        assert back.tool_calls == message.tool_calls
        assert back.stats == message.stats
        assert back.parts == message.parts
        chat.deleteLater()
        qapp.processEvents()

    def test_error_field_restored(self, qapp):
        chat = _chat(qapp)
        message = _sample_message().withError("收尾报错")
        messageId = chat.chatView().addMessageFromDict(_load(_dump(message.toDict())))
        qapp.processEvents()
        back = chat.chatView().message(messageId)
        assert back.error == "收尾报错"
        assert chat.chatView().bubble(messageId).error() == "收尾报错"
        assert back.status == ElaChatStatusType.Error
        chat.deleteLater()
        qapp.processEvents()

    def test_error_message_settles_unfinished_tools(self, qapp):
        """带 error 的消息恢复时，未结算工具落 ``Error``。

        这与实时路径一致：``bubble.setError()`` 会先 ``_abortStream``，把还
        在跑的工具结算掉（否则界面留下永久转圈的忙碌环）。存储里
        「有 error 且工具仍 running」本身就是矛盾数据，结算掉是对的。
        """
        chat = _chat(qapp)
        data = _sample_message().toDict()
        data["error"] = "半路失败"
        data["parts"][2]["tool_call"]["status"] = ElaChatToolStatusType.Running
        data["parts"][3]["tool_call"]["status"] = ElaChatToolStatusType.Running
        messageId = chat.chatView().addMessageFromDict(data)
        qapp.processEvents()
        calls = chat.chatView().message(messageId).tool_calls
        assert [c.status for c in calls] == [ElaChatToolStatusType.Error] * 2, (
            "带 error 的消息必须结算掉所有未完成工具，否则界面留永久转圈"
        )
        chat.deleteLater()
        qapp.processEvents()

    def test_part_ids_preserved(self, qapp):
        chat = _chat(qapp)
        messageId = chat.chatView().addMessageFromDict(
            _load(_dump(_sample_message().toDict()))
        )
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        assert [p.id for p in bubble.parts()] == ["r1", "t1", "c1", "c2", "s1"]
        chat.deleteLater()
        qapp.processEvents()

    def test_steps_preserved(self, qapp):
        chat = _chat(qapp)
        messageId = chat.chatView().addMessageFromDict(
            _load(_dump(_sample_message().toDict()))
        )
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        assert [p.step for p in bubble.parts()] == [1, 1, 1, 2, 2]
        assert chat.chatView().message(messageId).stepCount == 2
        chat.deleteLater()
        qapp.processEvents()

    def test_context_tools_are_grouped_like_live(self, qapp):
        """恢复出来的工具归组必须与实时流式一致（这是重放式实现的意义）。"""
        chat = _chat(qapp)
        data = {
            "id": 0,
            "role": "assistant",
            "status": "done",
            "parts": [
                {
                    "id": "c1",
                    "kind": "tool",
                    "tool_call": {
                        "id": "c1",
                        "name": "read",
                        "result": "x",
                        "status": "done",
                    },
                },
                {
                    "id": "c2",
                    "kind": "tool",
                    "tool_call": {
                        "id": "c2",
                        "name": "grep",
                        "result": "y",
                        "status": "done",
                    },
                },
                {
                    "id": "s1",
                    "kind": "tool",
                    "tool_call": {
                        "id": "s1",
                        "name": "shell",
                        "result": "z",
                        "status": "error",
                    },
                },
            ],
        }
        messageId = chat.chatView().addMessageFromDict(data)
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        assert len(bubble.toolPanels()) == 1
        kinds = {k: type(v).__name__ for k, v in bubble._tool_cards.items()}
        assert kinds == {
            "c1": "ContextToolGroupCard",
            "c2": "ContextToolGroupCard",
            "s1": "ToolCallCard",
        }
        chat.deleteLater()
        qapp.processEvents()

    def test_restored_parts_all_settled(self, qapp):
        """存储里不该有在途态；万一有，恢复后也不留 streaming。"""
        chat = _chat(qapp)
        data = {
            "id": 0,
            "role": "assistant",
            "status": "done",
            "parts": [
                {"id": "t1", "kind": "text", "text": "a", "status": "streaming"},
                {"id": "r1", "kind": "reasoning", "text": "b", "status": "streaming"},
            ],
        }
        messageId = chat.chatView().addMessageFromDict(data)
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        assert all(p.status != ElaChatStatusType.Streaming for p in bubble.parts())
        assert bubble.hasPendingText() is False
        chat.deleteLater()
        qapp.processEvents()

    def test_user_message_with_attachments(self, qapp):
        chat = _chat(qapp)
        data = {
            "id": 0,
            "role": "user",
            "text": "看这张图",
            "status": "done",
            "attachments": [{"name": "a.png", "size": 2048, "mime": "image/png"}],
        }
        messageId = chat.chatView().addMessageFromDict(data)
        qapp.processEvents()
        message = chat.chatView().message(messageId)
        assert message.text == "看这张图"
        assert len(message.attachments) == 1
        assert message.attachments[0].displaySize == "2.0 KB"
        chat.deleteLater()
        qapp.processEvents()

    def test_message_id_preserved_and_advances_counter(self, qapp):
        chat = _chat(qapp)
        data = _sample_message().toDict()
        data["id"] = 42
        messageId = chat.chatView().addMessageFromDict(_load(_dump(data)))
        qapp.processEvents()
        assert messageId == 42
        # 内部计数器必须跟着推进，否则后续自动分配的 id 会撞车
        assert chat.chatView()._next_id > 42
        chat.deleteLater()
        qapp.processEvents()

    def test_duplicate_id_raises(self, qapp):
        """id 冲突必须报错，不能静默重号（重号 = 后一条按 id 取不到）。"""
        chat = _chat(qapp)
        view = chat.chatView()
        first = {"id": 5, "role": "user", "text": "先来的", "status": "done"}
        second = {"id": 5, "role": "user", "text": "后来的", "status": "done"}
        view.addMessageFromDict(first)
        with pytest.raises(ValueError, match="已被占用"):
            view.addMessageFromDict(second)
        assert len(view.messages()) == 1
        assert view.message(5).text == "先来的"
        chat.deleteLater()
        qapp.processEvents()

    def test_explicit_free_id_allowed(self, qapp):
        chat = _chat(qapp)
        view = chat.chatView()
        view.addMessageFromDict(
            {"id": 5, "role": "user", "text": "a", "status": "done"}
        )
        got = view.addMessageFromDict(
            {"id": 5, "role": "user", "text": "b", "status": "done"}, messageId=9
        )
        assert got == 9
        assert view.message(9).text == "b"
        chat.deleteLater()
        qapp.processEvents()

    def test_restored_message_shows_footer_and_stats_badge(self, qapp):
        """恢复出来的消息，底部行与用量徽标要正常显示。

        判据必须是**消息状态**而不是 ``_stream_ended`` —— ``setParts()`` 从不动
        那个标记，拿它当「回合是否结束」的判据会把恢复出来的徽标全藏掉。
        """
        chat = _chat(qapp)
        view = chat.chatView()
        view.addMessageFromDict(_sample_message().toDict())
        qapp.processEvents()
        bubble = view.bubble(view.messages()[0].id)
        assert bubble.footer().isHidden() is False
        badge = bubble.statsBadge()
        assert badge is not None
        assert badge.isVisibleTo(bubble) is True
        assert badge.parentWidget() is bubble._stats_host, "恢复的整轮徽标要停靠底部行"
        chat.deleteLater()
        qapp.processEvents()

    def test_restored_message_keeps_status(self, qapp):
        """消息级 status 也要还原：被停止 / 出错的历史不能显示成 Done。"""
        chat = _chat(qapp)
        view = chat.chatView()
        mid = view.addMessageFromDict(
            {
                "id": 9,
                "role": "assistant",
                "status": "stopped",
                "parts": [
                    {"id": "p1", "kind": "text", "text": "半截回答", "status": "done"}
                ],
            }
        )
        qapp.processEvents()
        assert view.message(mid).status == "stopped"
        assert view.bubble(mid).status() == "stopped"
        chat.deleteLater()
        qapp.processEvents()

    def test_restore_messages_batch(self, qapp):
        chat = _chat(qapp)
        rows = [
            {"id": 1, "role": "user", "text": "问一", "status": "done"},
            _sample_message().toDict(),
            {"id": 3, "role": "user", "text": "问二", "status": "done"},
        ]
        ids = chat.chatView().restoreMessages(rows)
        qapp.processEvents()
        messages = chat.chatView().messages()
        assert len(messages) == len(ids) == 3
        assert [m.role for m in messages] == [
            ElaChatRoleType.User,
            ElaChatRoleType.Assistant,
            ElaChatRoleType.User,
        ]
        assert messages[0].text == "问一"
        assert messages[1].text == _sample_message().text
        assert messages[2].text == "问二"
        chat.deleteLater()
        qapp.processEvents()

    def test_restore_messages_renumbers_ids(self, qapp):
        """批量恢复重新分配 id，避开与已有消息的冲突。"""
        chat = _chat(qapp)
        view = chat.chatView()
        view.addMessage("user", "已存在")
        ids = view.restoreMessages(
            [{"id": 1, "role": "user", "text": "a", "status": "done"}]
        )
        assert ids[0] != 1
        assert len(view.messages()) == 2
        chat.deleteLater()
        qapp.processEvents()

    def test_set_parts_rejects_streaming(self, qapp):
        chat = _chat(qapp)
        messageId = chat.beginAssistantMessage()
        bubble = chat.chatView().bubble(messageId)
        assert bubble.setParts(_sample_parts()) is False, "流式期间不能重建时间线"
        chat.endAssistantMessage(messageId)
        qapp.processEvents()
        chat.deleteLater()
        qapp.processEvents()

    def test_set_parts_rejects_user_message(self, qapp):
        chat = _chat(qapp)
        messageId = chat.sendUserMessage("hi")
        qapp.processEvents()
        assert chat.chatView().bubble(messageId).setParts(_sample_parts()) is False
        chat.deleteLater()
        qapp.processEvents()

    def test_set_parts_twice_replaces_cleanly(self, qapp):
        """重复 setParts 不能留下上一次的控件（工具面板是真实控件）。"""
        chat = _chat(qapp)
        messageId = chat.addMessage("assistant", "")
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        assert bubble.setParts(_sample_parts()) is True
        first_panels = len(bubble.toolPanels())
        assert bubble.setParts(_sample_parts()) is True
        assert len(bubble.toolPanels()) == first_panels, (
            "重复 setParts 残留了上一次的步骤面板"
        )
        assert [p.id for p in bubble.parts()] == ["r1", "t1", "c1", "c2", "s1"]
        chat.deleteLater()
        qapp.processEvents()

    def test_set_parts_keeps_one_panel_per_step(self, qapp):
        """跨步骤重放必须与 beginStep 一致收口工具分组与当前面板。"""
        chat = _chat(qapp)
        messageId = chat.addMessage("assistant", "")
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        # 两步各一个上下文工具（分组卡）+ 一个普通工具（独立卡）
        parts = [
            ElaChatPart(
                id="r1",
                kind=ElaChatPartKindType.Tool,
                tool_call=ElaChatToolCall(
                    id="c1", name="read", arguments='{"p":"a"}', result="内容"
                ),
                step=1,
            ),
            ElaChatPart(
                id="r2",
                kind=ElaChatPartKindType.Tool,
                tool_call=ElaChatToolCall(
                    id="c2", name="grep", arguments="x", result="命中"
                ),
                step=2,
            ),
            ElaChatPart(
                id="r3",
                kind=ElaChatPartKindType.Tool,
                tool_call=ElaChatToolCall(id="c3", name="bash", arguments="ls"),
                step=3,
            ),
        ]
        assert bubble.setParts(parts) is True
        panels = bubble.toolPanels()
        assert len(panels) == 3, "后续步骤的工具并进了上一步的面板"
        assert [p.toolLayout().count() for p in panels] == [1, 1, 1]
        # 分组卡按步分开：read 与 grep 不在同一张卡里
        assert [
            c.name for c in panels[0].toolLayout().itemAt(0).widget().toolCalls()
        ] == ["read"]
        assert [
            c.name for c in panels[1].toolLayout().itemAt(0).widget().toolCalls()
        ] == ["grep"]
        # 收尾收口：分组卡标题必须是「已探索」（否则恢复出来停在「正在探索」）
        assert panels[0].toolLayout().itemAt(0).widget().title() == "已探索"
        assert panels[1].toolLayout().itemAt(0).widget().title() == "已探索"
        chat.deleteLater()
        qapp.processEvents()

    def test_set_parts_does_not_leak_current_stats_across_steps(self, qapp):
        """重放后当前用量分段不得停在旧步骤（恢复后继续跑会覆盖上一轮数据）。"""
        chat = _chat(qapp)
        messageId = chat.addMessage("assistant", "")
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        assert (
            bubble.setParts(
                [
                    ElaChatPart(
                        id="s1",
                        kind=ElaChatPartKindType.Stats,
                        stats=ElaChatStats(prompt_tokens=11, total_tokens=42),
                        step=1,
                    ),
                    ElaChatPart(
                        id="t2",
                        kind=ElaChatPartKindType.Tool,
                        tool_call=ElaChatToolCall(id="c2", name="bash", arguments="ls"),
                        step=2,
                    ),
                ]
            )
            is True
        )
        # 落在第 2 步（没有用量分段）时，当前用量分段必须为空而不是停在第 1 步
        assert bubble.stepIndex() == 2
        assert bubble._current_stats_id is None
        chat.deleteLater()
        qapp.processEvents()


class TestLiveRoundTrip:
    def test_stream_then_restore_equals_live(self, qapp):
        """端到端：真实流式跑一轮 -> 落库 -> 新组件恢复 -> 与原消息逐字段相等。"""
        chat = _chat(qapp)
        messageId = chat.beginAssistantMessage()
        chat.chatView().beginReasoning(messageId)
        for chunk in ("分析", "中"):
            chat.chatView().appendReasoning(messageId, chunk)
        chat.chatView().appendText(messageId, "**结论**：可以这样做。")
        callId = chat.chatView().addToolCall(messageId, "read", '{"p":"a.py"}')
        chat.chatView().setToolCallResult(messageId, callId, "文件内容", ok=True)
        failId = chat.chatView().addToolCall(messageId, "bash", "ls")
        chat.chatView().setToolCallResult(messageId, failId, "boom", ok=False)
        chat.chatView().setStepStats(
            messageId, ElaChatStats(prompt_tokens=11, total_tokens=42)
        )
        chat.chatView().setMessageDuration(messageId, 1800.0)
        chat.endAssistantMessage(messageId)
        qapp.processEvents()
        live = chat.chatView().message(messageId)

        fresh = _chat(qapp)
        restored_id = fresh.chatView().addMessageFromDict(_load(_dump(live.toDict())))
        qapp.processEvents()
        back = fresh.chatView().message(restored_id)

        assert back.text == live.text
        assert back.reasoning == live.reasoning
        assert back.reasoning_ms == live.reasoning_ms
        assert back.duration_ms == live.duration_ms
        assert back.tool_calls == live.tool_calls
        assert back.stats == live.stats
        assert back.parts == live.parts
        assert [p.id for p in back.parts] == [p.id for p in live.parts]

        chat.deleteLater()
        fresh.deleteLater()
        qapp.processEvents()

    def test_restore_keeps_one_panel_per_step(self, qapp):
        """端到端：多步骤消息恢复后工具面板数与实时一致。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = view.beginMessage("assistant")
        for name, callId in (("read", "c1"), ("grep", "c2")):
            view.beginStep(messageId)
            view.addToolCall(messageId, name, "{}", callId)
            view.setToolCallResult(messageId, callId, "ok")
        view.endMessage(messageId)
        qapp.processEvents()
        live_panels = view.bubble(messageId).toolPanels()

        fresh = _chat(qapp)
        restored_id = fresh.chatView().addMessageFromDict(
            _load(_dump(view.message(messageId).toDict()))
        )
        qapp.processEvents()
        back_panels = fresh.chatView().bubble(restored_id).toolPanels()

        assert len(live_panels) == 2
        assert len(back_panels) == len(live_panels)

        chat.deleteLater()
        fresh.deleteLater()
        qapp.processEvents()

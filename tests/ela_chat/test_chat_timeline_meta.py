"""时间线通知 / 重试 / 活动行 / 密度 / 消息身份（M0 + M1）。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatDetailPlacementType,
    ElaChatDetailSection,
    ElaChatMention,
    ElaChatMessage,
    ElaChatNoticeType,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatTimelineDetail,
    ElaChatToolCall,
    ElaChatView,
)


def _assistant_with_notice(view: ElaChatView, text: str = "答") -> tuple[int, str]:
    message_id = view.beginMessage(ElaChatRoleType.Assistant)
    view.beginText(message_id)
    view.appendText(message_id, text)
    part_id = view.addNotice(
        message_id, ElaChatNoticeType.ModelSwitched, "已切换模型", "deepseek-v4"
    )
    return message_id, part_id


class TestNoticeModel:
    def test_part_roundtrip(self):
        part = ElaChatPart(
            id="n1",
            kind=ElaChatPartKindType.Notice,
            text="已切换模型",
            notice_type=ElaChatNoticeType.ModelSwitched,
            detail="deepseek-v4",
        )
        restored = ElaChatPart.fromDict(part.toDict())
        assert restored == part
        assert restored.notice_type == "model-switched"
        assert restored.detail == "deepseek-v4"

    def test_notice_text_not_in_message_text(self):
        part = ElaChatPart(
            id="n1",
            kind=ElaChatPartKindType.Notice,
            text="已切换模型",
        )
        message = ElaChatMessage(id=1, role=ElaChatRoleType.Assistant).withParts(
            (part, ElaChatPart(id="t1", kind=ElaChatPartKindType.Text, text="正文"))
        )
        assert message.text == "正文"


class TestMentionModel:
    def test_roundtrip_and_invalid(self):
        mention = ElaChatMention(start=2, end=6, kind="file")
        assert mention.isValid
        assert ElaChatMention.fromDict(mention.toDict()) == mention
        assert not ElaChatMention(start=6, end=2).isValid

    def test_message_roundtrip(self):
        message = ElaChatMessage(
            id=1,
            role=ElaChatRoleType.User,
            text="看 @a.py",
        ).withMentions([ElaChatMention(start=2, end=6, kind="file")])
        message = message.withIdentity("coder", "m1", "high")
        restored = ElaChatMessage.fromDict(message.toDict())
        assert restored.agent == "coder"
        assert restored.model == "m1"
        assert restored.model_variant == "high"
        assert restored.mentions == (ElaChatMention(start=2, end=6, kind="file"),)

    def test_invalid_mentions_dropped(self):
        message = ElaChatMessage(id=1, role=ElaChatRoleType.User).withMentions(
            [ElaChatMention(start=5, end=1), {"start": 0, "end": 2, "kind": "agent"}]
        )
        assert message.mentions == (ElaChatMention(start=0, end=2, kind="agent"),)


class TestToolMetadata:
    def test_roundtrip(self):
        call = ElaChatToolCall(
            id="t1",
            name="edit",
            metadata={"files": [{"file": "a.py", "additions": 2}]},
        )
        restored = ElaChatToolCall.fromDict(call.toDict())
        assert restored.metadata == call.metadata
        assert restored.withResult("ok").metadata == call.metadata

    def test_bad_metadata_becomes_empty(self):
        restored = ElaChatToolCall.fromDict(
            {"id": "t", "name": "x", "metadata": ["not", "a", "dict"]}
        )
        assert restored.metadata == {}


class TestTimelineDetailModel:
    def test_defaults_and_roundtrip(self):
        detail = ElaChatTimelineDetail()
        assert detail.thinking.placement == ElaChatDetailPlacementType.Collapsed
        restored = ElaChatTimelineDetail.fromDict(detail.toDict())
        assert restored == detail

    def test_section_validation(self):
        try:
            ElaChatDetailSection(placement="nope")
        except ValueError:
            pass
        else:
            raise AssertionError("非法 placement 应抛 ValueError")

    def test_dict_coercion(self):
        view = ElaChatView()
        view.setTimelineDetail({"thinking": {"placement": "hidden"}})
        assert view.timelineDetail().thinking.hidden
        assert view.timelineDetail().tools.placement == "collapsed"
        view.deleteLater()


class TestTimelineWidgets:
    def test_add_notice_and_snapshot(self, qapp, make):
        view = make(ElaChatView)
        message_id, part_id = _assistant_with_notice(view)
        assert part_id
        message = view.message(message_id)
        assert message is not None
        notice = message.part(part_id)
        assert notice is not None
        assert notice.kind == ElaChatPartKindType.Notice
        assert notice.text == "已切换模型"

    def test_activity_row(self, qapp, make):
        view = make(ElaChatView)
        view.setActivity("正在运行命令…")
        assert view.activity() == "正在运行命令…"
        assert view._activity_row is not None
        assert not view._activity_row.isHidden()
        view.setActivity("")
        assert view.activity() == ""
        assert view._activity_row.isHidden()

    def test_retry_state(self, qapp, make):
        view = make(ElaChatView)
        message_id = view.beginMessage(ElaChatRoleType.Assistant)
        view.setRetry(message_id, 2, "限流", 0)
        assert view.retryState(message_id) == (2, "限流", 0.0)
        bubble = view.bubble(message_id)
        assert bubble is not None
        assert bubble.retryState() == (2, "限流", 0.0)
        view.clearRetry(message_id)
        assert view.retryState(message_id) is None
        assert bubble.retryState() == (0, "", 0.0)

    def test_retry_card_dark_theme_colors(self, qapp, make):
        from PyQt6ElaWidgetTools import ElaThemeType, eTheme

        from pyqt6_ela_pro.chat._theme import text_color

        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            view = make(ElaChatView)
            message_id = view.beginMessage(ElaChatRoleType.Assistant)
            view.setRetry(message_id, 2, "限流", 0)
            bubble = view.bubble(message_id)
            card = bubble._retry_card
            assert card is not None
            assert (
                card._message_label.textColor().name()
                == text_color(ElaThemeType.ThemeMode.Dark).name()
            )
        finally:
            eTheme.setThemeMode(previous)

    def test_message_identity(self, qapp, make):
        view = make(ElaChatView)
        message_id = view.addMessage(ElaChatRoleType.User, "你好")
        view.setMessageIdentity(message_id, "coder", "m1", "high")
        message = view.message(message_id)
        assert message is not None
        assert (message.agent, message.model, message.model_variant) == (
            "coder",
            "m1",
            "high",
        )
        bubble = view.bubble(message_id)
        assert bubble is not None
        assert bubble.identity() == ("coder", "m1", "high")

    def test_density_hides_and_reopens(self, qapp, make):
        view = make(ElaChatView)
        message_id = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginReasoning(message_id)
        view.appendReasoning(message_id, "想一想")
        view.addToolCall(message_id, "read", '{"path":"a.py"}')
        view.endMessage(message_id)
        view.setTimelineDetail(
            {
                "thinking": {"placement": "hidden"},
                "tools": {"placement": "collapsed"},
            }
        )
        bubble = view.bubble(message_id)
        assert bubble is not None
        thinking = [
            part.id
            for part in bubble.parts()
            if part.kind == ElaChatPartKindType.Reasoning
        ]
        assert thinking
        widget = bubble._part_widgets.get(thinking[0])
        assert widget is not None
        assert widget.isHidden()
        view.setTimelineDetail(
            {
                "thinking": {"placement": "expanded"},
                "tools": {"placement": "expanded"},
            }
        )
        assert not widget.isHidden()

    def test_disclosure_survives_session_roundtrip(self, qapp, make):
        view = make(ElaChatView)
        message_id = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginReasoning(message_id)
        view.appendReasoning(message_id, "想一想")
        view.endMessage(message_id)
        part_id = view.message(message_id).parts[0].id
        view.setPartExpanded(part_id, True)
        bundle = view.exportSession()
        other = make(ElaChatView)
        other.importSession(bundle)
        assert other.partExpanded(part_id) is True

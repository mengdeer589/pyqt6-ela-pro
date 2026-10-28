"""等待首个 token（TTFT）骨架的显隐契约。

骨架是 ``ElaShimmer``，只在「流式中、还没有任何分段、也还没收到首个输出」
时出现；它不是 ``ElaChatPart``，不进 ``parts`` / 导出 / journal。历史虚拟化
占位（``DeferredPlaceholder``）刻意保持零子控件，不在这里换成 shimmer 控件。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from pyqt6_ela_pro.chat import (
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatView,
)
from pyqt6_ela_pro.chat._theme import base_color
from pyqt6_ela_pro.ela_shimmer import ElaShimmer
from PyQt6ElaWidgetTools import eTheme

_WAITING_NAME = "ElaChatWaitingShimmer"


def _view(qapp, make) -> ElaChatView:
    view = make(ElaChatView)
    view.resize(520, 360)
    view.show()
    qapp.processEvents()
    return view


def _shimmer(widget):
    return widget.findChild(ElaShimmer, _WAITING_NAME)


class TestWaitingPlaceholderVisibility:
    def test_shown_before_first_token(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        qapp.processEvents()

        shimmer = _shimmer(view.bubble(mid))
        assert shimmer is not None
        assert shimmer.isHidden() is False
        assert shimmer.isAnimationRunning() is True
        assert shimmer.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert not view.message(mid).parts

    def test_canvas_matches_message_surface(self, qapp, make):
        """骨架底色跟消息区（BasicPress）走，不是 WindowBase。"""
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))
        assert (
            shimmer._canvas_color().name() == base_color(eTheme.getThemeMode()).name()
        )

    def test_whitespace_chunks_keep_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.appendText(mid, "\n\n")
        view.appendText(mid, "   ")
        assert shimmer.isHidden() is False
        assert not view.message(mid).parts

        view.appendText(mid, "答")
        assert shimmer.isHidden() is True
        assert [part.kind for part in view.message(mid).parts] == [
            ElaChatPartKindType.Text
        ]

    def test_reasoning_hides_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.beginReasoning(mid)
        assert shimmer.isHidden() is True

    def test_tool_call_hides_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.addToolCall(mid, "read", {"path": "README.md"}, "call-1")
        assert shimmer.isHidden() is True

    def test_step_stats_hides_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.setStepStats(mid, ElaChatStats(prompt_tokens=1, completion_tokens=1))
        assert shimmer.isHidden() is True

    def test_steer_notice_hides_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.addSteerNotice(mid, "继续")
        assert shimmer.isHidden() is True

    def test_compaction_hides_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.beginCompaction(mid)
        assert shimmer.isHidden() is True

    def test_end_without_content_hides_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.endMessage(mid)
        assert shimmer.isHidden() is True
        assert not view.message(mid).parts

    def test_error_hides_waiting(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))

        view.setMessageError(mid, "请求失败", "RateLimit")
        assert shimmer.isHidden() is True

    def test_hidden_shimmer_stops_animation(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        shimmer = _shimmer(view.bubble(mid))
        assert shimmer.isAnimationRunning() is True

        view.appendText(mid, "答")
        assert shimmer.isHidden() is True
        assert shimmer.isAnimationRunning() is False


class TestWaitingPlaceholderLifetime:
    def test_non_streaming_message_has_no_shimmer(self, qapp, make):
        view = _view(qapp, make)
        mid = view.addMessage(ElaChatRoleType.Assistant, "历史回答")
        assert _shimmer(view.bubble(mid)) is None

    def test_restored_session_has_no_shimmer(self, qapp, make):
        source = _view(qapp, make)
        mid = source.beginMessage(ElaChatRoleType.Assistant)
        source.appendText(mid, "已结束的回答")
        source.endMessage(mid)
        bundle = source.exportSession()

        restored = _view(qapp, make)
        restored.importSession(bundle)
        assert restored.count() == 1
        assert restored.findChildren(ElaShimmer) == []

    def test_view_switch_controls_existing_and_new_bubbles(self, qapp, make):
        view = _view(qapp, make)
        view.setWaitingPlaceholderEnabled(False)
        assert view.waitingPlaceholderEnabled() is False

        mid = view.beginMessage(ElaChatRoleType.Assistant)
        bubble = view.bubble(mid)
        assert _shimmer(bubble) is None

        view.setWaitingPlaceholderEnabled(True)
        shimmer = _shimmer(bubble)
        assert shimmer is not None
        assert shimmer.isHidden() is False

        view.setWaitingPlaceholderEnabled(False)
        assert shimmer.isHidden() is True

    def test_shimmer_is_not_a_part(self, qapp, make):
        view = _view(qapp, make)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        assert _shimmer(view.bubble(mid)) is not None

        view.appendText(mid, "答案")
        assert [part.kind for part in view.message(mid).parts] == [
            ElaChatPartKindType.Text
        ]
        bundle = view.exportSession()
        assert bundle["messages"][0]["parts"][0]["kind"] == ElaChatPartKindType.Text
        assert "waiting_placeholder_enabled" not in bundle["view"]

"""多话题页（架构 B：一话题一 widget）的切换 / 隔离 / 归档恢复。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatReasoningStyleType, ElaChatRoleType
from pyqt6_ela_pro.example.chat_session_page import ChatSessionPage


def _page(qapp) -> ChatSessionPage:
    page = ChatSessionPage()
    page.show()
    qapp.processEvents()
    return page


def _topic(page: ChatSessionPage, index: int) -> str:
    return list(page._sessions)[index]


def _answers(page: ChatSessionPage, topicId: str) -> list:
    return [message.text for message in page._pages[topicId].chat.chatView().messages()]


class TestTopicIsolation:
    def test_each_topic_has_its_own_view_and_draft(self, qapp):
        """一话题一 widget：消息、草稿互不影响（不需要宿主搬运编辑态）。"""
        page = _page(qapp)
        first = _topic(page, 0)
        second = page._createTopic(activate=True)
        qapp.processEvents()

        page._pages[first].chat.addMessage(ElaChatRoleType.User, "话题一的消息")
        page._pages[second].chat.addMessage(ElaChatRoleType.User, "话题二的消息")
        page._pages[first].chat.chatInput().setText("话题一的草稿")
        qapp.processEvents()

        assert _answers(page, first) == ["话题一的消息"]
        assert _answers(page, second) == ["话题二的消息"]
        # 草稿各留各的：切过去不会把上一条草稿带过去
        assert page._pages[second].chat.chatInput().text() == ""
        assert page._stack.currentWidget() is page._pages[second].container

        page._activateTopic(first)
        qapp.processEvents()
        assert page._pages[first].chat.chatInput().text() == "话题一的草稿"
        assert page._stack.currentWidget() is page._pages[first].container
        page.deleteLater()
        qapp.processEvents()

    def test_generation_keeps_running_when_switching_away(self, qapp):
        """切页不中止生成：隐藏的话题继续跑自己的回合（架构 B 的主要理由）。"""
        page = _page(qapp)
        first = _topic(page, 0)
        topic = page._pages[first]
        assert topic.binder.startTurn("一边生成一边切走") is not None

        second = page._createTopic(activate=True)
        qapp.processEvents()

        assert page._stack.currentWidget() is page._pages[second].container
        assert topic.binder.isOpen() is True  # 旧话题的回合还在
        assert topic.chat.isGenerating() is True
        page.deleteLater()
        qapp.processEvents()


class TestArchiveAndRestore:
    def test_archive_then_restore_round_trip(self, qapp):
        """归档 = exportSession + 销毁页面 + 移除标签；恢复 = 重建 + importSession + 草稿。"""
        page = _page(qapp)
        topicId = _topic(page, 0)
        chat = page._pages[topicId].chat
        chat.addMessage(ElaChatRoleType.User, "归档前的问题")
        chat.chatInput().setText("没发出去的草稿")
        qapp.processEvents()

        assert page._archiveTopic(topicId) is True
        assert topicId not in page._pages  # 页面已销毁
        assert topicId not in page._tab_ids  # 标签已移除
        bundle = page._bundles[topicId]
        assert len(bundle.get("messages", [])) == 1
        assert bundle["extra"]["draft"] == "没发出去的草稿"

        assert page._restoreTopic(topicId) is True
        qapp.processEvents()

        restored = page._pages[topicId]
        assert _answers(page, topicId) == ["归档前的问题"]
        assert restored.chat.chatInput().text() == "没发出去的草稿"
        assert page._stack.currentWidget() is restored.container
        assert page._tabs.currentIndex() == page._tab_ids.index(topicId)
        page.deleteLater()
        qapp.processEvents()

    def test_archive_aborts_turn_so_late_chunks_cannot_land(self, qapp):
        """销毁页面前 abortTurn：回合作废后，迟到的分片无处可落（不污染消息）。"""
        page = _page(qapp)
        topicId = _topic(page, 0)
        topic = page._pages[topicId]
        assert topic.binder.startTurn("归档时还在生成") is not None
        messageId = topic.chat.streamingMessageId()
        text_before = topic.chat.chatView().message(messageId).text

        page._archiveTopic(topicId)
        # 归档之后后端 / 宿主再塞分片：回合已关（isOpen() False），binder 一律忽略
        topic.binder.stream("迟到的分片")

        assert topic.binder.isOpen() is False
        assert topic.chat.isGenerating() is False
        assert topic.chat.chatView().message(messageId).text == text_before
        page.deleteLater()
        qapp.processEvents()

    def test_new_topic_button_from_input_creates_and_switches(self, qapp):
        """输入区内置「新建话题」按钮 → 宿主建新话题并切过去。"""
        page = _page(qapp)
        first = _topic(page, 0)
        page._pages[first].chat.chatInput().newTopicButton().click()
        qapp.processEvents()

        assert len(page._sessions) == 2
        second = _topic(page, 1)
        assert page._stack.currentWidget() is page._pages[second].container
        assert page._tabs.currentIndex() == 1  # 标签栏选中的就是新话题
        assert page._tabs.tabText(1).startswith(page._sessions[second].title)
        page.deleteLater()
        qapp.processEvents()

    def test_tab_close_archives_topic(self, qapp):
        """标签上的关闭键 = 归档（页面销毁、标签移除、可恢复）。"""
        page = _page(qapp)
        first = _topic(page, 0)
        page._createTopic(activate=True)
        qapp.processEvents()
        assert page._tabs.count() == 2

        page._tabs.tabCloseRequested.emit(1)  # 模拟点关闭键

        assert len(page._tab_ids) == 1
        assert page._tabs.count() == 1
        assert _topic(page, 0) == first  # 剩下的是原来那个
        page.deleteLater()
        qapp.processEvents()

    def test_tab_reorder_keeps_topic_mapping(self, qapp):
        """标签可拖动换序：下标 → 话题 id 的映射必须跟着走。"""
        page = _page(qapp)
        first = _topic(page, 0)
        second = page._createTopic(activate=True)
        qapp.processEvents()

        page._tabs.moveTab(0, 1)  # 等价于用户把第一个标签拖到最后
        assert page._tab_ids == [second, first]
        assert page._currentTopicId() == second
        page.deleteLater()
        qapp.processEvents()


class TestAppearance:
    """外观偏好是宿主的全局设置：改一次要应用到所有话题页（含之后新建的）。"""

    def test_tab_counts_follow_messages(self, qapp):
        """标签文本里的条数跟着消息走（宿主列表最简接线：messageAdded → 刷新）。"""
        page = _page(qapp)
        topicId = _topic(page, 0)
        page._pages[topicId].chat.addMessage(ElaChatRoleType.User, "一条消息")
        qapp.processEvents()
        assert "1 条" in page._tabs.tabText(0)
        page.deleteLater()
        qapp.processEvents()

    def test_toggle_applies_to_all_topics_and_new_pages(self, qapp):
        page = _page(qapp)
        first = _topic(page, 0)
        second = page._createTopic(activate=True)
        qapp.processEvents()

        page._on_toggle_reasoning_style()
        qapp.processEvents()

        assert page._reasoning_style == ElaChatReasoningStyleType.Inline
        for topicId in (first, second):
            assert (
                page._pages[topicId].chat.chatView().reasoningStyle()
                == ElaChatReasoningStyleType.Inline
            )

        third = page._createTopic(activate=True)  # 新建的页也要带上偏好
        qapp.processEvents()
        assert (
            page._pages[third].chat.chatView().reasoningStyle()
            == ElaChatReasoningStyleType.Inline
        )
        page.deleteLater()
        qapp.processEvents()

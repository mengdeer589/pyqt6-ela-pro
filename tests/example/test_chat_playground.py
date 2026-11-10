"""AI 聊天实验台：splitter 特性面板 + 多话题插入。"""

from __future__ import annotations

from PyQt6.QtWidgets import QPushButton

from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.chat import ElaChatTracePanel, clearToolRenderers
from pyqt6_ela_pro.chat.blocks import ElaChatFileChanges, ToolCallCard
from pyqt6_ela_pro.ela_diff_view import ElaDiffView
from pyqt6_ela_pro.example.chat_playground_page import ChatPlaygroundPage


def _last_tool_card(page: ChatPlaygroundPage) -> ToolCallCard:
    view = page._active_chat().chatView()
    bubble = view.bubble(view.messages()[-1].id)
    assert bubble is not None
    card = bubble.toolPanel().findChild(ToolCallCard)
    assert card is not None
    return card


class TestChatPlaygroundPage:
    def test_layout_and_feature_tabs(self, qapp, make):
        page = make(ChatPlaygroundPage)
        assert page.PAGE_TITLE == "AI 组件"
        assert page._splitter.count() == 2
        assert len(page._feature_tabs()) == 6
        assert page._tabs.count() == 1
        assert page._active_chat() is not None

    def test_toggle_feature_panel(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        assert page._feature_panel.isVisible() is True
        page._toggle_features()
        qapp.processEvents()
        assert page._feature_panel.isVisible() is False
        page._toggle_features()
        qapp.processEvents()
        assert page._feature_panel.isVisible() is True

    def test_all_feature_callbacks_run(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        for _tab, features in page._feature_tabs():
            for _title, _hint, method, needs_idle in features:
                page._run_feature(method, needs_idle)
                qapp.processEvents()
                for dialog in list(page._dialogs):
                    dialog.close()
                page._dialogs.clear()
                qapp.processEvents()
        assert page._active_chat() is not None

    def test_trace_refresh_does_not_close_dialog(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        page._demo_trace(page._active_chat())
        qapp.processEvents()
        dialog = page._dialogs[-1]
        assert dialog.isVisible() is True
        panel = dialog.findChild(ElaChatTracePanel)
        assert panel is not None
        hidden_refresh = [
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "刷新" and not panel.isAncestorOf(button)
        ]
        assert hidden_refresh and all(button.isHidden() for button in hidden_refresh)
        assert panel._refresh_button.isVisible() is True
        panel._refresh_button.click()
        qapp.processEvents()
        assert dialog.isVisible() is True
        dialog.close()

    def test_insert_goes_to_active_topic(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        first = page._active_chat()
        page._run_feature(page._demo_plan, False)
        qapp.processEvents()
        first_count = first.chatView().count()
        assert first_count >= 2

        page._createTopic(activate=True)
        qapp.processEvents()
        second = page._active_chat()
        assert second is not first
        page._run_feature(page._demo_plan, False)
        qapp.processEvents()
        assert second.chatView().count() >= 2
        assert first.chatView().count() == first_count

    def test_rich_renderer_builds_diff_and_pushes_result(self, qapp, make):
        """富渲染器演示必须是真内容：文件行 + 真实 diff + 结果回传。"""
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        page._run_feature(page._demo_renderer, False)
        qapp.processEvents()

        card = _last_tool_card(page)
        assert card.isOpened() is True
        assert card._subtitle_text == "2 个文件"
        assert "files=" not in card._args_text
        widget = card._renderer_widget
        assert widget is not None
        assert widget.findChild(ElaChatFileChanges) is not None
        assert widget.findChildren(ElaDiffView)
        result = widget.findChild(ColorText, "demoPatchResult")
        assert result is not None
        assert result.text().startswith("已完成")
        assert "2 个文件已更新" in result.text()

    def test_file_changes_demo_installs_builtin_renderer(self, qapp, make):
        """不依赖先点「内置渲染器」：本演示自己安装 edit 的内置渲染器。"""
        clearToolRenderers()
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        page._run_feature(page._demo_file_changes, False)
        qapp.processEvents()

        card = _last_tool_card(page)
        card.setOpened(True)
        qapp.processEvents()
        assert card._renderer_widget is not None
        assert isinstance(card._renderer_widget, ElaChatFileChanges)

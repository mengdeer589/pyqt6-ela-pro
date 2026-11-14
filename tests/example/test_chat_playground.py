"""AI 聊天实验台：splitter 特性面板 + 多话题插入。"""

from __future__ import annotations

from PyQt6.QtWidgets import QPushButton

from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.chat import (
    ElaChatQueueDock,
    ElaChatRoleType,
    ElaChatTracePanel,
    clearToolRenderers,
)
from pyqt6_ela_pro.chat.blocks import ElaChatFileChanges, PermissionCard, ToolCallCard
from pyqt6_ela_pro.ela_diff_view import ElaDiffView
from pyqt6_ela_pro.example.chat_gallery import ChatGalleryDialog
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
        tabs = page._feature_tabs()
        assert len(tabs) == 8
        assert tabs[0][0] == "快速体验"
        assert all(features for _name, features in tabs)
        titles = [title for _name, features in tabs for title, *_rest in features]
        assert len(titles) == len(set(titles))
        assert page._tabs.count() == 1
        assert page._active_chat() is not None

    def test_input_area_shows_selector_and_completion(self, qapp, make):
        page = make(ChatPlaygroundPage)
        inp = page._active_chat().chatInput()
        bar = inp.toolBar()
        selector = bar.item("mode")
        assert selector is not None
        assert bar._leading.indexOf(selector) > bar._leading.indexOf(inp._usage_ring)
        assert bar._leading.indexOf(selector) == bar._leading.count() - 1
        assert inp.history() is not None
        assert inp._mention_provider is not None
        assert inp._command_provider is not None

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
        for tab, features in page._feature_tabs():
            if tab == "快速体验":
                continue
            for title, _hint, method, needs_idle in features:
                page._run_feature(method, needs_idle)
                qapp.processEvents()
                assert "演示插入失败" not in page._status.status(), title
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

    def test_host_contract_undo_and_stop(self, qapp, make):
        """撤回 / 重新生成 / 停止必须真的落到消息与后端，而不是只发信号。"""
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        page._demo_basic_turn(page._active_chat())
        qapp.processEvents()

        chat = page._active_chat()
        topic = page._active_page()
        view = chat.chatView()
        assert view.messages()
        user_id = page._last_message_id(chat, ElaChatRoleType.User)
        assert user_id is not None

        chat.undoRequested.emit(user_id)
        qapp.processEvents()
        assert chat.chatInput().text() == "跑一条完整回合"
        assert not view.messages()

        page._demo_basic_turn(chat)
        qapp.processEvents()
        assistant_id = page._last_message_id(chat, ElaChatRoleType.Assistant)
        assert assistant_id is not None
        chat.regenerateRequested.emit(assistant_id)
        qapp.processEvents()
        assert chat.isGenerating() is True

        chat.stopGeneration()
        qapp.processEvents()
        assert topic.mock.isRunning() is False
        assert chat.isGenerating() is False

    def test_suggestion_command_and_shell(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        chat = page._active_chat()
        view = chat.chatView()
        inp = chat.chatInput()

        chat.suggestionClicked.emit("你好")
        qapp.processEvents()
        assert view.messages()
        assert chat.isGenerating() is True

        inp.setText("/clear")
        inp.submit()
        qapp.processEvents()
        assert not view.messages()

        inp.setText("/help")
        inp.submit()
        qapp.processEvents()
        assert any("可用命令" in m.text for m in view.messages())

        inp.setShellMode(True)
        inp.setText("echo hello")
        inp.submit()
        qapp.processEvents()
        texts = [m.text for m in view.messages()]
        assert any("echo hello" in text for text in texts)

    def test_feature_feedback_updates(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        page._run_feature(page._demo_plan, False, "计划 / 待办")
        qapp.processEvents()
        assert page._feature_feedback is not None
        assert page._feature_feedback.text().startswith("已完成")

    def test_quick_scenario_runs(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        assert page._scenario_labels
        page._start_scenario("引导 · 消息操作", page._scenario_actions)
        qapp.processEvents()
        chat = page._active_chat()
        assert chat.chatView().messages()
        label = page._scenario_labels["引导 · 消息操作"]
        assert "撤回" in label.text()

    def test_approval_toggle_drops_pending_message(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        chat = page._active_chat()
        page._demo_approval(chat)
        qapp.processEvents()
        assert chat.chatView().messages()
        assert chat.permissionDock().card() is not None
        page._demo_approval(chat)
        qapp.processEvents()
        assert not chat.chatView().messages()
        assert chat.permissionDock().card() is None

    def test_error_retry_starts_turn(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        chat = page._active_chat()
        page._demo_message_error(chat)
        qapp.processEvents()
        error_id = page._active_page().error_id
        assert error_id is not None
        chat.retryRequested.emit(error_id)
        qapp.processEvents()
        assert chat.isGenerating() is True
        chat.stopGeneration()
        qapp.processEvents()

    def test_context_usage_click_opens_dialog(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        chat = page._active_chat()
        chat.chatInput().setContextUsage(1200, 200000, 0.02)
        chat.contextUsageClicked.emit()
        qapp.processEvents()
        assert page._dialogs
        page._dialogs[-1].close()

    def test_approval_reply_settles_message(self, qapp, make):
        page = make(ChatPlaygroundPage)
        page.resize(1100, 800)
        page.show()
        qapp.processEvents()
        chat = page._active_chat()
        page._start_scenario("引导 · 批准审批", page._scenario_approval)
        qapp.processEvents()
        cards = chat.pendingPermissionCards()
        assert cards
        cards[0].replied.emit("allowed", "", "")
        qapp.processEvents()
        assert any("审批结果" in m.text for m in chat.chatView().messages())
        assert all(not m.isStreaming for m in chat.chatView().messages())

    def test_gallery_builds_interactive_blocks(self, qapp, make):
        page = make(ChatPlaygroundPage)
        dialog = make(ChatGalleryDialog, page)
        cards = dialog.findChildren(PermissionCard)
        assert cards
        assert dialog.findChild(ElaChatQueueDock) is not None
        assert dialog.findChildren(ColorText)
        cards[0].replied.emit("allowed", "", "")
        qapp.processEvents()
        assert any("allowed" in label.text() for label in dialog._feedback)

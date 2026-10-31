"""聊天示例页的形状守卫。

聊天示例页有两条**容易被静默破坏**的约定，靠肉眼 review 看不出来：

1. **每节都要有内容** —— 「预填」是靠页面构造时跑一遍脚本实现的。一旦某一步
   抛异常（API 改名 / 参数改名），页面照样建得出来、渲染出来，只是**某一节
   是空的**。全绿测试不代表展示正确。
2. **每节的回调都要能跑通** —— 演示方法里常有 ``message.toolCalls`` 这类跟着
   库改名的属性；错了不在构造时暴露，只在点击那一刻炸，而 PyQt5 的槽在异常时
   会 0xC0000409 **静默终止**（连 pytest 的报告都没有，整轮测试凭空消失）。

**刻意不「把页面上所有按钮点一遍」**：那会点到「清空上下文」——
``ElaConfirmDialog`` 是模态的，在测试进程里直接阻塞。所以这里逐个点名调用
那些**确定无副作用**的回调。
"""

from __future__ import annotations

import pytest

from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import ElaChatReasoningStyleType
from pyqt6_ela_pro.example.chat_agent_page import ChatAgentPage
from pyqt6_ela_pro.example.chat_files_page import ChatFilesPage
from pyqt6_ela_pro.example.chat_input_page import ChatInputPage
from pyqt6_ela_pro.example.chat_overview_page import ChatOverviewPage
from pyqt6_ela_pro.example.chat_persist_page import ChatPersistPage
from pyqt6_ela_pro.example.chat_session_page import ChatSessionPage
from pyqt6_ela_pro.example.chat_timeline_page import ChatTimelinePage
from pyqt6_ela_pro.example.chat_workbench_page import ChatWorkbenchPage

CHAT_PAGES = [
    (ChatOverviewPage, "聊天组件总览"),
    (ChatInputPage, "输入区能力"),
    (ChatAgentPage, "Agent 能力"),
    (ChatFilesPage, "文件与 Diff"),
    (ChatTimelinePage, "时间线与检索"),
    (ChatSessionPage, "会话管理"),
    (ChatPersistPage, "持久化与性能"),
]


@pytest.mark.parametrize("cls,title", CHAT_PAGES, ids=[t for _c, t in CHAT_PAGES])
def test_page_constructs_with_title(cls, title, qapp, make):
    page = make(cls)
    assert page.PAGE_TITLE == title


# ================================================================ 工作台
class TestChatWorkbenchPage:
    def test_has_all_workspaces(self, qapp, make):
        page = make(ChatWorkbenchPage)
        assert page.PAGE_TITLE == "AI 组件工作台"
        titles = list(page._pivot.getPivotTitle())
        assert titles == [name for name, _desc, _cls in page.WORKSPACES]
        assert page._stack.count() == len(page.WORKSPACES)

    def test_only_first_workspace_built_on_start(self, qapp, make):
        """与图表工作台一致：首屏只建概览，其余工作区首次切换才实例化。"""
        page = make(ChatWorkbenchPage)
        assert page._workspaces[0]["page"] is not None
        assert all(item["page"] is None for item in page._workspaces[1:])

    def test_switch_builds_workspace_lazily(self, qapp, make):
        page = make(ChatWorkbenchPage)
        page._activate_workspace(3)
        assert page._stack.currentIndex() == 3
        assert page._workspaces[3]["page"] is not None
        assert page._workspaces[3]["page"].PAGE_TITLE == "文件与 Diff"
        # 未切到的工作区仍未构建
        assert page._workspaces[5]["page"] is None

    def test_every_workspace_builds(self, qapp, make):
        page = make(ChatWorkbenchPage)
        for index in range(len(page.WORKSPACES)):
            page._activate_workspace(index)
            assert page._workspaces[index]["page"] is not None
            assert page._stack.currentIndex() == index


# ================================================================ 总览
class TestChatOverviewPage:
    def test_prefilled_without_interaction(self, qapp, make):
        """预填：构造完就有消息（用户不用自己造一轮对话）。"""
        page = make(ChatOverviewPage)
        messages = page._chat.chatView().messages()
        assert len(messages) >= 2
        assert messages[0].isUser
        assert messages[-1].isAssistant

    def test_prefilled_turn_has_rich_parts(self, qapp, make):
        """预填那条必须把能力面铺满：推理 / 正文 / 工具（成功 + 失败）/ 统计。

        ``part.kind`` 是**字符串**（``'reasoning'`` / ``'text'`` / ``'tool'`` /
        ``'stats'`` …），不是枚举 —— 别按枚举写断言。
        """
        page = make(ChatOverviewPage)
        messages = page._chat.chatView().messages()
        message = messages[-1]
        kinds = [part.kind for part in message.parts]
        assert kinds.count("reasoning") == 1, kinds
        assert kinds.count("text") == 2, kinds
        assert kinds.count("tool") == 2, kinds
        assert kinds.count("stats") == 1, kinds
        # ToolCall 的成败在 `status` 上（不是 `ok` 布尔）：
        # Done=成功、Error=失败、Aborted=回合中止时未完成
        from pyqt6_ela_pro.chat import ElaChatToolStatusType

        statuses = {call.status for call in message.tool_calls}
        assert statuses == {ElaChatToolStatusType.Done, ElaChatToolStatusType.Error}, statuses
        # 附件挂在**用户**那条上（附件是独立的一行，不拼进正文）
        assert len(messages[0].attachments) == 2

    def test_appearance_setters_hit_existing_messages(self, qapp, make):
        """外观开关作用于**已有**消息，不是只对之后新生成的生效。"""
        page = make(ChatOverviewPage)
        view = page._chat.chatView()
        original = view.reasoningStyle()

        page._on_reasoning_style(ElaChatReasoningStyleType.Inline)
        assert view.reasoningStyle() == ElaChatReasoningStyleType.Inline
        page._on_reasoning_style(original)

        page._on_tool_grouping("raw")
        assert view.toolGrouping() is False
        page._on_tool_grouping("group")
        assert view.toolGrouping() is True

        page._on_stats_mode("none")
        assert view.statsMode() == "none"
        page._on_stats_mode("footer")

        page._on_avatar_shape("square")
        assert view.avatarShape() == "square"
        page._on_avatar_shape("rounded")

        page._on_waiting_placeholder(False)
        assert view.waitingPlaceholderEnabled() is False
        page._on_waiting_placeholder(True)
        assert view.waitingPlaceholderEnabled() is True

    def test_appearance_dropdown_checks_are_exclusive_and_synced(self, qapp, make):
        """下拉勾选态必须互斥、跟随当前选择，且再点已选项保持勾选（radio 语义）。

        回归：回调原先只改 view 与按钮文案、不重刷 actions —— 选「内联」后两项
        同时勾选；再点已选项被 Qt 的 toggle 取消，菜单里一个勾都没有。
        """
        page = make(ChatOverviewPage)
        actions = page._reasoning_actions
        order = list(actions)
        assert order == [
            ElaChatReasoningStyleType.Collapse,
            ElaChatReasoningStyleType.Inline,
        ]

        actions[order[1]].trigger()
        qapp.processEvents()
        assert [actions[key].isChecked() for key in order] == [False, True]
        assert page._chat.chatView().reasoningStyle() == order[1]
        assert "内联" in page._reasoning_button.text()

        actions[order[1]].trigger()
        qapp.processEvents()
        assert [actions[key].isChecked() for key in order] == [False, True]

        actions[order[0]].trigger()
        qapp.processEvents()
        assert [actions[key].isChecked() for key in order] == [True, False]
        assert "折叠" in page._reasoning_button.text()

    def test_content_width_toggle(self, qapp, make):
        page = make(ChatOverviewPage)
        view = page._chat.chatView()
        page._on_content_width()
        assert view.contentMaxWidth() == 720
        page._on_content_width()
        assert view.contentMaxWidth() == 0

    def test_replay_appends_another_turn(self, qapp, make):
        """重播走 QTimer 回调链，跑完必须还活着。"""
        page = make(ChatOverviewPage)
        before = page._chat.chatView().count()
        page._player.play(page._script_full_turn(), interval=0)
        assert _wait_until(qapp, lambda: page._chat.chatView().count() > before)


# ================================================================ 输入区
class TestChatInputPage:
    def test_all_sections_present(self, qapp, make):
        page = make(ChatInputPage)
        assert sorted(page._section_notes) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    def test_safe_callbacks_run(self, qapp, make):
        """逐个点名调用**无副作用**的回调（避开模态的清空确认）。"""
        page = make(ChatInputPage)
        for callback in (
            page._on_add_toolbar_button,
            page._on_toggle_reasoning,
            page._on_demo_attachment,
            page._on_send_with_attachment,
            page._on_context,
            page._on_enqueue,
            page._on_stress,
            page._on_new_topic_clicked,
            page._demo_usage,
            page._on_context_usage_clicked,
        ):
            callback()
            qapp.processEvents()
        assert page._chat.chatView().count() > 1

    def test_mention_provider_filters(self, qapp, make):
        page = make(ChatInputPage)
        assert len(page._mention_suggestions("")) == 3
        assert len(page._mention_suggestions("read")) == 1
        assert page._mention_suggestions("zzz") == []

    def test_usage_demo_feeds_the_ring(self, qapp, make):
        """「上下文占用圆环」节真的把数据喂进输入区工具栏的圆环。

        圆环是**默认组件**（跟新建话题 / 上传 / 清空一样常驻），喂数据只改
        百分比、不改显隐。
        """
        page = make(ChatInputPage)
        ring = page._chat.chatInput().contextUsageWidget()
        assert not ring.isHidden()  # 默认就显示（空底环 0%）

        page._demo_usage()
        qapp.processEvents()
        assert not ring.isHidden()
        assert page._chat.chatInput().contextUsagePercent() == 9

        # 点击回执（真宿主在此弹自己的详情面板）
        page._on_context_usage_clicked()
        qapp.processEvents()

    def test_attachments_reach_the_backend(self, qapp, make):
        """带附件发送时，附件必须真的送进后端（不是只画在消息上）。

        链路：`messageSubmittedFull` → `_on_submitted` 存附件 → `_start_answer`
        → `binder.startTurn(attachments=...)` → `mock.turnAttachments()`。
        """
        page = make(ChatInputPage)
        page._on_send_with_attachment()
        qapp.processEvents()
        # 示例页传的是原始 dict（真实宿主传 message.attachments，是 ElaChatAttachment）
        attachments = page._mock.turnAttachments()
        assert [item["name"] for item in attachments] == ["blocks.py", "notes.md"]

    def test_turn_control_handles_empty_history(self, qapp, make):
        """空历史时「撤回 / 重新生成」要给出提示而不是炸。"""
        page = make(ChatInputPage)
        page._on_undo_last()
        page._on_regenerate_last()
        qapp.processEvents()

    def test_queue_advanced_ops(self, qapp, make):
        page = make(ChatInputPage)
        page._on_queue_advanced()
        page._on_queue_undo()
        page._on_pending_steer()
        qapp.processEvents()
        assert page._chat.steerCount() >= 1


# ================================================================ Agent
class TestChatAgentPage:
    def test_section_titles_unique(self, qapp, make):
        """回归：原来「2. 工具审批」被写了两遍（批准型 + 问答型）。"""
        page = make(ChatAgentPage)
        titles = [title for _i, title, *_ in page._sections()]
        assert len(titles) == len(set(titles)), f"小节标题重复：{titles}"

    def test_all_demo_callbacks_run(self, qapp, make):
        page = make(ChatAgentPage)
        for _i, _title, _method, buttons, _hint in page._sections():
            for _text, callback in buttons:
                callback()
                qapp.processEvents()
        assert page._chat.chatView().count() > 3

    def test_each_section_writes_its_own_note(self, qapp, make):
        """每节一个说明行：``_fire`` 把回调绑到「它属于哪一节」。"""
        page = make(ChatAgentPage)
        labels = []
        for _i, _title, _method, buttons, _hint in page._sections():
            if not buttons:
                continue
            label = _FakeLabel()
            labels.append(label)
            page._fire(label, buttons[0][1])()
        assert labels and all(label.text for label in labels), (
            "某一节的回调没写进自己的说明行"
        )


# ================================================================ 文件与 Diff
class TestChatFilesPage:
    def test_prefilled_and_callbacks(self, qapp, make):
        page = make(ChatFilesPage)
        assert page._chat.chatView().count() >= 1
        for _label, method in page._sections:
            page._fire(method)()
            qapp.processEvents()
        assert page._chat.chatView().count() >= 6

    def test_multi_file_and_long_diff(self, qapp, make):
        page = make(ChatFilesPage)
        page._demo_multi_file()
        page._demo_long_diff()
        qapp.processEvents()
        messages = page._chat.chatView().messages()
        calls = [call for message in messages for call in message.tool_calls]
        assert any(call.name == "patch" for call in calls)


# ================================================================ 时间线与检索
class TestChatTimelinePage:
    def test_sample_and_status_callbacks(self, qapp, make):
        page = make(ChatTimelinePage)
        assert page._chat.chatView().count() >= 2
        page._demo_notices()
        page._demo_retry()
        page._demo_activity()
        page._demo_density()
        page._demo_disclosure()
        page._demo_pending()
        page._demo_identity()
        qapp.processEvents()
        assert page._chat.chatView().count() >= 3

    def test_search_and_pending(self, qapp, make):
        page = make(ChatTimelinePage)
        page._demo_search()
        assert page._chat.chatView().searchHits()
        page._demo_pending()
        assert page._pending_id is not None
        page._resolve_pending()
        assert page._pending_id is None


class _FakeLabel:
    """只为了验证「回调写到了正确的那个说明行」。"""

    def __init__(self):
        self.text = ""

    def setText(self, text):  # noqa: N802 (Qt 命名)
        self.text = text


# ================================================================ 会话
class TestChatSessionPage:
    def test_topic_lifecycle(self, qapp, make):
        page = make(ChatSessionPage)
        assert len(page._pages) == 1
        page._on_new_topic_clicked()
        qapp.processEvents()
        assert len(page._pages) == 2
        page._on_archive_clicked()
        qapp.processEvents()
        assert len(page._pages) == 1
        assert page._bundles, "归档后应当留下一份 bundle"

    def test_appearance_propagates_to_all_pages(self, qapp, make):
        """外观偏好是**宿主全局设置**：一话题一 widget，改了要应用到所有页。"""
        page = make(ChatSessionPage)
        page._on_new_topic_clicked()
        qapp.processEvents()
        page._on_toggle_reasoning_style()
        qapp.processEvents()
        styles = {p.chat.chatView().reasoningStyle() for p in page._pages.values()}
        assert styles == {ElaChatReasoningStyleType.Inline}, (
            f"有页面没跟上外观设置：{styles}"
        )


# ================================================================ 持久化
class TestChatPersistPage:
    def test_round_is_recorded(self, qapp, make):
        """构造完就有一份回合日志（_push 记事件的同时就 apply 它）。"""
        page = make(ChatPersistPage)
        assert page._journal is not None
        assert page._journal.events()

    def test_replay_restores_the_turn(self, qapp, make):
        page = make(ChatPersistPage)
        page._on_replay()
        qapp.processEvents()
        assert page._chat.chatView().count() >= 1

    def test_corrupt_lines_tolerated(self, qapp, make):
        """截断行 + 未知事件都不能让整条日志废掉。"""
        page = make(ChatPersistPage)
        lines = page._journal.dumps().splitlines()
        lines.append(lines[-1][:5])
        lines.append('{"t":"未来事件"}')
        journal = type(page._journal).fromLines(lines)
        assert journal.message().status == "done"

    def test_session_roundtrip(self, qapp, make):
        page = make(ChatPersistPage)
        page._on_export()
        page._on_import()
        page._on_restore()
        qapp.processEvents()
        assert page._chat.chatView().count() >= 1

    def test_perf_switches(self, qapp, make):
        """两个开关都是「翻转当前值」。

        注意**默认都是开**（延迟重排、视口挂起），所以第一次点击是关 ——
        断言「点完等于 True」会把默认值写死进去，以后库改默认就假失败。
        """
        page = make(ChatPersistPage)
        view = page._chat.chatView()

        before = view.resizeReflowDeferred()
        page._on_toggle_reflow()
        assert view.resizeReflowDeferred() is (not before)
        page._on_toggle_reflow()
        assert view.resizeReflowDeferred() is before

        before = view.viewportSuspension()
        page._on_toggle_suspend()
        assert view.viewportSuspension() is (not before)
        page._on_toggle_suspend()
        assert view.viewportSuspension() is before

        page._on_batch()
        page._on_load_30()
        assert view.count() > 1

    def test_view_state_bundle(self, qapp, make):
        page = make(ChatPersistPage)
        page._demo_view_state()
        assert page._view_bundle is not None
        options = page._view_bundle["view"]
        assert options["timeline_detail"]["thinking"]["placement"] == "expanded"
        assert options["disclosure"]
        assert page._chat.draftState()["text"]
        page._on_inspect_state()
        assert "timeline_detail" in page._notes["state"].text()

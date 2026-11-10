"""AI 聊天实验台：多话题聊天 + 右侧 ElaSplitter 特性面板。"""

from __future__ import annotations

import json
import traceback
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaPivot,
    ElaScrollArea,
    ElaTabBar,
    ElaText,
)

from pyqt6_ela_pro import ElaButton, ElaDialogBase, ElaSplitter, ElaThemeWidget
from pyqt6_ela_pro._internal import safe_connect
from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.chat import (
    ElaChatFileChanges,
    ElaChatMockBackend,
    ElaChatOption,
    ElaChatPermission,
    ElaChatPlan,
    ElaChatQuestion,
    ElaChatRoleType,
    ElaChatSessionInfo,
    ElaChatStats,
    ElaChatStatusBar,
    ElaChatStreamBinder,
    ElaChatToolStatusType,
    ElaChatTracePanel,
    ElaChatWidget,
    installBuiltinToolRenderers,
    registerToolRenderer,
)
from pyqt6_ela_pro.chat.blocks import ToolCallCard
from pyqt6_ela_pro.chat.renderers import parseToolArguments
from .base_page import ExamplePage

#: 右侧特性面板默认宽度
FEATURE_PANEL_WIDTH = 420

#: 「富渲染器」演示的 patch 数据（before / after → 真实 diff）
_DEMO_PATCH_FILES = (
    {
        "file": "chat/renderers.py",
        "before": "def toolRenderer(name):\n    return _REGISTRY.get(name)\n",
        "after": (
            "def toolRenderer(name):\n"
            "    entry = _REGISTRY.get(name)\n"
            "    return entry.factory if entry is not None else None\n"
        ),
        "status": "modified",
    },
    {
        "file": "example/playground.py",
        "before": "def _demo_renderer(chat):\n    label = ColorText()\n",
        "after": (
            "def _demo_renderer(chat):\n"
            "    body = _DemoPatchBody(files)\n"
            "    return body\n"
        ),
        "status": "modified",
    },
)

#: 工具状态 → 演示文案
_TOOL_STATUS_TEXT = {
    ElaChatToolStatusType.Pending: "等待中",
    ElaChatToolStatusType.Running: "运行中",
    ElaChatToolStatusType.Done: "已完成",
    ElaChatToolStatusType.Error: "失败",
    ElaChatToolStatusType.Aborted: "已中止",
}


class _DemoPatchBody(QWidget):
    """「富渲染器」演示内容区：文件行 + 真实 diff + 结果回传。"""

    def __init__(self, files, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._changes = ElaChatFileChanges(self)
        self._changes.setFiles(files or ())
        layout.addWidget(self._changes)
        self._result = ColorText(self)
        self._result.setObjectName("demoPatchResult")
        self._result.setTextFormat(Qt.TextFormat.PlainText)
        self._result.setTextPixelSize(11)
        self._result.setWordWrap(True)
        self._result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._result)

    def updateToolResult(self, result: str, status: str) -> None:
        """接收工具结果推送（运行中 → 已完成）。"""
        label = _TOOL_STATUS_TEXT.get(status, str(status or ""))
        text = str(result or "").strip()
        self._result.setText(f"{label} · {text}" if text else label)


class _TopicPage:
    """一个话题的聊天页 + 假后端 + 流绑定器。"""

    def __init__(self, container, chat, mock, binder):
        self.container = container
        self.chat = chat
        self.mock = mock
        self.binder = binder


class ChatPlaygroundPage(ExamplePage):
    """标准多话题聊天页；组件特性从右侧 splitter 面板插入当前话题。"""

    PAGE_TITLE = "AI 组件"

    def __init__(self, parent=None):
        self._sessions: dict[str, ElaChatSessionInfo] = {}
        self._pages: dict[str, _TopicPage] = {}
        self._bundles: dict[str, dict] = {}
        self._tab_ids: list[str] = []
        self._seq = 0
        self._tabs: Optional[ElaTabBar] = None
        self._stack: Optional[QStackedWidget] = None
        self._splitter: Optional[ElaSplitter] = None
        self._feature_panel: Optional[QWidget] = None
        self._feature_pivot: Optional[ElaPivot] = None
        self._feature_stack: Optional[QStackedWidget] = None
        self._feature_button: Optional[ElaButton] = None
        self._status: Optional[ElaChatStatusBar] = None
        self._feature_width = FEATURE_PANEL_WIDTH
        self._dialogs: list = []
        self._reasoning_style = "collapse"
        super().__init__(parent)

    def _setupUI(self):
        super()._setupUI()
        root = self.layout()
        root.removeWidget(self._scrollArea)
        self._scrollArea.hide()
        self._scrollArea.deleteLater()
        self._build_playground(root)

    def buildDemoContent(self):
        if self._demo_built:
            return
        self._demo_built = True

    def _build_playground(self, root_layout) -> None:
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = ElaThemeWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 10)
        header_layout.setSpacing(10)
        title = ElaText("AI 聊天", header)
        title.setTextPixelSize(20)
        font = QFont()
        font.setPixelSize(20)
        font.setBold(True)
        title.setFont(font)
        header_layout.addWidget(title)
        subtitle = ElaText("多话题 · 输入区 · 特性面板", header)
        subtitle.setTextPixelSize(12)
        subtitle.setWordWrap(False)
        header_layout.addWidget(subtitle)
        header_layout.addStretch(1)

        self._feature_button = ElaButton(
            "收起特性",
            icon=ElaIconType.IconName.Sliders,
            variant="outlined",
            parent=header,
        )
        self._feature_button.setFixedWidth(120)
        safe_connect(
            self._feature_button,
            "clicked",
            lambda _=False: self._toggle_features(),
            "playground.feature_toggle",
            receiver=self._feature_button,
        )
        header_layout.addWidget(self._feature_button)
        new_button = ElaButton(
            "新建话题",
            icon=ElaIconType.IconName.CommentPlus,
            variant="outlined",
            parent=header,
        )
        new_button.setFixedWidth(120)
        safe_connect(
            new_button,
            "clicked",
            lambda _=False: self._createTopic(activate=True),
            "playground.new_topic",
            receiver=new_button,
        )
        header_layout.addWidget(new_button)
        root_layout.addWidget(header)

        self._splitter = ElaSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setHandleWidth(6)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)

        left = QWidget(self._splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 8, 8, 8)
        left_layout.setSpacing(8)
        self._tabs = ElaTabBar(left)
        # ElaTabBar 在空表时 sizeHint 为 0，布局会把它压成 0 高；先钉住高度。
        self._tabs.setFixedHeight(40)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        left_layout.addWidget(self._tabs)
        self._stack = QStackedWidget(left)
        left_layout.addWidget(self._stack, 1)

        self._feature_panel = self._build_feature_panel(self._splitter)
        self._splitter.addWidget(left)
        self._splitter.addWidget(self._feature_panel)
        self._splitter.setSizes([760, FEATURE_PANEL_WIDTH])
        root_layout.addWidget(self._splitter, 1)

        self._status = ElaChatStatusBar(self)
        self._status.setInfo("多话题 · 一话题一 widget · 特性面板插入当前话题")
        self._status.setStatus("最近操作：—")
        root_layout.addWidget(self._status)

        self._createTopic(activate=True)

    def _build_feature_panel(self, parent) -> QWidget:
        panel = ElaThemeWidget(parent)
        panel.setMinimumWidth(340)
        panel.setMaximumWidth(620)
        panel.setAutoFillBackground(True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = ColorText("特性", panel)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setTextPixelSize(15)
        title.setTextWeight(QFont.Weight.DemiBold)
        head.addWidget(title)
        hint = ColorText("插入当前话题", panel)
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setTextPixelSize(11)
        head.addWidget(hint)
        head.addStretch(1)
        layout.addLayout(head)

        self._feature_pivot = ElaPivot(panel)
        self._feature_pivot.setTextPixelSize(13)
        self._feature_stack = QStackedWidget(panel)
        for name, features in self._feature_tabs():
            self._feature_pivot.appendPivot(name)
            self._feature_stack.addWidget(self._build_feature_tab(features))
        self._feature_pivot.setCurrentIndex(0)
        self._feature_pivot.pivotClicked.connect(self._on_feature_tab)
        layout.addWidget(self._feature_pivot)
        layout.addWidget(self._feature_stack, 1)
        return panel

    def _feature_tabs(self):
        """``(tab 名, ((标题, 说明, 方法, 需要空闲), ...))``。"""
        return (
            (
                "基础",
                (
                    (
                        "完整回合",
                        "一条流式回答 + 工具卡 + 统计",
                        self._demo_basic_turn,
                        True,
                    ),
                    (
                        "计划 / 待办",
                        "折叠摘要 + checklist；反复更新同一张卡",
                        self._demo_plan,
                        False,
                    ),
                    (
                        "多步骤回合",
                        "探索 + 计划 → 子代理 → 编辑 + 汇总",
                        self._demo_multi_step,
                        True,
                    ),
                ),
            ),
            (
                "工具",
                (
                    (
                        "内置渲染器",
                        "read / glob / grep / fetch / mcp / todo",
                        self._demo_builtins,
                        False,
                    ),
                    (
                        "文件变更 / diff",
                        "metadata.files → ElaChatFileChanges",
                        self._demo_file_changes,
                        False,
                    ),
                    (
                        "富渲染器",
                        "registerToolRenderer：真实 diff + 结果回传",
                        self._demo_renderer,
                        False,
                    ),
                ),
            ),
            (
                "Agent",
                (
                    (
                        "子代理嵌套",
                        "delegate_task + 子工具",
                        self._demo_subagent,
                        False,
                    ),
                    (
                        "批准型审批",
                        "允许一次 / 长按始终允许 / 拒绝",
                        self._demo_approval,
                        False,
                    ),
                    ("问答型审批", "逐题向导 + 自定义答案", self._demo_question, False),
                    (
                        "steer 插话",
                        "在 beginStep 边界送进当前回合",
                        self._demo_steer,
                        True,
                    ),
                    (
                        "上下文压缩",
                        "只表达，不实现压缩算法",
                        self._demo_compaction,
                        False,
                    ),
                ),
            ),
            (
                "时间线",
                (
                    (
                        "通知 / 重试 / 活动行",
                        "三种不占正文的时间线状态",
                        self._demo_timeline,
                        False,
                    ),
                    ("成本 / 上下文", "步骤用量 + 输入区圆环", self._demo_cost, False),
                    (
                        "运行轨迹",
                        "turn → step → tool 独立面板",
                        self._demo_trace,
                        False,
                    ),
                ),
            ),
            (
                "会话",
                (
                    (
                        "新建话题",
                        "新页面 + 新后端，旧话题继续生成",
                        self._demo_new_topic,
                        False,
                    ),
                    ("归档当前", "exportSession → 销毁页面", self._demo_archive, False),
                    (
                        "恢复最近归档",
                        "importSession + 回填草稿",
                        self._demo_restore,
                        False,
                    ),
                ),
            ),
            (
                "输入",
                (
                    (
                        "Shell 模式",
                        "等宽字体 / Esc 退出 / shellSubmitted",
                        self._demo_shell_mode,
                        False,
                    ),
                    ("提示历史", "↑/↓ 浏览草稿", self._demo_history_hint, False),
                ),
            ),
        )

    def _build_feature_tab(self, features) -> QWidget:
        scroll = ElaScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(12)
        for title, hint, method, needs_idle in features:
            section = QWidget(content)
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(4)
            head = QHBoxLayout()
            head.setSpacing(8)
            label = ColorText(title, section)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextPixelSize(13)
            label.setTextWeight(QFont.Weight.DemiBold)
            head.addWidget(label, 1)
            button = ElaButton(
                "插入",
                variant="outlined",
                size="small",
                parent=section,
            )
            button.setFixedWidth(64)
            safe_connect(
                button,
                "clicked",
                lambda _=False, fn=method, idle=needs_idle: self._run_feature(fn, idle),
                "playground.feature",
                receiver=button,
            )
            head.addWidget(button)
            section_layout.addLayout(head)
            note = ColorText(hint, section)
            note.setTextFormat(Qt.TextFormat.PlainText)
            note.setTextPixelSize(12)
            note.setWordWrap(True)
            section_layout.addWidget(note)
            layout.addWidget(section)
        layout.addStretch(1)
        scroll.setWidget(content)
        content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        return scroll

    def _currentTopicId(self) -> Optional[str]:
        if self._tabs is None:
            return None
        index = self._tabs.currentIndex()
        if 0 <= index < len(self._tab_ids):
            return self._tab_ids[index]
        return None

    def _active_page(self) -> Optional[_TopicPage]:
        topic_id = self._currentTopicId()
        return self._pages.get(topic_id) if topic_id else None

    def _active_chat(self) -> Optional[ElaChatWidget]:
        page = self._active_page()
        return page.chat if page is not None else None

    def _createTopic(self, title=None, activate=True) -> str:
        self._seq += 1
        topicId = f"topic-{self._seq}"
        session = ElaChatSessionInfo(id=topicId, title=title or f"话题 {self._seq}")
        self._sessions[topicId] = session
        self._tabs.blockSignals(True)
        index = self._tabs.addTab(session.title)
        self._tabs.blockSignals(False)
        self._tab_ids.insert(index, topicId)
        if activate:
            self._activateTopic(topicId)
        self._status.setStatus(f"已新建「{session.title}」")
        return topicId

    def _pageFor(self, topicId) -> _TopicPage:
        topic = self._pages.get(topicId)
        if topic is not None:
            return topic
        container = QWidget(self._stack)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        chat = ElaChatWidget(container)
        layout.addWidget(chat)
        mock = ElaChatMockBackend(container, tickMs=24)
        binder = ElaChatStreamBinder(chat, worker=mock)
        chat.messageSubmittedFull.connect(
            lambda text, attachments, b=binder: b.startTurn(
                text, attachments=attachments
            )
        )
        mock.turnFinished.connect(binder.finish)
        chat.newTopicRequested.connect(lambda: self._createTopic(activate=True))
        chat.cleared.connect(lambda: self._status.setStatus("当前话题上下文已清空"))
        chat.chatView().messageAdded.connect(
            lambda *_args, tid=topicId: self._refreshTab(tid)
        )
        topic = _TopicPage(container=container, chat=chat, mock=mock, binder=binder)
        self._pages[topicId] = topic
        self._stack.addWidget(container)
        bundle = self._bundles.get(topicId)
        if bundle is not None:
            chat.chatView().importSession(bundle)
            draft = (bundle.get("extra") or {}).get("draft", "")
            if draft:
                chat.chatInput().setText(draft)
        self._applyAppearance(topic)
        chat.setCurrentSessionId(topicId)
        return topic

    def _applyAppearance(self, topic: _TopicPage) -> None:
        view = topic.chat.chatView()
        view.setReasoningStyle(self._reasoning_style)
        view.setChangeSummaryEnabled(True)

    def _refreshTab(self, topicId: str) -> None:
        if topicId not in self._tab_ids or self._tabs is None:
            return
        index = self._tab_ids.index(topicId)
        if self._tabs.tabText(index) == self._sessions[topicId].title:
            return
        self._tabs.blockSignals(True)
        self._tabs.setTabText(index, self._sessions[topicId].title)
        self._tabs.blockSignals(False)

    def _activateTopic(self, topicId: str) -> None:
        topic = self._pageFor(topicId)
        index = self._tab_ids.index(topicId) if topicId in self._tab_ids else -1
        if index >= 0 and self._tabs.currentIndex() != index:
            self._tabs.blockSignals(True)
            self._tabs.setCurrentIndex(index)
            self._tabs.blockSignals(False)
        self._stack.setCurrentWidget(topic.container)
        self._refreshTab(topicId)
        self._status.setStatus(f"已切换到「{self._sessions[topicId].title}」")

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self._tab_ids):
            topic = self._pageFor(self._tab_ids[index])
            self._stack.setCurrentWidget(topic.container)

    def _on_tab_close_requested(self, index: int) -> None:
        if 0 <= index < len(self._tab_ids):
            self._archiveTopic(self._tab_ids[index])

    def _archiveTopic(self, topicId: str) -> bool:
        topic = self._pages.get(topicId)
        if topic is None:
            return False
        bundle = topic.chat.chatView().exportSession(
            self._sessions[topicId],
            extra={"draft": topic.chat.chatInput().text()},
        )
        self._bundles[topicId] = bundle
        topic.binder.abortTurn()
        topic.mock.shutdown()
        was_current = topicId == self._currentTopicId()
        index = self._tab_ids.index(topicId) if topicId in self._tab_ids else -1
        if index >= 0:
            self._tabs.blockSignals(True)
            self._tabs.removeTab(index)
            self._tabs.blockSignals(False)
            self._tab_ids.pop(index)
        self._stack.removeWidget(topic.container)
        topic.container.deleteLater()
        del self._pages[topicId]
        self._status.setStatus(
            f"已归档「{self._sessions[topicId].title}」"
            f"（{len(bundle.get('messages', ()))} 条消息）"
        )
        if not self._tab_ids:
            self._createTopic(activate=True)
        elif was_current and index >= 0:
            self._tabs.setCurrentIndex(min(index, len(self._tab_ids) - 1))
            self._activateTopic(self._tab_ids[min(index, len(self._tab_ids) - 1)])
        return True

    def _restoreLastArchived(self) -> bool:
        archived = [
            topicId
            for topicId in self._sessions
            if topicId not in self._tab_ids and topicId in self._bundles
        ]
        if not archived:
            self._status.setStatus("没有已归档话题")
            return False
        topicId = archived[-1]
        session = self._sessions[topicId]
        self._tabs.blockSignals(True)
        index = self._tabs.addTab(session.title)
        self._tabs.blockSignals(False)
        self._tab_ids.insert(index, topicId)
        self._activateTopic(topicId)
        self._status.setStatus(f"已恢复「{session.title}」")
        return True

    def _run_feature(self, method: Callable, needs_idle: bool = False) -> None:
        chat = self._active_chat()
        if chat is None:
            self._createTopic(activate=True)
            chat = self._active_chat()
        if chat is None:
            return
        if needs_idle and chat.isGenerating():
            self._createTopic(activate=True)
            chat = self._active_chat()
        try:
            method(chat)
            self._status.setStatus("演示已插入当前话题")
        except Exception:
            traceback.print_exc()
            self._status.setStatus("演示插入失败（见控制台）")

    def _on_feature_tab(self, index: int) -> None:
        if self._feature_stack is not None:
            self._feature_stack.setCurrentIndex(index)

    def _toggle_features(self) -> None:
        panel = self._feature_panel
        if panel is None:
            return
        if panel.isVisible():
            self._feature_width = max(panel.width(), 340)
            panel.hide()
            self._feature_button.setText("特性")
        else:
            panel.show()
            total = max(1, self._splitter.width())
            self._splitter.setSizes(
                [max(1, total - self._feature_width), self._feature_width]
            )
            self._feature_button.setText("收起特性")

    def _start_demo(self, chat: ElaChatWidget, text: str):
        """演示回合不经过 mock 后端：直接建用户消息 + 助手流式消息。"""
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, text)
        return view, chat.beginAssistantMessage()

    def _open_tool_card(self, chat: ElaChatWidget, messageId: int, callId: str) -> None:
        """展开工具面板与指定卡片（演示内容第一眼可见）。"""
        bubble = chat.chatView().bubble(messageId)
        if bubble is None:
            return
        panel = bubble.toolPanel()
        if panel is None:
            return
        panel.setOpened(True)
        for card in panel.findChildren(ToolCallCard):
            if card.toolCallId() == callId:
                card.setOpened(True)
                return

    def _demo_basic_turn(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "跑一条完整回合")
        view.beginStep(mid)
        view.appendText(mid, "先看一下当前实现。")
        call = view.addToolCall(mid, "read", '{"path": "demo.py"}', kind="read")
        view.setToolCallResult(mid, call, "print('hello')", ok=True)
        view.setStepStats(mid, ElaChatStats(total_tokens=640, duration_ms=900))
        chat.endAssistantMessage()

    def _demo_plan(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "拆一下计划")
        view.beginStep(mid)
        view.setPlan(
            mid,
            ElaChatPlan.fromMarkdown("- [x] 读实现\n- [>] 改工具卡\n- [ ] 补回归测试"),
        )
        chat.endAssistantMessage()

    def _demo_multi_step(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "完整跑一轮")
        view.beginStep(mid)
        read = view.addToolCall(mid, "read", '{"path": "demo.py"}')
        view.setToolCallResult(mid, read, "class Demo: ...", ok=True)
        view.setPlan(
            mid,
            ElaChatPlan.fromMarkdown("- [x] 读实现\n- [>] 子代理查链路\n- [ ] 补测试"),
        )
        view.beginStep(mid)
        parent = view.addToolCall(
            mid, "delegate_task", '{"task": "查渲染链路"}', "multi-p1"
        )
        child = view.addToolCall(
            mid, "grep", '{"pattern": "toolRenderer"}', "multi-c1", parentId=parent
        )
        view.setToolCallResult(mid, child, "3 处匹配", ok=True)
        view.setToolCallResult(mid, parent, "链路已确认", ok=True)
        view.beginStep(mid)
        edit = view.addToolCall(
            mid,
            "edit",
            '{"path": "demo.py"}',
            "multi-e1",
            metadata={
                "files": [
                    {
                        "file": "demo.py",
                        "patch": (
                            "--- a/demo.py\n+++ b/demo.py\n"
                            "@@ -1,2 +1,3 @@\n"
                            " def render_tool(name):\n"
                            "+    return name.upper()\n"
                            "     return name\n"
                        ),
                        "additions": 1,
                        "deletions": 0,
                        "status": "modified",
                    }
                ]
            },
        )
        view.setToolCallResult(mid, edit, "ok", ok=True)
        view.setPlan(
            mid,
            ElaChatPlan.fromMarkdown("- [x] 读实现\n- [x] 子代理查链路\n- [x] 补测试"),
        )
        chat.endAssistantMessage()

    def _demo_builtins(self, chat: ElaChatWidget) -> None:
        installBuiltinToolRenderers()
        view, mid = self._start_demo(chat, "内置渲染器全家桶")
        view.beginStep(mid)
        items = (
            ("read", '{"path": "demo.py"}', "class Demo: ..."),
            ("glob", '{"pattern": "**/*.py"}', "demo.py\nchat.py"),
            ("grep", '{"pattern": "ToolCallCard"}', "tool_cards.py:51"),
            ("fetch", '{"url": "https://example.com"}', "# 示例网页"),
            ("mcp", '{"server": "filesystem"}', '{"tools": ["read_file"]}'),
            (
                "todowrite",
                '{"todos": [{"content": "读实现", "status": "completed"}, '
                '{"content": "补测试", "status": "pending"}]}',
                "ok",
            ),
        )
        for name, arguments, result in items:
            call = view.addToolCall(mid, name, arguments)
            view.setToolCallResult(mid, call, result, ok=True)
        chat.endAssistantMessage()

    def _demo_file_changes(self, chat: ElaChatWidget) -> None:
        installBuiltinToolRenderers()  # 本演示依赖 edit 的内置渲染器，别依赖点击顺序
        view, mid = self._start_demo(chat, "改一个文件")
        view.beginStep(mid)
        call = view.addToolCall(
            mid,
            "edit",
            '{"path": "demo.py"}',
            metadata={
                "files": [
                    {
                        "file": "demo.py",
                        "patch": "--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-x\n+y\n",
                        "additions": 1,
                        "deletions": 1,
                        "status": "modified",
                    }
                ]
            },
        )
        view.setToolCallResult(mid, call, "ok", ok=True)
        chat.endAssistantMessage()

    def _demo_renderer(self, chat: ElaChatWidget) -> None:
        def build(ctx):
            files = [
                item
                for item in (ctx.parsedArguments().get("files") or [])
                if isinstance(item, dict)
            ]
            return _DemoPatchBody(files)

        def subtitle(arguments):
            files = parseToolArguments(arguments).get("files")
            count = len(files) if isinstance(files, list) else 0
            return ("files", f"{count} 个文件" if count else "")

        registerToolRenderer("demo_patch", build, subtitle=subtitle, replace=True)
        view, mid = self._start_demo(chat, "富渲染")
        view.beginStep(mid)
        call = view.addToolCall(
            mid,
            "demo_patch",
            json.dumps({"files": list(_DEMO_PATCH_FILES)}, ensure_ascii=False),
        )
        # 先展开再回填结果：现场演示 updateToolResult 的推送（运行中 → 已完成）。
        self._open_tool_card(chat, mid, call)
        view.setToolCallResult(mid, call, "2 个文件已更新（+2 / −1）", ok=True)
        chat.endAssistantMessage()

    def _demo_subagent(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "让子代理查一下")
        view.beginStep(mid)
        parent = view.addToolCall(
            mid, "delegate_task", '{"task": "查工具卡"}', "demo-p1"
        )
        child = view.addToolCall(
            mid, "read", '{"path": "tool_cards.py"}', "demo-c1", parentId=parent
        )
        view.setToolCallResult(mid, child, "class ToolCallCard: ...", ok=True)
        view.setToolCallResult(mid, parent, "工具卡由卡片 + 渲染器组成", ok=True)
        chat.endAssistantMessage()

    def _demo_approval(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id=f"perm-{mid}",
                action="edit",
                resources=("demo.py",),
                detail="允许修改 demo.py？",
            ),
        )

    def _demo_question(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id=f"q-{mid}",
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="scope",
                        header="范围",
                        question="哪些目录需要一起看？",
                        options=(
                            ElaChatOption("pyqt6_ela_pro/", "组件库本体"),
                            ElaChatOption("tests/", "回归测试"),
                        ),
                        multiple=True,
                    ),
                ),
            ),
        )

    def _demo_steer(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "先看一下实现")
        view.beginStep(mid)
        view.beginText(mid)
        view.appendText(mid, "我先看看……")
        view.endText(mid)
        chat.steerMessage("等等，先别动 _column")
        view.beginStep(mid)
        chat.drainSteer()
        chat.endAssistantMessage()

    def _demo_compaction(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        part = view.beginCompaction(mid, "auto")
        view.appendCompactionSummary(mid, part, "## 目标\n- 保留关键文件路径\n")
        view.endCompaction(mid, part, "done", 24)

    def _demo_timeline(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "时间线状态")
        view.beginStep(mid)
        view.addNotice(mid, "model-switched", "已切换模型", "deepseek-v4")
        view.appendText(mid, "收到，正在处理……")
        view.setRetry(mid, 2, "上游限流，稍后重试", 0)
        view.setActivity("正在探索代码库…")
        chat.endAssistantMessage()

    def _demo_cost(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "这一轮花了多少")
        view.beginStep(mid)
        view.appendText(mid, "本轮用量如下。")
        view.setStepStats(
            mid, ElaChatStats(total_tokens=1200, cost_usd=0.02, duration_ms=2400)
        )
        chat.endAssistantMessage()
        stats = view.sessionStats(200_000)
        chat.chatInput().setContextUsage(
            stats.total_tokens, 200_000, stats.total_cost_usd
        )

    def _demo_trace(self, chat: ElaChatWidget) -> None:
        if not self.window().isVisible():
            self._status.setStatus("轨迹面板需要真实窗口；当前未显示，已跳过")
            return
        if not chat.chatView().messages():
            self._demo_multi_step(chat)
        dialog = ElaDialogBase(title="运行轨迹", parent=self.window())
        dialog.setWindowTitle("运行轨迹")
        dialog.setAutoFit(False)
        dialog.resize(900, 640)
        dialog.setLeftButtonText("关闭")
        dialog.setRightButtonText("刷新")
        panel = ElaChatTracePanel(chat.chatView(), dialog)
        panel.rowActivated.connect(chat.chatView().scrollToMessage)
        dialog.setParamWidget(panel)
        dialog.leftButtonClicked.connect(dialog.accept)
        # ElaContentDialog 的右键固定走关闭动画；刷新用面板自己的「刷新」，
        # 对话框右键隐藏，避免两个按钮都关窗口（面板内的刷新按钮要保留）。
        for button in dialog.findChildren(QPushButton):
            if button.text() == "刷新" and not panel.isAncestorOf(button):
                button.hide()
        self._dialogs.append(dialog)
        dialog.show()

    def _demo_new_topic(self, chat: ElaChatWidget) -> None:
        self._createTopic(activate=True)

    def _demo_archive(self, chat: ElaChatWidget) -> None:
        topicId = self._currentTopicId()
        if topicId:
            self._archiveTopic(topicId)

    def _demo_restore(self, chat: ElaChatWidget) -> None:
        self._restoreLastArchived()

    def _demo_shell_mode(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        input_widget.setShellMode(True)
        input_widget.setPlaceholderText("shell 模式：输入命令，Esc 退出")
        self._status.setStatus("当前话题已进入 shell 模式")

    def _demo_history_hint(self, chat: ElaChatWidget) -> None:
        self._status.setStatus("提示历史：↑/↓ 在输入区首/末块触发")


__all__ = ["ChatPlaygroundPage"]

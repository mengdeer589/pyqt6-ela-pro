"""
[pyqt6_ela_pro] 会话管理页（多话题，架构 B）

**一话题一个 ``ElaChatWidget``**，用 ``ElaTabBar`` 做话题列表、``QStackedWidget``
切页。选它是因为这个库的模型是「时间线归 ``view``」—— 一个话题的消息、
草稿、排队、滚动位置全都天然隔离，不需要自己在宿主侧做键值映射。

三件事分清：

1. **切话题不中止生成** —— 每页有独立的 mock 后端与 binder，A 话题还在流式
   时切到 B，回来 A 仍在继续；
2. **归档 = 销毁页面 + 存 bundle**（``view.exportSession()``）。必须**先
   ``binder.abortTurn(cancelBackend=True)``** 再销毁，否则后端回调会打进已释放的控件；
3. **恢复 = 重建页面 + ``view.importSession(bundle)``**，再回填草稿。

对话界面本身的形态在「聊天组件总览」页，接入方式在「输入区能力」页，
落库与崩溃恢复在「持久化与性能」页。
"""

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu, ElaTabBar

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro.chat import (
    ElaChatMockBackend,
    ElaChatReasoningStyleType,
    ElaChatSessionInfo,
    ElaChatStatusBar,
    ElaChatStreamBinder,
    ElaChatWidget,
)
from .base_page import ExamplePage
from .chat_demo_kit import note


class _TopicPage:
    """一个话题页的控件组：容器 + 聊天组件 + 假后端 + 流绑定器。"""

    def __init__(self, container, chat, mock, binder):
        self.container = container
        self.chat = chat
        self.mock = mock
        self.binder = binder


class ChatSessionPage(ExamplePage):
    """会话管理（多话题，架构 B）：一话题一 widget + ElaTabBar 话题列表。"""

    PAGE_TITLE = "会话管理"

    def __init__(self, parent=None):
        # 属性必须在 super().__init__() 之前就位：基类构造里会调 _addDemoContent
        self._sessions: dict[str, ElaChatSessionInfo] = {}
        self._pages: dict[str, _TopicPage] = {}
        self._bundles: dict[str, dict] = {}
        #: 标签下标 → 话题 id（ElaTabBar 可拖动换序，靠它保持映射）
        self._tab_ids: list[str] = []
        self._seq = 0
        self._tabs = None
        self._stack = None
        self._status = None
        self._restore_button = None
        self._style_button = None
        self._reasoning_style = ElaChatReasoningStyleType.Collapse
        super().__init__(parent)

    # -- 页面搭建 ----------------------------------------------------------

    def _addDemoContent(self, main_layout):
        self._addInfoText(
            "一话题一个 ElaChatWidget，用 ElaTabBar 做话题列表、QStackedWidget 切页。"
            "切页不会中止生成（每页独立后端），草稿 / 排队 / 滚动按话题天然隔离。",
            main_layout,
        )
        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        self._tabs = ElaTabBar(self)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tabs.tabMoved.connect(self._on_tab_moved)
        tab_row.addWidget(self._tabs, 1)
        new_button = ElaButton(
            "新建话题",
            icon=ElaIconType.IconName.CommentPlus,
            iconSize=16,
            variant="outlined",
            parent=self,
        )
        new_button.setFixedWidth(120)
        new_button.clicked.connect(self._on_new_topic_clicked)
        tab_row.addWidget(new_button)
        main_layout.addLayout(tab_row)

        self._stack = QStackedWidget(self)
        main_layout.addWidget(self._stack)

        controls = QHBoxLayout()
        archive_button = ElaButton("归档当前", variant="outlined", parent=self)
        self._restore_button = ElaButton("恢复已归档…", variant="outlined", parent=self)
        for button in (archive_button, self._restore_button):
            button.setFixedWidth(120)
        archive_button.clicked.connect(self._on_archive_clicked)
        self._restore_button.clicked.connect(self._on_restore_clicked)
        controls.addWidget(archive_button)
        controls.addWidget(self._restore_button)
        # 外观偏好是**宿主的全局设置**（架构 B：每页一个 widget，得显式传播，
        # 否则切话题会看到不同形态）；这里用一个开关演示「改了要应用到所有页」
        self._reasoning_style = "collapse"
        style_button = ElaButton("思考形态：折叠", variant="outlined", parent=self)
        style_button.setFixedWidth(140)
        self._style_button = style_button
        style_button.clicked.connect(self._on_toggle_reasoning_style)
        controls.addWidget(style_button)
        controls.addStretch()
        main_layout.addLayout(controls)

        main_layout.addWidget(
            note(
                self,
                "归档 = 销毁这一页 + 存下 exportSession 的 bundle，"
                "顺序不能反：先 binder.abortTurn(cancelBackend=True) 再销毁，"
                "否则后端回调会打进已释放的控件（importSession 会保留原消息 id，"
                "残留的迟到分片就会命中新话题里同 id 的消息）。",
            )
        )

        self._status = ElaChatStatusBar(self)
        self._status.setInfo("架构 B：一话题一 widget · 每页一个 mock 后端")
        self._status.setStatus("最近操作：—")
        main_layout.addWidget(self._status)

        self._createTopic(activate=True)

    def resizeEvent(self, event):  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_height()

    def _sync_height(self):
        """话题区占页面高度 75%（宿主布局，不属于组件）。"""
        if self._stack is None:
            return
        target = max(360, int(self.height() * 0.75))
        if self._stack.height() == target:
            return
        self._stack.setFixedHeight(target)

    # -- 话题生命周期 ------------------------------------------------------

    def _createTopic(self, title=None, bundle=None, activate=True) -> str:
        """新建话题（可带归档 bundle）；返回话题 id。"""
        self._seq += 1
        topicId = f"topic-{self._seq}"
        session = ElaChatSessionInfo(id=topicId, title=title or f"话题 {self._seq}")
        self._sessions[topicId] = session
        self._tabs.blockSignals(True)
        index = self._tabs.addTab(session.title)
        self._tabs.blockSignals(False)
        self._tab_ids.insert(index, topicId)
        if bundle is not None:
            self._bundles[topicId] = bundle
        self._refreshTab(topicId)
        if activate:
            self._activateTopic(topicId)
        return topicId

    def _pageFor(self, topicId) -> _TopicPage:
        """懒建话题页：chat + binder + mock；归档过的先 importSession + 回填草稿。"""
        topic = self._pages.get(topicId)
        if topic is not None:
            return topic
        container = QWidget(self._stack)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        chat = ElaChatWidget(container)
        layout.addWidget(chat)

        mock = ElaChatMockBackend(container, tickMs=28)
        binder = ElaChatStreamBinder(chat, worker=mock)
        # 用 Full 变体：多带一份附件，重新生成 / 重试时宿主才拿得到它
        chat.messageSubmittedFull.connect(
            lambda text, attachments: binder.startTurn(text, attachments=attachments)
        )
        mock.turnFinished.connect(binder.finish)
        # 输入区工具栏自带的「新建话题」按钮 → 宿主建新话题并切过去
        chat.newTopicRequested.connect(lambda: self._createTopic(activate=True))
        chat.cleared.connect(lambda: self._status.setStatus("当前话题上下文已清空"))
        # 标签上的条数跟着消息走（宿主列表的最简接线）
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
        # 外观偏好（宿主全局设置）在导入之后统一 apply —— 话题切换要看起来一致，
        # 不能让每个话题各带一套（bundle 里的 view 段是「导出那一刻」的快照）
        self._applyAppearance(topic)
        # 组件侧记录「本页属于哪个话题」（宿主标签栏才是权威，这里保持一致）
        chat.setCurrentSessionId(topicId)
        return topic

    # -- 外观偏好（宿主的全局设置，显式传播到每一页） ----------------------

    def _applyAppearance(self, topic: _TopicPage) -> None:
        """把宿主的全局外观偏好应用到某个话题页。"""
        view = topic.chat.chatView()
        view.setReasoningStyle(self._reasoning_style)

    def _on_toggle_reasoning_style(self):
        self._reasoning_style = (
            ElaChatReasoningStyleType.Inline
            if self._reasoning_style == ElaChatReasoningStyleType.Collapse
            else ElaChatReasoningStyleType.Collapse
        )
        label = (
            "内联" if self._reasoning_style == ElaChatReasoningStyleType.Inline else "折叠"
        )
        self._style_button.setText(f"思考形态：{label}")
        for topic in self._pages.values():
            self._applyAppearance(topic)
        self._status.setStatus(
            f"思考形态 = {self._reasoning_style}（已应用到所有话题）"
        )

    def _activateTopic(self, topicId) -> None:
        if topicId not in self._pages and topicId not in self._sessions:
            return
        topic = self._pageFor(topicId)
        index = self._tab_ids.index(topicId) if topicId in self._tab_ids else -1
        if index >= 0 and self._tabs.currentIndex() != index:
            self._tabs.setCurrentIndex(index)  # 触发 _on_tab_changed 切页
        self._stack.setCurrentWidget(topic.container)
        self._refreshTab(topicId)
        self._status.setStatus(f"已切换到「{self._sessions[topicId].title}」")

    def _archiveTopic(self, topicId) -> bool:
        """归档话题：导出 bundle（含草稿）→ 作废回合 → 销毁页面 + 移除标签。"""
        topic = self._pages.get(topicId)
        if topic is None:
            return False
        bundle = topic.chat.chatView().exportSession(
            self._sessions[topicId],
            extra={"draft": topic.chat.chatInput().text()},
        )
        self._bundles[topicId] = bundle
        # 关键：先作废回合，再让页面消失 —— 否则旧回合的迟到分片会落进
        # 恢复出来的同 id 消息（importSession 保留消息 id）
        topic.binder.abortTurn()
        topic.mock.shutdown()
        if topicId in self._tab_ids:
            index = self._tab_ids.index(topicId)
            self._tabs.blockSignals(True)
            self._tabs.removeTab(index)
            self._tabs.blockSignals(False)
            self._tab_ids.pop(index)
        self._stack.removeWidget(topic.container)
        topic.container.deleteLater()
        del self._pages[topicId]
        self._status.setStatus(
            f"已归档「{self._sessions[topicId].title}」"
            f"（{len(bundle.get('messages', ()))} 条消息 + 草稿）"
        )
        return True

    def _restoreTopic(self, topicId) -> bool:
        """恢复归档话题：标签加回来 + 重建页面 + importSession + 回填草稿。"""
        if topicId not in self._sessions or topicId in self._tab_ids:
            return False
        session = self._sessions[topicId]
        self._tabs.blockSignals(True)
        index = self._tabs.addTab(session.title)
        self._tabs.blockSignals(False)
        self._tab_ids.insert(index, topicId)
        self._activateTopic(topicId)
        self._status.setStatus(f"已恢复「{session.title}」（含草稿，消息 id 保持稳定）")
        return True

    # -- 宿主行为（按钮 / 标签栏） -----------------------------------------

    def _on_new_topic_clicked(self):
        """新建话题：新页面 + 切过去；上一个话题的生成继续在后台跑。"""
        running = any(page.chat.isGenerating() for page in self._pages.values())
        topicId = self._createTopic(activate=True)
        self._status.setStatus(
            f"已新建「{self._sessions[topicId].title}」"
            + ("（其它话题仍在生成中）" if running else "")
        )

    def _on_archive_clicked(self):
        topicId = self._currentTopicId()
        if topicId is None:
            return
        if not self._archiveTopic(topicId):
            self._status.setStatus("当前话题已归档")
            return
        self._activateNeighbor(topicId)

    def _on_restore_clicked(self):
        """恢复入口：弹出已归档话题菜单（归档后标签已移除，列表由宿主维护）。"""
        archived = [
            topicId
            for topicId in self._sessions
            if topicId not in self._tab_ids and topicId not in self._pages
        ]
        if not archived:
            self._status.setStatus("没有已归档话题")
            return
        menu = ElaMenu(self)
        for topicId in archived:
            session = self._sessions[topicId]
            count = len(self._bundles.get(topicId, {}).get("messages", ()))
            action = menu.addAction(f"{session.title}（{count} 条）")
            action.triggered.connect(
                lambda _checked=False, tid=topicId: self._restoreTopic(tid)
            )
        menu.popup(
            self._restore_button.mapToGlobal(QPoint(0, self._restore_button.height()))
        )

    def _on_tab_changed(self, index: int):
        """标签切换 → 切页（页面懒建）。"""
        if index < 0 or index >= len(self._tab_ids):
            return
        topicId = self._tab_ids[index]
        topic = self._pageFor(topicId)
        self._stack.setCurrentWidget(topic.container)
        self._refreshTab(topicId)

    def _on_tab_close_requested(self, index: int):
        """标签上的关闭键 = 归档该话题（页面销毁、可随时恢复）。"""
        if index < 0 or index >= len(self._tab_ids):
            return
        topicId = self._tab_ids[index]
        if self._archiveTopic(topicId):
            self._activateNeighbor(topicId)

    def _on_tab_moved(self, from_index: int, to_index: int):
        """标签拖动换序：同步「下标 → 话题 id」映射（页面本身按 id 找）。"""
        if not (0 <= from_index < len(self._tab_ids)):
            return
        topicId = self._tab_ids.pop(from_index)
        self._tab_ids.insert(max(0, min(to_index, len(self._tab_ids))), topicId)

    def _activateNeighbor(self, removedId: str) -> None:
        """归档后切到剩余话题；一个都不剩就新建一个（页面上总有可用话题）。"""
        remaining = [topicId for topicId in self._tab_ids if topicId != removedId]
        if remaining:
            self._activateTopic(remaining[-1])
        else:
            self._createTopic(activate=True, title="话题 1")

    # -- 标签同步 ----------------------------------------------------------

    def _currentTopicId(self):
        index = self._tabs.currentIndex() if self._tabs is not None else -1
        if 0 <= index < len(self._tab_ids):
            return self._tab_ids[index]
        return None

    def _refreshTab(self, topicId) -> None:
        """标签文本 = 标题 +（消息数）—— 宿主话题列表的最简形态。"""
        if topicId not in self._tab_ids:
            return
        index = self._tab_ids.index(topicId)
        topic = self._pages.get(topicId)
        count = len(topic.chat.chatView().messages()) if topic is not None else 0
        self._sessions[topicId] = self._sessions[topicId].withMessageCount(count)
        self._tabs.setTabText(index, f"{self._sessions[topicId].title}（{count} 条）")
        self._tabs.setTabToolTip(
            index, f"{self._sessions[topicId].title}\n{count} 条消息"
        )

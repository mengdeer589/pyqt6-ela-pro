"""AI 组件工作台：ElaPivot 切七个工作区，首次切换才构建。

各工作区仍是独立 ``ExamplePage``（自带滚动区），工作台只负责切换。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaPivot, ElaText

from pyqt6_ela_pro import ElaThemeWidget

from .base_page import ExamplePage
from .chat_agent_page import ChatAgentPage
from .chat_files_page import ChatFilesPage
from .chat_input_page import ChatInputPage
from .chat_overview_page import ChatOverviewPage
from .chat_persist_page import ChatPersistPage
from .chat_session_page import ChatSessionPage
from .chat_timeline_page import ChatTimelinePage


class ChatWorkbenchPage(ExamplePage):
    """AI 组件工作台：概览 / 输入区 / Agent / 文件与 Diff / 时间线 / 会话 / 持久化。"""

    PAGE_TITLE = "AI 组件工作台"

    #: 工作区：(名称, 说明, 页面类)
    WORKSPACES = (
        (
            "概览",
            "一条预填的完整回合 + 外观开关：推理、正文、工具面板、统计徽标、"
            "底部行动作与免责声明。",
            ChatOverviewPage,
        ),
        (
            "输入区",
            "命令 / 选择器 / shell 模式 / 历史与草稿 / 大段粘贴 / 队列排序 / "
            "插话 / 待发送 / @ 提及。",
            ChatInputPage,
        ),
        (
            "Agent",
            "工具卡渲染器与审批：批准型、问答型向导、插话、压缩分隔卡、"
            "会话统计与上下文占用。",
            ChatAgentPage,
        ),
        (
            "文件与 Diff",
            "模型改了文件之后用户看到什么：单文件 diff、多文件列表、长 diff "
            "折叠与截断、shell 控制台、write / patch。",
            ChatFilesPage,
        ),
        (
            "时间线与检索",
            "回答之外的时间线语义：通知、自动重试、运行态活动行、密度、"
            "逐段披露、会话内搜索、消息身份与 @ 提及。",
            ChatTimelinePage,
        ),
        (
            "会话",
            "多话题架构 B：一话题一个 ElaChatWidget，切换不中止生成，"
            "归档与恢复走 exportSession / importSession。",
            ChatSessionPage,
        ),
        (
            "持久化",
            "回合日志重放、会话导出 / 导入、大消息量三条开关、"
            "密度 / 披露 / 草稿的持久化。",
            ChatPersistPage,
        ),
    )

    def __init__(self, parent=None):
        self._workspaces: list[dict] = []
        self._active_workspace = 0
        self._pivot_syncing = False
        super().__init__(parent)

    # ── 工作台外壳 ──────────────────────────────────────────────────────

    def _setupUI(self):
        super()._setupUI()
        root = self.layout()
        root.removeWidget(self._scrollArea)
        self._scrollArea.hide()
        self._scrollArea.deleteLater()
        self._build_workbench(root)

    def _build_workbench(self, root_layout):
        """顶部标题 / 分页 + 每个工作区一个独立页面（首次切换才实例化）。"""
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = ElaThemeWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 10)
        header_layout.setSpacing(9)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = ElaText("AI 组件工作台", header)
        title.setTextPixelSize(22)
        font = QFont()
        font.setPixelSize(22)
        font.setBold(True)
        title.setFont(font)
        title_row.addWidget(title)
        subtitle = ElaText("ElaChatWidget · 回合 / 工具 / 审批 / 持久化", header)
        subtitle.setTextPixelSize(13)
        subtitle.setWordWrap(False)
        title_row.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignBottom)
        title_row.addStretch()
        hint = ElaText("预填 + 可重播 · 首次切换才构建", header)
        hint.setTextPixelSize(12)
        hint.setWordWrap(False)
        title_row.addWidget(hint, 0, Qt.AlignmentFlag.AlignBottom)
        header_layout.addLayout(title_row)

        self._pivot = ElaPivot(header)
        self._pivot.setTextPixelSize(14)
        for name, _desc, _page_cls in self.WORKSPACES:
            self._pivot.appendPivot(name)
        self._pivot.setCurrentIndex(0)
        self._pivot.pivotClicked.connect(self._onWorkspaceChanged)
        header_layout.addWidget(self._pivot)

        self._desc_label = ElaText("", header)
        self._desc_label.setTextPixelSize(13)
        self._desc_label.setWordWrap(True)
        header_layout.addWidget(self._desc_label)
        root_layout.addWidget(header)

        self._stack = QStackedWidget(self)
        for name, desc, page_cls in self.WORKSPACES:
            placeholder = QWidget(self._stack)
            self._stack.addWidget(placeholder)
            self._workspaces.append(
                {
                    "name": name,
                    "desc": desc,
                    "page_cls": page_cls,
                    "page": None,
                    "placeholder": placeholder,
                }
            )
        root_layout.addWidget(self._stack, 1)
        self._apply_workspace_text(0)

    def buildDemoContent(self):
        """首个工作区立即构建；其余在首次切换时惰性构建。"""
        if self._demo_built:
            return
        self._demo_built = True
        self._activate_workspace(0)

    def _onWorkspaceChanged(self, index: int):
        if self._pivot_syncing or index < 0:
            return
        self._activate_workspace(index)

    def _activate_workspace(self, index: int):
        if not 0 <= index < len(self._workspaces):
            return
        self._active_workspace = index
        workspace = self._workspaces[index]
        if workspace["page"] is None:
            page = workspace["page_cls"](self._stack)
            placeholder = workspace["placeholder"]
            self._stack.insertWidget(index, page)
            self._stack.removeWidget(placeholder)
            placeholder.deleteLater()
            workspace["page"] = page
            workspace["placeholder"] = None
            # 页面自带滚动区，内容在首次 show 时构建；这里先建好，
            # 避免切过去的第一帧是空页。
            page.buildDemoContent()
        self._stack.setCurrentIndex(index)
        if self._pivot.getCurrentIndex() != index:
            self._pivot_syncing = True
            try:
                self._pivot.setCurrentIndex(index)
            finally:
                self._pivot_syncing = False
        self._apply_workspace_text(index)

    def _apply_workspace_text(self, index: int):
        self._desc_label.setText(self._workspaces[index]["desc"])


__all__ = ["ChatWorkbenchPage"]

"""AI 组件实验台：多话题聊天 + 引导场景 + 右侧 ElaSplitter 面板。"""

from __future__ import annotations

import json
import os
import time
import traceback
from typing import Callable, Optional

from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
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

from pyqt6_ela_pro import (
    ElaButton,
    ElaDialogBase,
    ElaMarkdownViewer,
    ElaSplitter,
    ElaThemeWidget,
)
from pyqt6_ela_pro._internal import is_deleted, safe_connect, single_shot_on
from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro._theme import ElaSeverity, severityColor
from pyqt6_ela_pro.chat import (
    DISCLAIMER_TEXT,
    ElaChatDetailDepthType,
    ElaChatDetailPlacementType,
    ElaChatFileChanges,
    ElaChatMention,
    ElaChatMockBackend,
    ElaChatOption,
    ElaChatPermission,
    ElaChatPlan,
    ElaChatPromptHistory,
    ElaChatQuestion,
    ElaChatRoleType,
    ElaChatSelector,
    ElaChatSelectorItem,
    ElaChatSessionInfo,
    ElaChatStats,
    ElaChatStatusBar,
    ElaChatStreamBinder,
    ElaChatSuggestion,
    ElaChatTimelineDetail,
    ElaChatToolStatusType,
    ElaChatTracePanel,
    ElaChatTurnJournal,
    ElaChatWidget,
    ModelPricing,
    formatCost,
    installBuiltinToolRenderers,
    registerToolRenderer,
    stats_cost,
)
from pyqt6_ela_pro.chat.blocks import ToolCallCard
from pyqt6_ela_pro.chat.renderers import parseToolArguments
from ._step_player import _ScriptPlayer
from .base_page import ExamplePage

#: 右侧特性面板默认宽度
FEATURE_PANEL_WIDTH = 420

_DEMO_MENTIONS = (
    ElaChatSuggestion(
        id="demo.py",
        label="demo.py",
        description="演示文件",
        insert_text="@demo.py ",
        kind="file",
    ),
    ElaChatSuggestion(
        id="chat/",
        label="chat/",
        description="聊天组件目录",
        insert_text="@chat/ ",
        kind="file",
    ),
)
_DEMO_COMMANDS = (
    ElaChatSuggestion(
        id="clear",
        label="/clear",
        description="清空上下文（交宿主处理）",
        insert_text="/clear ",
    ),
    ElaChatSuggestion(
        id="help",
        label="/help",
        description="列出演示命令",
        insert_text="/help ",
    ),
)


def _demo_mention_items(query: str):
    query = (query or "").lower()
    return [item for item in _DEMO_MENTIONS if query in item.label.lower()]


def _demo_command_items(query: str):
    query = (query or "").lower()
    return [item for item in _DEMO_COMMANDS if query in item.label.lower()]


def _always_open(*_args, **_kwargs) -> bool:
    return True


def _always_closed(*_args, **_kwargs) -> bool:
    return False


_AVATAR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    '<rect width="64" height="64" rx="14" fill="#2563eb"/>'
    '<circle cx="23" cy="26" r="9" fill="#fff"/>'
    '<circle cx="41" cy="26" r="9" fill="#fff"/>'
    '<rect x="20" y="42" width="24" height="5" rx="2.5" fill="#fff"/>'
    "</svg>"
)

#: mock 后端的富 Markdown 回答（让「真实流式回合」有内容可看）
_RICH_REPLY = """## 完整回合演示

这条回答由 `ElaChatMockBackend` 流式输出，经过 `ElaChatStreamBinder` 落到步骤 / 工具 / 统计。

- 思考段 → 工具面板 → 正文
- 行内代码 `ElaChatWidget` 与公式 $E=mc^2$
- 引用与高亮：> 组件只负责表达，业务归宿主

| 能力 | 说明 |
|---|---|
| 流式 | 分片提交，不阻塞 UI |
| 工具 | read / grep / edit 生命周期 |
| 统计 | 词元 / 耗时 / 成本 |

```python
def hello():
    print("pyqt6_ela_pro")
```
"""

_ASYNC_WORKER_DOC = """## 真实后端接入

`ElaChatAsyncWorker` 是 QThread + asyncio + 命令队列的后端基类；子类只实现
`_setup()` / `_stream_turn()` / 可选的 `_rollback_turn()`：

```python
class AgentWorker(ElaChatAsyncWorker):
    async def _setup(self):
        self.ready.emit()

    def _stream_turn(self, prompt, attachments):
        yield chunk
```

```python
worker = AgentWorker()
binder = ElaChatStreamBinder(chat, worker=worker)
binder.shutdownOnClose(window)
```

完整示例见「AI 接入指南」页的 `AgentWorker`；本页演示统一用
`ElaChatMockBackend`，避免示例依赖真实模型服务。
"""


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
        self.cycles: dict[str, int] = {}
        self.draft_state = None
        self.pending_id = None
        self.error_id = None
        self.plan_retry_id = None
        self.dock_widget = None
        self.custom_picker = False


class ChatPlaygroundPage(ExamplePage):
    """标准多话题聊天页；右侧面板分「快速体验」场景与 API 实验台。"""

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
        self._feature_feedback: Optional[ColorText] = None
        self._status: Optional[ElaChatStatusBar] = None
        self._feature_width = FEATURE_PANEL_WIDTH
        self._dialogs: list = []
        self._reasoning_style = "collapse"
        self._player: Optional[_ScriptPlayer] = None
        self._scenario_labels: dict = {}
        self._active_scenario = ""
        self._gallery_dialog = None
        super().__init__(parent)
        self._player = _ScriptPlayer(self)

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
        title = ElaText("AI 组件", header)
        title.setTextPixelSize(20)
        font = QFont()
        font.setPixelSize(20)
        font.setBold(True)
        title.setFont(font)
        header_layout.addWidget(title)
        subtitle = ElaText("多话题 · 场景演示 · API 实验台", header)
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
        gallery_button = ElaButton(
            "组件画廊",
            icon=ElaIconType.IconName.Shapes,
            variant="outlined",
            parent=header,
        )
        gallery_button.setFixedWidth(120)
        safe_connect(
            gallery_button,
            "clicked",
            lambda _=False: self._open_gallery(),
            "playground.gallery",
            receiver=gallery_button,
        )
        header_layout.addWidget(gallery_button)
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
        self._status.setInfo("多话题 · 场景演示 · API 实验台")
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
        hint = ColorText("场景演示 / API 调试", panel)
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
            if name == "快速体验":
                self._feature_stack.addWidget(self._build_scenario_tab(features))
            else:
                self._feature_stack.addWidget(self._build_feature_tab(features))
        self._feature_pivot.setCurrentIndex(0)
        safe_connect(
            self._feature_pivot,
            "pivotClicked",
            self._on_feature_tab,
            "playground.feature_tab",
            receiver=self._feature_pivot,
        )
        layout.addWidget(self._feature_pivot)
        self._feature_feedback = ColorText("", panel)
        self._feature_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self._feature_feedback.setTextPixelSize(12)
        self._feature_feedback.setWordWrap(True)
        layout.addWidget(self._feature_feedback)
        layout.addWidget(self._feature_stack, 1)
        return panel

    def _feature_tabs(self):
        """``(tab 名, ((标题, 说明, 方法, 需要空闲), ...))``。"""
        return (
            (
                "快速体验",
                (
                    (
                        "引导 · 流式回合",
                        "输入 → mock 逐字输出 → 工具面板 → 统计",
                        self._scenario_streaming,
                        True,
                    ),
                    (
                        "引导 · 批准审批",
                        "弹出审批卡，点允许 / 拒绝后自动回填结果",
                        self._scenario_approval,
                        False,
                    ),
                    (
                        "引导 · 问答审批",
                        "两题向导 + 多选 / 自定义答案",
                        self._scenario_question,
                        False,
                    ),
                    (
                        "引导 · 工具链",
                        "逐步展开 read → grep → edit（真实 diff）",
                        self._scenario_tools,
                        True,
                    ),
                    (
                        "引导 · 消息操作",
                        "展开操作栏，撤回 / 重新生成真的可用",
                        self._scenario_actions,
                        False,
                    ),
                    (
                        "引导 · 输入区",
                        "@ 引用 / 附件 / 补全 / 发送",
                        self._scenario_input,
                        False,
                    ),
                ),
            ),
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
                    (
                        "步骤 / 流式状态",
                        "stepCount / toolPanels / streamingMessageId",
                        self._demo_step_handles,
                        True,
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
                    (
                        "工具分组",
                        "连续上下文工具合并为分组卡",
                        self._demo_tool_grouping,
                        False,
                    ),
                    (
                        "工具默认开合",
                        "默认 / 全展开 / 全收起 三档策略",
                        self._demo_tool_default_open,
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
                "消息",
                (
                    (
                        "通知 / 重试 / 活动行",
                        "三种不占正文的时间线状态",
                        self._demo_timeline,
                        False,
                    ),
                    (
                        "时间线密度",
                        "hidden / collapsed / expanded 六分区",
                        self._demo_timeline_detail,
                        False,
                    ),
                    (
                        "分段展开",
                        "setPartExpanded 覆盖密度默认值",
                        self._demo_part_expand,
                        False,
                    ),
                    (
                        "活动行 provider",
                        "binder.setActivityProvider / setAutoActivity",
                        self._demo_activity_provider,
                        False,
                    ),
                    (
                        "消息元信息",
                        "身份 / 标题 / 时间 / 耗时 / @ 区间 / 附件",
                        self._demo_message_meta,
                        False,
                    ),
                    (
                        "变更汇总",
                        "changeSummaryEnabled / turnChanges",
                        self._demo_change_summary,
                        False,
                    ),
                    (
                        "错误卡 / 重试",
                        "setMessageError → 错误卡 + 重试",
                        self._demo_message_error,
                        False,
                    ),
                    (
                        "待发送消息",
                        "addPendingUserMessage → resolve",
                        self._demo_pending_user,
                        False,
                    ),
                    (
                        "消息操作",
                        "撤回 / 重新生成 / 重试 / 删除 / 批量删除",
                        self._demo_message_actions,
                        True,
                    ),
                    (
                        "自定义消息动作",
                        "actions(messageId).addCustomAction",
                        self._demo_custom_action,
                        False,
                    ),
                    (
                        "气泡句柄",
                        "header / meta / footer / actions / parts",
                        self._demo_bubble_handles,
                        False,
                    ),
                    (
                        "清空计划 / 重试",
                        "clearPlan / clearRetry",
                        self._demo_clear_plan_retry,
                        False,
                    ),
                ),
            ),
            (
                "外观",
                (
                    (
                        "统计徽标",
                        "footer / steps / none",
                        self._demo_stats_mode,
                        False,
                    ),
                    (
                        "推理样式",
                        "collapse / inline",
                        self._demo_reasoning_style,
                        False,
                    ),
                    (
                        "免责声明",
                        "显示 / 隐藏 / 自定义文案",
                        self._demo_disclaimer,
                        False,
                    ),
                    (
                        "复制提示",
                        "setCopyNotificationEnabled",
                        self._demo_copy_notification,
                        False,
                    ),
                    (
                        "等待骨架",
                        "setWaitingPlaceholderEnabled",
                        self._demo_waiting_placeholder,
                        False,
                    ),
                    (
                        "头像 / 形状",
                        "自定义 SVG / 圆角 / 方形 / 隐藏",
                        self._demo_avatars,
                        False,
                    ),
                    (
                        "用户气泡宽度",
                        "0.9 → 0.7 → 0.5",
                        self._demo_user_bubble_width,
                        False,
                    ),
                    (
                        "内容宽度",
                        "不限 / 760 / 600",
                        self._demo_content_width,
                        False,
                    ),
                    (
                        "空态建议",
                        "标题 / 副标题 / 建议按钮",
                        self._demo_empty_state,
                        False,
                    ),
                    (
                        "滚动行为",
                        "贴底 / 阈值 / 滚动条策略",
                        self._demo_scroll_behavior,
                        False,
                    ),
                ),
            ),
            (
                "输入",
                (
                    (
                        "命令 / @ 引用",
                        "输入 / 或 @ 触发补全",
                        self._demo_completion,
                        False,
                    ),
                    (
                        "附件",
                        "add / set / clear + 附件条计数",
                        self._demo_attachments,
                        False,
                    ),
                    (
                        "文件选择器",
                        "setFilePicker 自定义回形针",
                        self._demo_file_picker,
                        False,
                    ),
                    (
                        "MIME 判定",
                        "acceptsMime / attachMime",
                        self._demo_mime,
                        False,
                    ),
                    (
                        "发送键行为",
                        "Enter 发送 / 行数 / 按钮文案",
                        self._demo_send_behavior,
                        False,
                    ),
                    (
                        "程序化提交",
                        "submit / text / setText",
                        self._demo_submit,
                        True,
                    ),
                    (
                        "草稿快照",
                        "draftState / setDraftState",
                        self._demo_draft,
                        False,
                    ),
                    (
                        "提示历史",
                        "↑/↓ 浏览草稿",
                        self._demo_history_hint,
                        False,
                    ),
                    (
                        "Shell 模式",
                        "等宽字体 / Esc 退出 / shellSubmitted",
                        self._demo_shell_mode,
                        False,
                    ),
                    (
                        "排队消息",
                        "enqueueMessage → 队列 dock",
                        self._demo_queue,
                        False,
                    ),
                    (
                        "队列 / 插话开关",
                        "setQueueEnabled / autoSend / steer",
                        self._demo_queue_toggles,
                        False,
                    ),
                    (
                        "工具栏扩展",
                        "toolBar().addButton 自定义按钮",
                        self._demo_toolbar_extension,
                        False,
                    ),
                    (
                        "工具栏显隐",
                        "addFile / clear / newTopic / usage",
                        self._demo_toolbar_visibility,
                        False,
                    ),
                    (
                        "用户 / 助手名",
                        "setUserName / setAssistantName",
                        self._demo_names,
                        False,
                    ),
                    (
                        "输入区替换",
                        "setDockWidget / clearDock",
                        self._demo_input_dock,
                        False,
                    ),
                ),
            ),
            (
                "会话 / 高级",
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
                    (
                        "会话搜索",
                        "showSearchBar / Ctrl+F 命中高亮",
                        self._demo_search,
                        False,
                    ),
                    (
                        "程序化发送",
                        "sendUserMessage + 生成态",
                        self._demo_send_message,
                        True,
                    ),
                    (
                        "严格 ID",
                        "setStrictIds 暴露宿主传错 id",
                        self._demo_strict_ids,
                        False,
                    ),
                    (
                        "虚拟化开关",
                        "parts / shell / list / 挂起 / resize",
                        self._demo_virtualization,
                        False,
                    ),
                    (
                        "物化 / 定位",
                        "materializeMessage + scrollToMessage",
                        self._demo_materialize,
                        False,
                    ),
                    (
                        "回合日志",
                        "ElaChatTurnJournal 序列化 + 重放",
                        self._demo_journal,
                        False,
                    ),
                    (
                        "计价换算",
                        "ModelPricing / stats_cost / formatCost",
                        self._demo_pricing,
                        False,
                    ),
                    (
                        "真实后端接入",
                        "ElaChatAsyncWorker 接入说明",
                        self._demo_async_worker,
                        False,
                    ),
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
                self._feature_button_text(title),
                variant="outlined",
                size="small",
                parent=section,
            )
            button.setFixedWidth(64)
            safe_connect(
                button,
                "clicked",
                lambda _=False, fn=method, idle=needs_idle, name=title: (
                    self._run_feature(fn, idle, name)
                ),
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

    @staticmethod
    def _feature_button_text(title: str) -> str:
        """按演示类型给按钮一个具体动作名，不再全部叫「插入」。"""
        if title in ("运行轨迹", "真实后端接入", "会话搜索", "组件画廊"):
            return "打开"
        toggle_keys = (
            "开关",
            "显隐",
            "样式",
            "模式",
            "宽度",
            "头像",
            "分组",
            "开合",
            "密度",
            "名称",
            "严格 ID",
            "虚拟化",
            "行为",
            "通知",
            "骨架",
            "免责声明",
            "变更汇总",
            "统计徽标",
        )
        if any(key in title for key in toggle_keys):
            return "切换"
        return "插入"

    def _build_scenario_tab(self, features) -> QWidget:
        """「快速体验」：每张卡按脚本播放一段可交互场景。"""
        scroll = ElaScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(14)

        for title, hint, method, _needs_idle in features:
            card = QWidget(content)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(5)
            head = QHBoxLayout()
            head.setSpacing(8)
            label = ColorText(title, card)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextPixelSize(13)
            label.setTextWeight(QFont.Weight.DemiBold)
            head.addWidget(label, 1)
            replay = ElaButton("重放", variant="text", size="small", parent=card)
            replay.setFixedWidth(52)
            safe_connect(
                replay,
                "clicked",
                lambda _=False, fn=method, name=title: self._start_scenario(
                    name, fn, replay=True
                ),
                "playground.scenario_replay",
                receiver=replay,
            )
            head.addWidget(replay)
            card_layout.addLayout(head)
            note = ColorText(hint, card)
            note.setTextFormat(Qt.TextFormat.PlainText)
            note.setTextPixelSize(12)
            note.setWordWrap(True)
            card_layout.addWidget(note)
            start = ElaButton(
                "开始演示",
                variant="solid",
                color="primary",
                size="small",
                parent=card,
            )
            start.setFixedWidth(96)
            safe_connect(
                start,
                "clicked",
                lambda _=False, fn=method, name=title: self._start_scenario(name, fn),
                "playground.scenario_start",
                receiver=start,
            )
            card_layout.addWidget(start)
            progress = ColorText("就绪", card)
            progress.setTextFormat(Qt.TextFormat.PlainText)
            progress.setTextPixelSize(11)
            progress.setWordWrap(True)
            card_layout.addWidget(progress)
            self._scenario_labels[title] = progress
            layout.addWidget(card)

        clear = ElaButton(
            "清除当前话题", variant="outlined", size="small", parent=content
        )
        clear.setFixedWidth(120)
        safe_connect(
            clear,
            "clicked",
            lambda _=False: self._clear_current_topic(),
            "playground.scenario_clear",
            receiver=clear,
        )
        layout.addWidget(clear)
        layout.addStretch(1)
        scroll.setWidget(content)
        content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        return scroll

    def _start_scenario(
        self, title: str, method: Callable, replay: bool = False
    ) -> None:
        """启动 / 重放一个引导场景；重放始终开新话题，不污染当前会话。"""
        chat = self._active_chat()
        if replay or chat is None or chat.isGenerating():
            self._createTopic(title=title, activate=True)
            chat = self._active_chat()
        if chat is None:
            return
        self._player.stop()
        self._active_scenario = title
        self._set_scenario_feedback(title, "播放中…")
        try:
            method(chat)
        except Exception:
            traceback.print_exc()
            self._set_scenario_feedback(title, "失败（见控制台）", error=True)
            self._status.setBusy(False)

    def _set_scenario_feedback(
        self, title: str, text: str, error: bool = False
    ) -> None:
        label = self._scenario_labels.get(title)
        if label is None or is_deleted(label):
            return
        label.setText(text)
        label.setTextColor(
            severityColor(self._theme_mode, ElaSeverity.Error) if error else None
        )

    def _clear_current_topic(self) -> None:
        chat = self._active_chat()
        if chat is None:
            return
        topic = self._active_page()
        chat.clear()
        chat.chatInput().clear()
        if topic is not None:
            topic.mock.reset()
        self._status.setStatus("已清除当前话题的消息与后端会话")
        self._set_feature_feedback("已清除当前话题")

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
        input_widget = chat.chatInput()
        mode_selector = ElaChatSelector(
            "模式",
            [
                ElaChatSelectorItem(
                    id="agent",
                    label="Agent",
                    icon=ElaIconType.IconName.Robot,
                ),
                ElaChatSelectorItem(
                    id="plan",
                    label="Plan",
                    icon=ElaIconType.IconName.ListCheck,
                ),
            ],
            "agent",
            input_widget.inputSurface(),
        )
        safe_connect(
            mode_selector,
            "selectionChanged",
            lambda value: self._status.setStatus(f"输入区模式：{value}"),
            "playground.selector",
            receiver=mode_selector,
        )
        chat.toolBar().addWidget(mode_selector, zone="leading", key="mode")
        input_widget.setHistory(ElaChatPromptHistory())
        input_widget.setMentionProvider(_demo_mention_items)
        input_widget.setCommandProvider(_demo_command_items)
        input_widget.setCommandSubmitMode("signal")
        safe_connect(
            chat,
            "commandSubmitted",
            lambda text: self._handle_command(chat, text),
            "playground.command",
            receiver=chat,
        )
        safe_connect(
            chat,
            "mentionSelected",
            lambda mid, label: self._status.setStatus(f"引用：{label}（{mid}）"),
            "playground.mention",
            receiver=chat,
        )
        safe_connect(
            chat,
            "suggestionClicked",
            lambda text: self._submit_suggestion(chat, text),
            "playground.suggestion",
            receiver=chat,
        )
        safe_connect(
            chat,
            "shellSubmitted",
            lambda text: self._handle_shell(chat, text),
            "playground.shell",
            receiver=chat,
        )
        safe_connect(
            chat,
            "attachmentsChanged",
            lambda items: self._status.setStatus(f"附件变化：{len(items)} 项"),
            "playground.attachments",
            receiver=chat,
        )
        safe_connect(
            chat,
            "filesAdded",
            lambda paths: self._status.setStatus(f"文件进入输入区：{len(paths)} 个"),
            "playground.files",
            receiver=chat,
        )
        safe_connect(
            input_widget,
            "addFileRequested",
            lambda: self._status.setStatus("点击了「添加文件」按钮"),
            "playground.add_file",
            receiver=input_widget,
        )
        safe_connect(
            chat,
            "contextUsageClicked",
            lambda: self._show_context_usage(chat),
            "playground.usage_clicked",
            receiver=chat,
        )
        mock = ElaChatMockBackend(container, tickMs=24)
        mock.setReplyProvider(lambda _question: _RICH_REPLY)
        binder = ElaChatStreamBinder(chat, worker=mock)
        self._wire_host_contract(chat, mock, binder)
        safe_connect(
            chat,
            "messageSubmittedFull",
            lambda text, attachments, b=binder: b.startTurn(
                text, attachments=attachments
            ),
            "playground.submit",
            receiver=chat,
        )
        safe_connect(
            mock,
            "turnFinished",
            binder.finish,
            "playground.mock_finish",
            receiver=mock,
        )
        safe_connect(
            chat,
            "newTopicRequested",
            lambda: self._createTopic(activate=True),
            "playground.new_topic_signal",
            receiver=chat,
        )
        safe_connect(
            chat,
            "cleared",
            lambda: self._status.setStatus("当前话题上下文已清空"),
            "playground.cleared",
            receiver=chat,
        )
        safe_connect(
            chat.chatView(),
            "messageAdded",
            lambda *_args, tid=topicId: self._refreshTab(tid),
            "playground.message_added",
            receiver=chat.chatView(),
        )
        view = chat.chatView()
        view.setEmptyTitle("AI 组件实验台")
        view.setEmptySubtitle("从右侧选一个场景，或在输入区直接发消息")
        view.setSuggestions(["跑一条完整回合", "看看工具调用与 diff", "演示审批与提问"])
        topic = _TopicPage(container=container, chat=chat, mock=mock, binder=binder)
        self._pages[topicId] = topic
        self._stack.addWidget(container)
        bundle = self._bundles.get(topicId)
        if bundle is not None:
            view.importSession(bundle)
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

    def _topic_for_chat(self, chat: ElaChatWidget) -> Optional[_TopicPage]:
        for topic in self._pages.values():
            if topic.chat is chat:
                return topic
        return None

    def _drop_pending_permission(self, chat) -> None:
        """撤掉 dock 上的审批卡并删掉对应待答消息（避免留下永久「生成中」）。"""
        chat.clearPermissionDock()
        view = chat.chatView()
        for message in reversed(view.messages()):
            bubble = view.bubble(message.id)
            if bubble is not None and bubble.pendingPermissionParts():
                chat.removeMessage(message.id)
                return

    def _wire_host_contract(self, chat, mock, binder) -> None:
        """把 ElaChatWidget 的宿主信号接到真实行为（对齐 chat_guide_page 的 DemoWindow）。"""
        safe_connect(
            chat,
            "stopRequested",
            lambda: self._stop_topic(mock, binder),
            "playground.stop",
            receiver=chat,
        )
        safe_connect(
            chat,
            "undoRequested",
            lambda mid: self._undo_message(chat, mock, binder, mid),
            "playground.undo",
            receiver=chat,
        )
        safe_connect(
            chat,
            "regenerateRequested",
            lambda mid: self._regenerate_message(chat, mock, binder, mid),
            "playground.regenerate",
            receiver=chat,
        )
        safe_connect(
            chat,
            "retryRequested",
            lambda mid: self._retry_message(chat, mock, binder, mid),
            "playground.retry",
            receiver=chat,
        )
        safe_connect(
            chat,
            "attachmentClicked",
            lambda _mid, path: self._open_attachment(path),
            "playground.attachment_clicked",
            receiver=chat,
        )
        safe_connect(
            chat,
            "generationStarted",
            lambda mid: self._on_generation_started(chat, mid),
            "playground.generation_started",
            receiver=chat,
        )
        safe_connect(
            chat,
            "generationFinished",
            lambda mid, status: self._on_generation_finished(chat, mid, status),
            "playground.generation_finished",
            receiver=chat,
        )
        safe_connect(
            chat,
            "permissionReplied",
            lambda *args: self._on_permission_replied(chat, *args),
            "playground.permission_replied",
            receiver=chat,
        )

    def _stop_topic(self, mock, binder) -> None:
        binder.cancel()
        mock.cancel()
        self._status.setBusy(False)
        self._status.setStatus("已停止生成（保留已输出内容）")
        self._set_feature_feedback("已停止：当前回合保留已输出内容")

    def _undo_message(self, chat, mock, binder, messageId: int) -> None:
        binder.cancel()
        mock.cancel()
        message = chat.undoMessage(messageId)
        if message is None:
            self._status.setStatus(f"没有可撤回的消息 #{messageId}")
            return
        self._status.setStatus(f"已撤回消息 #{message.id}，原文回填输入区")
        self._set_feature_feedback(f"已撤回消息 #{message.id}")
        if self._active_scenario:
            title, self._active_scenario = self._active_scenario, ""
            self._set_scenario_feedback(title, f"已撤回消息 #{message.id}")

    def _regenerate_message(self, chat, mock, binder, messageId: int) -> None:
        binder.cancel()
        mock.cancel()
        message = chat.regenerateFrom(messageId)
        if message is None:
            self._status.setStatus("没有可重新生成的回答")
            return
        started = binder.startTurn(
            message.text, regenerate=True, attachments=message.attachments
        )
        self._status.setStatus(
            "正在重新生成" if started is not None else "后端未受理重新生成"
        )

    def _retry_message(self, chat, mock, binder, messageId: int) -> None:
        binder.cancel()
        mock.cancel()
        message = chat.retryMessage(messageId)
        if message is None:
            self._status.setStatus("没有可重试的提问")
            return
        started = binder.startTurn(message.text, attachments=message.attachments)
        self._status.setStatus("正在重试" if started is not None else "后端未受理重试")

    def _on_generation_started(self, chat, messageId: int) -> None:
        if chat is not self._active_chat():
            return
        self._status.setBusy(True)
        self._status.setStatus("生成中…", level="busy")

    def _on_generation_finished(self, chat, messageId: int, status: str) -> None:
        if chat is not self._active_chat():
            return
        self._status.setBusy(False)
        if status == "error":
            self._status.setStatus("生成出错（错误卡上可重试）", level="error")
        elif self._status.level() == "busy":
            # 只覆盖「生成中」；演示方法自己写的结果文案保留
            self._status.setStatus("生成完成", level="success")
        if self._active_scenario:
            title, self._active_scenario = self._active_scenario, ""
            self._set_scenario_feedback(title, "已完成，可点「重放」再看一遍")

    def _on_permission_replied(
        self,
        chat,
        messageId: int,
        requestId: str,
        reply: str,
        answer: str,
        feedback: str,
    ) -> None:
        if reply == "cancelled":
            self._status.setStatus("审批已取消（消息删除 / dock 撤下）")
            return
        labels = {
            "allowed": "已允许一次",
            "always": "已允许并记住",
            "rejected": "已拒绝",
            "cancelled": "已取消",
        }
        if answer:
            label = "已提交答案"
        else:
            label = labels.get(reply, f"已提交（{reply}）")
        detail = f"：{answer or feedback}" if (answer or feedback) else ""
        chat.chatView().addMessage(
            ElaChatRoleType.Assistant, f"审批结果：{label}{detail}"
        )
        # 审批消息用 beginMessage 建的，等回复期间一直显示「生成中」
        chat.endAssistantMessage(messageId)
        self._status.setStatus(f"审批已回传：{label}{detail}")
        if self._active_scenario in ("引导 · 批准审批", "引导 · 问答审批"):
            self._set_scenario_feedback(self._active_scenario, f"已收到回复：{label}")
            self._active_scenario = ""

    def _submit_suggestion(self, chat, text: str) -> None:
        input_widget = chat.chatInput()
        input_widget.setText(text)
        if input_widget.submit():
            self._status.setStatus(f"已发送建议：{text}")
        else:
            self._status.setStatus("建议未能发送（后端未就绪或输入被占用）")

    def _handle_command(self, chat, text: str) -> None:
        input_widget = chat.chatInput()
        command = (text or "").strip().split(" ", 1)[0].lower()
        if command == "/clear":
            topic = self._topic_for_chat(chat)
            input_widget.clear()
            chat.clear()
            if topic is not None:
                topic.mock.reset()
            self._status.setStatus("已执行 /clear：消息与后端会话已清空")
            return
        if command == "/help":
            input_widget.clear()
            chat.chatView().addMessage(
                ElaChatRoleType.System,
                "可用命令：\n/clear  清空当前话题\n"
                "/help   显示这份说明\n"
                "其它输入按普通消息发送",
            )
            self._status.setStatus("已显示可用命令")
            return
        self._status.setStatus(f"未识别的命令：{text}")

    def _handle_shell(self, chat, text: str) -> None:
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, f"$ {text}")
        view.addMessage(
            ElaChatRoleType.System,
            f"$ {text}\n演示环境不会执行真实命令；这里只展示 shellSubmitted 的接线。",
        )
        self._status.setStatus(f"shell 输出已插入：{text}")

    def _show_context_usage(self, chat) -> None:
        used, window, cost = chat.chatInput().contextUsage()
        percent = chat.chatInput().contextUsagePercent()
        markdown = (
            "## 上下文占用\n\n"
            "| 项 | 值 |\n|---|---|\n"
            f"| 已用 | {used:,} |\n"
            f"| 窗口 | {window:,} |\n"
            f"| 占比 | {percent}% |\n"
            f"| 累计花费 | ${cost:.4f} |\n\n"
            "数据完全由宿主 `setContextUsage()` 提供，组件只负责展示。"
        )
        self._show_markdown_dialog("上下文占用", markdown)

    def _open_attachment(self, path: str) -> None:
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            self._status.setStatus(f"已打开附件：{path}")
            return
        self._show_markdown_dialog(
            "附件",
            f"附件路径：`{path or '(空)'}`\n\n"
            "演示附件没有真实文件路径；真实宿主在这里打开文件或预览。",
        )

    def _show_markdown_dialog(self, title: str, markdown: str) -> None:
        dialog = ElaDialogBase(title=title, parent=self.window())
        dialog.setWindowTitle(title)
        dialog.setAutoFit(False)
        dialog.resize(680, 460)
        dialog.setLeftButtonText("关闭")
        viewer = ElaMarkdownViewer(dialog)
        viewer.setMarkdown(markdown)
        dialog.setParamWidget(viewer)
        dialog.leftButtonClicked.connect(dialog.accept)
        for button in dialog.findChildren(QPushButton):
            if button.text() == "确定":
                button.hide()
                break
        self._dialogs.append(dialog)
        dialog.show()

    def _open_gallery(self) -> None:
        from .chat_gallery import ChatGalleryDialog

        dialog = self._gallery_dialog
        if dialog is not None and not is_deleted(dialog):
            dialog.show()
            dialog.raise_()
            return
        dialog = ChatGalleryDialog(self.window())
        self._gallery_dialog = dialog
        self._dialogs.append(dialog)
        dialog.show()

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
        if self._player is not None:
            self._player.stop()
        self._active_scenario = ""
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
        if self._player is not None:
            self._player.stop()
        self._active_scenario = ""
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

    def _run_feature(
        self, method: Callable, needs_idle: bool = False, title: str = ""
    ) -> None:
        label = title or getattr(method, "__name__", "演示")
        chat = self._active_chat()
        if chat is None:
            self._createTopic(activate=True)
            chat = self._active_chat()
        if chat is None:
            return
        if needs_idle and chat.isGenerating():
            self._createTopic(title=label, activate=True)
            chat = self._active_chat()
        before = self._status.status()
        self._set_feature_feedback(f"正在执行：{label}")
        try:
            method(chat)
            if self._status.status() == before:
                self._status.setStatus("演示已插入当前话题")
            self._set_feature_feedback(f"已完成：{label} · {self._status.status()}")
            self._scroll_to_last_message()
        except Exception:
            traceback.print_exc()
            self._status.setBusy(False)
            self._status.setStatus("演示插入失败（见控制台）", level="error")
            self._set_feature_feedback(f"失败：{label}（见控制台）", error=True)

    def _set_feature_feedback(self, text: str, error: bool = False) -> None:
        label = self._feature_feedback
        if label is None or is_deleted(label):
            return
        label.setText(text)
        label.setTextColor(
            severityColor(self._theme_mode, ElaSeverity.Error) if error else None
        )

    def _scroll_to_last_message(self) -> None:
        chat = self._active_chat()
        if chat is None:
            return
        view = chat.chatView()
        messages = view.messages()
        if messages:
            view.scrollToMessage(messages[-1].id)

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

    def _scenario_streaming(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        text = "用一个真实回合演示流式渲染、工具调用与统计"
        self._player.play(
            [
                (0, lambda: input_widget.setText(text)),
                (0, input_widget.submit),
            ],
            on_done=lambda: self._set_scenario_feedback(
                "引导 · 流式回合", "已提交，等待流式完成…"
            ),
            interval=400,
        )

    def _scenario_approval(self, chat: ElaChatWidget) -> None:
        if chat.permissionDock().card() is not None:
            self._drop_pending_permission(chat)
        view = chat.chatView()
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id=f"scenario-perm-{mid}",
                action="edit",
                resources=("example.py",),
                detail="允许修改 example.py？点按钮后宿主会回填一条结果消息。",
            ),
        )
        self._status.setStatus("审批卡已挂到输入区上方，等待你的选择")
        self._set_scenario_feedback(
            "引导 · 批准审批", "请在输入区上方点「允许一次 / 始终允许 / 拒绝」"
        )

    def _scenario_question(self, chat: ElaChatWidget) -> None:
        if chat.permissionDock().card() is not None:
            self._drop_pending_permission(chat)
        view = chat.chatView()
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id=f"scenario-q-{mid}",
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="scope",
                        header="范围",
                        question="哪些目录需要一起看？",
                        options=(
                            ElaChatOption("pyqt6_ela_pro/", "组件库本体"),
                            ElaChatOption("tests/", "回归测试"),
                            ElaChatOption("docs/", "文档"),
                        ),
                        multiple=True,
                    ),
                    ElaChatQuestion(
                        key="style",
                        header="深入程度",
                        question="需要多深入？",
                        options=(
                            ElaChatOption("quick", "只给结论"),
                            ElaChatOption("deep", "展开代码路径"),
                        ),
                    ),
                ),
            ),
        )
        self._status.setStatus("问答卡已挂到输入区上方，逐题回答后提交")
        self._set_scenario_feedback("引导 · 问答审批", "逐题选择 / 填写，最后点提交")

    def _scenario_tools(self, chat: ElaChatWidget) -> None:
        installBuiltinToolRenderers()
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, "逐步演示工具链与文件变更")
        mid = chat.beginAssistantMessage()

        def step_read() -> None:
            view.beginStep(mid)
            call = view.addToolCall(
                mid,
                "read",
                '{"path": "example/chat_playground_page.py"}',
                "scenario-read",
            )
            view.setToolCallResult(mid, call, "class ChatPlaygroundPage: ...", ok=True)
            self._open_tool_card(chat, mid, "scenario-read")

        def step_grep() -> None:
            call = view.addToolCall(
                mid, "grep", '{"pattern": "ToolCallCard"}', "scenario-grep"
            )
            view.setToolCallResult(mid, call, "3 处匹配", ok=True)
            self._open_tool_card(chat, mid, "scenario-grep")

        def step_edit() -> None:
            call = view.addToolCall(
                mid,
                "edit",
                '{"path": "example.py"}',
                "scenario-edit",
                metadata={
                    "files": [
                        {
                            "file": "example.py",
                            "patch": (
                                "--- a/example.py\n+++ b/example.py\n"
                                "@@ -1,2 +1,3 @@\n"
                                " def demo():\n"
                                "+    return 'tool chain'\n"
                                "     return None\n"
                            ),
                            "additions": 1,
                            "deletions": 0,
                            "status": "modified",
                        }
                    ]
                },
            )
            view.setToolCallResult(mid, call, "ok", ok=True)
            self._open_tool_card(chat, mid, "scenario-edit")

        def step_done() -> None:
            view.setPlan(
                mid,
                ElaChatPlan.fromMarkdown("- [x] 读实现\n- [x] 查引用\n- [x] 改代码"),
            )
            view.setStepStats(
                mid,
                ElaChatStats(total_tokens=2200, cost_usd=0.004, duration_ms=3100),
            )
            chat.endAssistantMessage()

        self._player.play(
            [(0, step_read), (0, step_grep), (0, step_edit), (0, step_done)],
            interval=600,
        )

    def _scenario_actions(self, chat: ElaChatWidget) -> None:
        self._demo_basic_turn(chat)
        view = chat.chatView()
        mid = self._last_message_id(chat, ElaChatRoleType.Assistant)
        if mid is not None:
            bubble = view.bubble(mid)
            if bubble is not None:
                bubble.setActionsHoverReveal(False)
            view.scrollToMessage(mid)
        self._active_scenario = "引导 · 消息操作"
        self._status.setBusy(False)
        self._status.setStatus("操作栏已展开：撤回 / 重新生成由宿主接好")
        self._set_scenario_feedback(
            "引导 · 消息操作", "点最后一条消息底部的「撤回 / 重新生成」试试"
        )

    def _scenario_input(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        input_widget.setText("看看 @demo.py 的渲染")
        input_widget.setMentions(
            [ElaChatMention(start=3, end=11, kind="file", id="demo.py")]
        )
        input_widget.addAttachment("demo.py", "", 1024)
        input_widget.textEdit().setFocus()
        self._active_scenario = ""
        self._status.setBusy(False)
        self._status.setStatus("输入区已预填：@ 引用 + 1 个附件")
        self._set_scenario_feedback(
            "引导 · 输入区", "按 @ 或 / 触发补全；回形针继续加文件；Enter 发送"
        )

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
        now = time.time()
        view.beginStep(mid)
        read = view.addToolCall(
            mid,
            "read",
            '{"path": "demo.py"}',
            startedAt=now,
            durationMs=800,
        )
        view.setToolCallResult(mid, read, "class Demo: ...", ok=True)
        view.setStepStats(
            mid, ElaChatStats(total_tokens=640, duration_ms=1400, cost_usd=0.001)
        )
        view.setPlan(
            mid,
            ElaChatPlan.fromMarkdown("- [x] 读实现\n- [>] 子代理查链路\n- [ ] 补测试"),
        )
        view.beginStep(mid)
        parent = view.addToolCall(
            mid,
            "delegate_task",
            '{"task": "查渲染链路"}',
            "multi-p1",
            startedAt=now + 1.5,
            durationMs=3200,
        )
        child = view.addToolCall(
            mid,
            "grep",
            '{"pattern": "toolRenderer"}',
            "multi-c1",
            parentId=parent,
            startedAt=now + 1.9,
            durationMs=1200,
        )
        view.setToolCallResult(mid, child, "3 处匹配", ok=True)
        view.setToolCallResult(mid, parent, "链路已确认", ok=True)
        view.setStepStats(
            mid, ElaChatStats(total_tokens=880, duration_ms=3300, cost_usd=0.002)
        )
        view.beginStep(mid)
        edit = view.addToolCall(
            mid,
            "edit",
            '{"path": "demo.py"}',
            "multi-e1",
            startedAt=now + 5.0,
            durationMs=1100,
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
        view.setStepStats(
            mid, ElaChatStats(total_tokens=420, duration_ms=1200, cost_usd=0.001)
        )
        view.setPlan(
            mid,
            ElaChatPlan.fromMarkdown("- [x] 读实现\n- [x] 子代理查链路\n- [x] 补测试"),
        )
        chat.endAssistantMessage()
        view.setMessageDuration(mid, 6100)

    def _demo_step_handles(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        mid = chat.beginAssistantMessage()
        view.beginStep(mid)
        view.beginReasoning(mid)
        view.appendReasoning(mid, "先分析输入区结构。")
        view.endReasoning(mid, 600)
        view.appendText(mid, "流式状态演示。")
        streaming = chat.streamingMessageId()
        generating = chat.isGenerating()
        call = view.addToolCall(mid, "read", '{"path": "demo.py"}')
        view.setToolCallResult(mid, call, "ok", ok=True)
        steps = chat.stepCount(mid)
        panels = chat.toolPanels(mid)
        view.endText(mid)
        chat.endAssistantMessage(mid)
        self._status.setStatus(
            f"步骤 {steps} / 工具面板 {len(panels)} / "
            f"streamingMessageId={streaming} / isGenerating={generating} / "
            f"lastMessage={view.lastMessage() is not None}"
        )

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
        if chat.permissionDock().card() is not None:
            self._drop_pending_permission(chat)
            self._status.setStatus(
                f"已撤下审批 dock 并清理待答消息（剩余待答 "
                f"{len(chat.pendingPermissionCards())} 张）"
            )
            return
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
        self._status.setStatus(
            f"审批卡已挂到 {type(chat.permissionDock()).__name__}，"
            f"待答 {len(chat.pendingPermissionCards())} 张"
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
        self._status.setStatus(
            f"问答型审批已挂到 dock，待答 {len(chat.pendingPermissionCards())} 张"
        )

    def _demo_steer(self, chat: ElaChatWidget) -> None:
        view, mid = self._start_demo(chat, "先看一下实现")
        view.beginStep(mid)
        view.beginText(mid)
        view.appendText(mid, "我先看看……")
        view.endText(mid)
        first = chat.steerMessage("等等，先别动 _column")
        chat.steerMessage("保留公开 API")
        queued = chat.steerCount()
        if first is not None:
            chat.dequeueSteer(first)
        after_dequeue = chat.steerCount()
        view.beginStep(mid)
        drained = chat.drainSteer()
        chat.clearSteer()
        chat.endAssistantMessage()
        self._status.setStatus(
            f"steer：入队 {queued} / dequeue 后 {after_dequeue} / "
            f"drain {bool(drained)} / 清空后 {chat.steerCount()}"
        )

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
        input_widget = chat.chatInput()
        input_widget.setContextUsage(stats.total_tokens, 200_000, stats.total_cost_usd)
        used, window, cost = input_widget.contextUsage()
        ring = input_widget.contextUsageWidget()
        self._status.setStatus(
            f"上下文 {used}/{window}（{input_widget.contextUsagePercent()}%）/ "
            f"花费 {formatCost(cost)} / 圆环 {ring is not None}"
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
        panel.setContextWindow(200_000)
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
        topic_id = self._createTopic(activate=True)
        new_chat = self._active_chat()
        session_id = new_chat.currentSessionId() if new_chat is not None else ""
        self._status.setStatus(f"新话题 {topic_id} / currentSessionId={session_id}")

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
        input_widget.setText("echo hello")
        self._status.setStatus(
            f"shell 模式：{input_widget.placeholderText()!r} / "
            f"shellMode={input_widget.shellMode()}；"
            "回车触发 shellSubmitted，Esc 退出"
        )

    def _demo_history_hint(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        history = input_widget.history()
        if history is not None:
            for item in ("看看 @demo.py 的渲染", "总结这段代码", "解释这个报错"):
                history.add(item)
        input_widget.clear()
        input_widget.textEdit().setFocus()
        count = len(history.items()) if history is not None else 0
        self._status.setStatus(
            f"提示历史：{count} 条（已补 3 条）；在空输入区按 ↑ / ↓ 浏览"
        )

    def _demo_completion(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        step = self._next_cycle("completion", 2)
        if step == 0:
            input_widget.setText("看看 @demo.py 的渲染")
            input_widget.setMentions(
                [ElaChatMention(start=3, end=11, kind="file", id="demo.py")]
            )
            spans = input_widget.mentionSpans()
            ids = input_widget.mentions()
            self._status.setStatus(
                f"命令 / @ 引用：spans {len(spans)} / ids {ids} / "
                f"submit={input_widget.commandSubmitMode()}；输入 / 或 @ 触发补全"
            )
        else:
            input_widget.clearMentions()
            self._status.setStatus("已清空引用记录（clearMentions）")
        input_widget.textEdit().setFocus()

    def _demo_queue(self, chat: ElaChatWidget) -> None:
        if chat.queueCount() == 0:
            chat.enqueueMessage("排队消息 A：先检查输入区")
            chat.enqueueMessage("排队消息 B：生成中继续追加")
        self._status.setStatus(
            f"排队 {chat.queueCount()} 条 / dock={chat.queueDock().isVisible()} / "
            f"首条={chat.queuedMessages()[0]['text'] if chat.queueCount() else '无'}"
        )

    def _demo_search(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        step = self._next_cycle("search", 4)
        if step == 0:
            if not view.messages():
                self._demo_basic_turn(chat)
            view.showSearchBar("实现")
            self._status.setStatus(
                f"会话搜索：{len(view.searchHits())} 处命中 / index={view.searchIndex()}"
            )
        elif step == 1:
            moved = view.searchNext()
            self._status.setStatus(f"searchNext={moved} / index={view.searchIndex()}")
        elif step == 2:
            moved = view.searchPrev()
            self._status.setStatus(f"searchPrev={moved} / index={view.searchIndex()}")
        else:
            view.clearSearch()
            view.hideSearchBar()
            self._status.setStatus(
                f"clearSearch + hideSearchBar / bar={view.searchBar() is not None}"
            )

    def _demo_send_message(self, chat: ElaChatWidget) -> None:
        mid = chat.sendUserMessage("程序化发送：sendUserMessage")
        self._status.setStatus(
            f"sendUserMessage 返回消息 #{mid} / isGenerating={chat.isGenerating()}"
        )

    def _next_cycle(self, key: str, count: int) -> int:
        topic = self._active_page()
        if topic is None:
            return 0
        index = topic.cycles.get(key, 0)
        topic.cycles[key] = (index + 1) % max(1, count)
        return index

    @staticmethod
    def _last_message_id(chat: ElaChatWidget, role=None):
        for message in reversed(chat.chatView().messages()):
            if role is None or message.role == role:
                return message.id
        return None

    def _ensure_turn(self, chat: ElaChatWidget) -> None:
        if not chat.chatView().messages():
            self._demo_basic_turn(chat)

    def _insert_tool_chain(
        self, chat: ElaChatWidget, with_failure: bool = False
    ) -> None:
        """插入一条含 3 个连续工具调用的消息（分组 / 开合策略的可观察载体）。"""
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, "工具分组 / 开合策略演示")
        mid = chat.beginAssistantMessage()
        view.beginStep(mid)
        items = (
            ("read", '{"path": "demo.py"}', "class Demo: ..."),
            ("glob", '{"pattern": "**/*.py"}', "demo.py\nchat.py"),
            ("grep", '{"pattern": "ToolCallCard"}', "3 处匹配"),
        )
        for index, (name, arguments, result) in enumerate(items):
            call = view.addToolCall(mid, name, arguments, f"chain-{index}")
            ok = not (with_failure and index == len(items) - 1)
            view.setToolCallResult(mid, call, result, ok=ok)
        chat.endAssistantMessage()

    def _demo_tool_grouping(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        on = not view.toolGrouping()
        view.setToolGrouping(on)
        self._insert_tool_chain(chat)
        self._status.setStatus(
            f"工具分组：{'开启' if on else '关闭'}（已插入 3 个连续工具）"
        )

    def _demo_tool_default_open(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        step = self._next_cycle("tool_default_open", 3)
        if step == 0:
            policy = None
            text = "库默认（失败工具卡展开）"
        elif step == 1:
            policy = _always_open
            text = "全部展开"
        else:
            policy = _always_closed
            text = "全部收起"
        view.setToolDefaultOpen(policy)
        self._insert_tool_chain(chat, with_failure=True)
        self._status.setStatus(
            f"工具默认开合：{text}（已插入 3 张工具卡，最后一张失败）"
        )

    def _demo_waiting_placeholder(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        on = not view.waitingPlaceholderEnabled()
        view.setWaitingPlaceholderEnabled(on)
        if on and not chat.isGenerating():
            topic = self._active_page()
            if topic is not None:
                # 放慢一档，让「等待骨架」在首字之前可见
                topic.mock.setTickMs(160)
                self._single_shot_restore_tick(topic)
            chat.sendUserMessage("等待骨架演示：先看占位再出字")
        self._status.setStatus(f"等待骨架：{'开启' if on else '关闭'}（已起一轮）")

    def _single_shot_restore_tick(self, topic: _TopicPage) -> None:
        def restore() -> None:
            if not is_deleted(topic.container):
                topic.mock.setTickMs(24)

        single_shot_on(topic.container, 1200, restore)

    def _demo_timeline_detail(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        step = self._next_cycle("timeline_detail", 3)
        detail = ElaChatTimelineDetail()
        if step == 0:
            text = "默认（collapsed）"
        elif step == 1:
            for name, _section in detail.sections:
                detail = detail.withSection(
                    name,
                    placement=ElaChatDetailPlacementType.Expanded,
                    details=ElaChatDetailDepthType.Expanded,
                )
            text = "六分区全部展开"
        else:
            for name, _section in detail.sections:
                detail = detail.withSection(
                    name, placement=ElaChatDetailPlacementType.Hidden
                )
            text = "六分区全部隐藏"
        view.setTimelineDetail(detail)
        self._status.setStatus(f"时间线密度：{text}")

    def _demo_part_expand(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._ensure_turn(chat)
        part_id = ""
        for message in reversed(view.messages()):
            if message.parts:
                part_id = message.parts[-1].id
                break
        if not part_id:
            self._status.setStatus("当前没有可展开的分段")
            return
        opened = not bool(view.partExpanded(part_id))
        view.setPartExpanded(part_id, opened)
        self._status.setStatus(f"分段 {part_id}：{'展开' if opened else '收起'}")

    def _demo_activity_provider(self, chat: ElaChatWidget) -> None:
        topic = self._active_page()
        if topic is None:
            return
        step = self._next_cycle("activity_provider", 3)
        if step == 0:
            topic.binder.setActivityProvider(None)
            topic.binder.setAutoActivity(True)
            text = "库默认文案 + 自动活动行"
        elif step == 1:
            topic.binder.setActivityProvider(
                lambda kind, detail: f"自定义活动：{kind or '工作'}"
            )
            topic.binder.setAutoActivity(True)
            text = "自定义 provider"
        else:
            topic.binder.setAutoActivity(False)
            text = "关闭自动活动行"
        started = False
        if not chat.isGenerating():
            chat.sendUserMessage("看看活动行是怎么显示的")
            started = True
        self._status.setStatus(
            f"活动行：{text}" + ("（已起一轮生成）" if started else "")
        )

    def _demo_message_meta(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        user_id = chat.addMessage(ElaChatRoleType.User, "看看 @demo.py 的渲染")
        view.setMessageMentions(
            user_id,
            [ElaChatMention(start=3, end=11, kind="file", id="demo.py")],
        )
        view.setMessageAttachments(user_id, [{"name": "demo.py", "size": 1024}])
        view.addMessageAttachment(user_id, "note.txt", "", 256)
        assistant_id = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(assistant_id, "这条消息带完整元信息。")
        view.endMessage(assistant_id)
        view.setMessageIdentity(
            assistant_id,
            agent="demo-agent",
            model="deepseek-v4",
            modelVariant="flash",
        )
        view.setMessageTitle(assistant_id, "演示助手")
        view.setMessageTimestamp(assistant_id, "2026-11-11 12:00")
        view.setMessageDuration(assistant_id, 1234)
        self._status.setStatus(
            f"用户 #{user_id}：@ 区间 + 2 个附件；"
            f"助手 #{assistant_id}：身份 / 标题 / 时间 / 耗时"
        )

    def _demo_change_summary(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._ensure_turn(chat)
        on = not view.changeSummaryEnabled()
        view.setChangeSummaryEnabled(on)
        mid = self._last_message_id(chat, ElaChatRoleType.Assistant)
        changes = view.turnChanges(mid) if mid is not None else None
        count = changes.count if changes is not None else 0
        self._status.setStatus(
            f"变更汇总：{'开启' if on else '关闭'} / 当前消息 {count} 个文件"
        )

    def _demo_message_error(self, chat: ElaChatWidget) -> None:
        topic = self._active_page()
        view = chat.chatView()
        if topic is not None and topic.error_id is not None:
            mid = topic.error_id
            if view.message(mid) is not None:
                error, error_type = view.messageError(mid)
                view.clearMessageError(mid)
                topic.error_id = None
                self._status.setStatus(
                    f"已清除消息 #{mid} 的错误（{error or error_type or '无'}）"
                )
                return
            topic.error_id = None
        view.addMessage(ElaChatRoleType.User, "演示：这条回答会失败并出现重试")
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(mid, "这条回答会带上错误卡。")
        view.endMessage(mid)
        chat.setMessageError("上游限流：请稍后重试", mid, "rate_limit")
        if topic is not None:
            topic.error_id = mid
        self._status.setStatus(f"消息 #{mid} 已设置错误卡（再点一次清除）")

    def _demo_pending_user(self, chat: ElaChatWidget) -> None:
        topic = self._active_page()
        view = chat.chatView()
        if topic is not None and topic.pending_id is not None:
            mid = topic.pending_id
            if view.message(mid) is not None:
                view.resolvePendingUserMessage(mid, sent=True)
                topic.pending_id = None
                self._status.setStatus(f"待发送消息 #{mid} 已结算为普通消息")
                return
            topic.pending_id = None
        mid = view.addPendingUserMessage("待发送：插话到当前回合", delivery="steer")
        if topic is not None:
            topic.pending_id = mid
        self._status.setStatus(f"已添加待发送消息 #{mid}（再点结算）")

    def _demo_message_actions(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._demo_basic_turn(chat)
        step = self._next_cycle("message_actions", 6)
        user_id = self._last_message_id(chat, ElaChatRoleType.User)
        if step == 0:
            message = chat.undoMessage(user_id) if user_id is not None else None
            self._status.setStatus(
                f"undoMessage 撤回用户消息 #{message.id}"
                if message is not None
                else "没有可撤回的用户消息"
            )
            return
        if step == 1:
            message = chat.undoLastUserMessage()
            self._status.setStatus(
                f"undoLastUserMessage 撤回最后一条用户消息 #{message.id}"
                if message is not None
                else "没有可撤回的用户消息"
            )
            return
        if step == 2:
            assistant_id = self._last_message_id(chat, ElaChatRoleType.Assistant)
            message = (
                chat.regenerateFrom(assistant_id) if assistant_id is not None else None
            )
            self._status.setStatus(
                f"重新生成返回用户消息 #{message.id}"
                if message is not None
                else "没有可重新生成的回答"
            )
            return
        if step == 3:
            assistant_id = self._last_message_id(chat, ElaChatRoleType.Assistant)
            message = (
                chat.retryMessage(assistant_id) if assistant_id is not None else None
            )
            self._status.setStatus(
                f"重试返回用户消息 #{message.id}"
                if message is not None
                else "没有可重试的回答"
            )
            return
        if step == 4:
            messages = view.messages()
            if messages:
                mid = messages[-1].id
                chat.removeMessage(mid)
                self._status.setStatus(f"removeMessage 删除消息 #{mid}")
            else:
                self._status.setStatus("当前没有可删除的消息")
            return
        removed = view.removeMessagesFrom(user_id) if user_id is not None else []
        self._status.setStatus(f"removeMessagesFrom 删除 {len(removed)} 条消息")

    def _demo_custom_action(self, chat: ElaChatWidget) -> None:
        self._ensure_turn(chat)
        mid = self._last_message_id(chat)
        actions = chat.actions(mid) if mid is not None else None
        if actions is None:
            self._status.setStatus("当前没有可挂操作栏的消息")
            return
        if actions.item("demo_pin") is None:
            actions.addCustomAction(
                "demo_pin",
                icon=ElaIconType.IconName.Bolt,
                tooltip="自定义动作",
                callback=lambda: self._status.setStatus("自定义消息动作被点击"),
            )
            self._status.setStatus("已添加自定义消息动作（再点移除）")
        else:
            actions.removeItem("demo_pin")
            self._status.setStatus("已移除自定义消息动作")

    def _demo_bubble_handles(self, chat: ElaChatWidget) -> None:
        self._ensure_turn(chat)
        view = chat.chatView()
        mid = self._last_message_id(chat, ElaChatRoleType.Assistant)
        bubble = view.bubble(mid) if mid is not None else None
        if bubble is None:
            self._status.setStatus("当前没有可读取的气泡")
            return
        bubble.setAvatarShape("rounded")
        bubble.setActionsHoverReveal(False)
        bubble.setActionsHoverReveal(True)
        try:
            reasoning_viewer = bubble.inlineReasoningViewer() is not None
        except RuntimeError:
            reasoning_viewer = False
        handles = {
            "hoverReveal": bubble.actionsHoverReveal(),
            "header": bubble.header() is not None,
            "meta": bubble.meta() is not None,
            "footer": bubble.footer() is not None,
            "actions": bubble.actions() is not None,
            "text": bool(bubble.text()),
            "parts": len(bubble.parts()),
            "markdown": bubble.markdownViewer() is not None,
            "reasoning": reasoning_viewer,
            "stats": bubble.statsBadge() is not None,
            "tools": len(bubble.toolPanels()),
        }
        self._status.setStatus(f"气泡 #{mid} 句柄：{handles}")

    def _demo_clear_plan_retry(self, chat: ElaChatWidget) -> None:
        topic = self._active_page()
        view = chat.chatView()
        if topic is not None and topic.plan_retry_id is not None:
            mid = topic.plan_retry_id
            if view.message(mid) is not None:
                plan = view.plan(mid)
                plan_part = view.planPart(mid)
                retry = view.retryState(mid)
                view.clearPlan(mid)
                view.clearRetry(mid)
                topic.plan_retry_id = None
                self._status.setStatus(
                    f"已清除消息 #{mid}：plan={plan is not None} / "
                    f"part={plan_part is not None} / retry={retry is not None}"
                )
                return
            topic.plan_retry_id = None
        view.addMessage(ElaChatRoleType.User, "演示：计划 + 自动重试")
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginStep(mid)
        view.setPlan(mid, ElaChatPlan.fromMarkdown("- [ ] 演示计划\n- [>] 清除后消失"))
        view.setRetry(mid, 2, "上游限流，稍后重试", 0)
        view.appendText(mid, "这条消息同时有计划卡和重试态。")
        view.endMessage(mid)
        if topic is not None:
            topic.plan_retry_id = mid
        self._status.setStatus(f"消息 #{mid} 已插入计划 + 重试（再点清除）")

    def _demo_stats_mode(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._ensure_turn(chat)
        modes = ("footer", "steps", "none")
        current = view.statsMode()
        mode = (
            modes[(modes.index(current) + 1) % len(modes)]
            if current in modes
            else "footer"
        )
        view.setStatsMode(mode)
        self._status.setStatus(f"统计徽标：{mode}")

    def _demo_reasoning_style(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._ensure_turn(chat)
        styles = ("collapse", "inline")
        current = view.reasoningStyle()
        style = (
            styles[(styles.index(current) + 1) % len(styles)]
            if current in styles
            else "collapse"
        )
        view.setReasoningStyle(style)
        self._status.setStatus(f"推理样式：{style}")

    def _demo_disclaimer(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._ensure_turn(chat)
        step = self._next_cycle("disclaimer", 3)
        if step == 0:
            view.setDisclaimerVisible(False)
            text = "隐藏"
        elif step == 1:
            view.setDisclaimer("演示：内容由 AI 生成，请自行核实")
            view.setDisclaimerVisible(True)
            text = "自定义文案"
        else:
            view.setDisclaimer(DISCLAIMER_TEXT)
            view.setDisclaimerVisible(True)
            text = "默认文案"
        self._status.setStatus(
            f"免责声明：{text} / visible={view.disclaimerVisible()} / "
            f"text={view.disclaimer()!r}"
        )

    def _demo_copy_notification(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        on = not view.copyNotificationEnabled()
        view.setCopyNotificationEnabled(on)
        self._ensure_turn(chat)
        mid = self._last_message_id(chat)
        bubble = view.bubble(mid) if mid is not None else None
        actions = bubble.actions() if bubble is not None else None
        if actions is not None:
            # 真的触发一次复制：能直接看到「已复制到剪贴板」提示（开 / 关对比）
            actions.copyRequested.emit()
            text = "已触发一次复制（看提示）"
        else:
            text = "当前没有可复制的消息"
        self._status.setStatus(f"复制提示：{'开启' if on else '关闭'} / {text}")

    def _demo_avatars(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._ensure_turn(chat)
        step = self._next_cycle("avatars", 4)
        if step == 0:
            view.setUserAvatar(_AVATAR_SVG)
            view.setAssistantAvatar(_AVATAR_SVG)
            view.setAvatarShape("rounded")
            view.setAvatarVisible(True)
            text = "自定义 SVG + 圆角"
        elif step == 1:
            view.setAvatarShape("square")
            text = "方形"
        elif step == 2:
            view.setAvatarVisible(False)
            text = "隐藏"
        else:
            view.setUserAvatar(None)
            view.setAssistantAvatar(None)
            view.setAvatarShape("circle")
            view.setAvatarVisible(True)
            text = "恢复默认"
        self._status.setStatus(
            f"头像：{text}（shape={view.avatarShape()} / visible={view.avatarVisible()} / "
            f"user={view.userAvatar() is not None} / "
            f"assistant={view.assistantAvatar() is not None}）"
        )

    def _demo_user_bubble_width(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        self._ensure_turn(chat)
        widths = (0.9, 0.7, 0.5)
        current = view.userBubbleMaxWidth()
        width = (
            widths[(widths.index(current) + 1) % len(widths)]
            if current in widths
            else widths[0]
        )
        view.setUserBubbleMaxWidth(width)
        self._status.setStatus(f"用户气泡最大宽度：{width:.1f}")

    def _demo_content_width(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        widths = (0, 760, 600)
        current = view.contentMaxWidth()
        width = (
            widths[(widths.index(current) + 1) % len(widths)]
            if current in widths
            else widths[0]
        )
        view.setContentMaxWidth(width)
        self._status.setStatus(f"内容宽度：{'不限' if width == 0 else f'{width}px'}")

    def _demo_empty_state(self, chat: ElaChatWidget) -> None:
        existing = next(
            (
                topic_id
                for topic_id, session in self._sessions.items()
                if session.title == "空态建议" and topic_id in self._tab_ids
            ),
            None,
        )
        if existing is None:
            self._createTopic(title="空态建议", activate=True)
        else:
            self._activateTopic(existing)
        new_chat = self._active_chat()
        if new_chat is None:
            return
        view = new_chat.chatView()
        view.setEmptyTitle("今天想聊点什么？")
        view.setEmptySubtitle("空态标题 / 副标题 / 建议按钮都由宿主设置")
        view.setSuggestions(["总结这段代码", "解释这个报错", "生成回归测试"])
        self._status.setStatus(
            f"空态：{view.emptyTitle()!r} / {view.emptySubtitle()!r} / "
            f"{len(view.suggestions())} 个建议；点击按钮看 suggestionClicked"
        )

    def _demo_scroll_behavior(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        step = self._next_cycle("scroll_behavior", 3)
        if step == 0:
            view.setStickToBottom(True)
            view.setJumpThreshold(80)
            view.setScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            text = "贴底 / 80px / AsNeeded"
        elif step == 1:
            view.setStickToBottom(False)
            view.setJumpThreshold(120)
            view.setScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            text = "不贴底 / 120px / AlwaysOn"
        else:
            view.setStickToBottom(True)
            view.setJumpThreshold(40)
            view.setScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            text = "贴底 / 40px / AlwaysOff"
        view.scrollToBottom()
        self._status.setStatus(
            f"滚动行为：{text}（stick={view.stickToBottom()} / "
            f"threshold={view.jumpThreshold()} / "
            f"policy={view.scrollBarPolicy().name} / bar={view.scrollBar() is not None}）"
        )

    def _demo_attachments(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        step = self._next_cycle("attachments", 4)
        if step == 0:
            input_widget.addAttachments([__file__])
            input_widget.addAttachment("draft.md", "", 1024)
            text = (
                f"addAttachments + addAttachment（{input_widget.attachmentCount()} 项 / "
                f"{len(input_widget.attachmentPaths())} 个路径 / "
                f"条 {input_widget.attachmentStrip().count()}）"
            )
        elif step == 1:
            input_widget.setAttachments(
                [
                    {"name": "替换 A.md", "size": 512},
                    {"name": "替换 B.py", "size": 768},
                ]
            )
            text = f"setAttachments 整体替换（{input_widget.attachmentCount()} 项）"
        elif step == 2:
            input_widget.removeAttachment(0)
            text = f"removeAttachment(0)（剩 {input_widget.attachmentCount()} 项）"
        else:
            input_widget.clearAttachments()
            text = "clearAttachments"
        self._status.setStatus(f"附件：{text}")

    def _demo_file_picker(self, chat: ElaChatWidget) -> None:
        topic = self._active_page()
        input_widget = chat.chatInput()
        if topic is not None and topic.custom_picker:
            input_widget.setFilePicker(None)
            topic.custom_picker = False
            text = "恢复系统文件框"
        else:
            input_widget.setFilePicker(lambda: [__file__])
            if topic is not None:
                topic.custom_picker = True
            # 真的点一次回形针：自定义 picker 会直接把本示例文件加进附件
            input_widget.addFileButton().click()
            text = "回形针改为添加本示例文件（已触发一次）"
        self._status.setStatus(f"文件选择器：{text}")

    def _demo_mime(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(__file__)])
        accepted = input_widget.acceptsMime(mime)
        attached = input_widget.attachMime(mime)
        self._status.setStatus(
            f"acceptsMime={accepted} / attachMime={attached} / "
            f"附件 {input_widget.attachmentCount()} 项"
        )

    def _demo_send_behavior(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        if not input_widget.text().strip():
            input_widget.setText("第一行\n第二行\n第三行\n第四行")
        step = self._next_cycle("send_behavior", 3)
        if step == 0:
            input_widget.setSendOnEnter(True)
            input_widget.setMinLines(3)
            input_widget.setMaxLines(8)
            input_widget.setSendText("发送")
            input_widget.setStopText("停止")
            text = "Enter 发送 / 3–8 行 / 发送·停止"
        elif step == 1:
            input_widget.setSendOnEnter(False)
            input_widget.setMinLines(1)
            input_widget.setMaxLines(4)
            input_widget.setSendText("提交")
            input_widget.setStopText("中止")
            text = "仅按钮发送 / 1–4 行 / 提交·中止"
        else:
            input_widget.setSendOnEnter(True)
            input_widget.setMinLines(6)
            input_widget.setMaxLines(12)
            input_widget.setSendText("发送")
            input_widget.setStopText("停止")
            text = "Enter 发送 / 6–12 行"
        self._status.setStatus(
            f"输入行为：{text}（sendOnEnter={input_widget.sendOnEnter()}）"
        )

    def _demo_submit(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        input_widget.setText("程序化提交：submit()")
        text = input_widget.text()
        ok = input_widget.submit()
        self._status.setStatus(f"submit={ok} / text={text!r}")

    def _demo_draft(self, chat: ElaChatWidget) -> None:
        topic = self._active_page()
        input_widget = chat.chatInput()
        if topic is not None and topic.draft_state is not None:
            chat.setDraftState(topic.draft_state)
            topic.draft_state = None
            self._status.setStatus(f"已恢复草稿快照（text={input_widget.text()!r}）")
            return
        input_widget.setText("草稿演示：保存后可以恢复")
        if topic is not None:
            topic.draft_state = chat.draftState()
        input_widget.clear()
        self._status.setStatus("已保存草稿并清空输入区（再点恢复）")

    def _demo_queue_toggles(self, chat: ElaChatWidget) -> None:
        step = self._next_cycle("queue_toggles", 3)
        if step == 0:
            chat.setQueueEnabled(True)
            chat.setAutoSendQueue(True)
            chat.setSteerEnabled(True)
            text = "默认：排队开 / 自动续发开 / 插话开"
        elif step == 1:
            chat.setQueueEnabled(False)
            chat.setAutoSendQueue(False)
            chat.setSteerEnabled(False)
            text = "全部关闭"
        else:
            chat.setQueueEnabled(True)
            chat.setAutoSendQueue(True)
            chat.setSteerEnabled(True)
            text = "恢复默认"
        self._status.setStatus(
            f"队列 / 插话：{text}（queue={chat.queueEnabled()} / "
            f"autoSend={chat.autoSendQueue()} / steer={chat.steerEnabled()}）"
        )

    def _demo_toolbar_extension(self, chat: ElaChatWidget) -> None:
        bar = chat.toolBar()
        if bar.item("demo_pin") is not None:
            bar.removeItem("demo_pin")
            self._status.setStatus("已移除自定义工具栏按钮")
            return
        bar.addButton(
            icon=ElaIconType.IconName.Bolt,
            tooltip="自定义工具按钮",
            key="demo_pin",
            zone="leading",
            callback=lambda: self._status.setStatus("自定义工具栏按钮被点击"),
        )
        self._status.setStatus("已添加自定义工具栏按钮（再点移除）")

    def _demo_toolbar_visibility(self, chat: ElaChatWidget) -> None:
        input_widget = chat.chatInput()
        step = self._next_cycle("toolbar_visibility", 2)
        if step == 0:
            input_widget.setNewTopicVisible(False)
            input_widget.setAddFileVisible(False)
            input_widget.setClearVisible(False)
            input_widget.setContextUsageVisible(False)
            text = "精简（隐藏新建 / 文件 / 清空 / 圆环）"
        else:
            input_widget.setNewTopicVisible(True)
            input_widget.setAddFileVisible(True)
            input_widget.setClearVisible(True)
            input_widget.setContextUsageVisible(True)
            text = "全部显示"
        self._status.setStatus(
            f"工具栏显隐：{text}（new={input_widget.newTopicButton() is not None} / "
            f"file={input_widget.addFileButton() is not None} / "
            f"clear={input_widget.clearButton() is not None}）"
        )

    def _demo_names(self, chat: ElaChatWidget) -> None:
        self._ensure_turn(chat)
        step = self._next_cycle("names", 3)
        presets = (("", ""), ("你", "AI 助手"), ("开发者", "审查助手"))
        user, assistant = presets[step]
        chat.setUserName(user)
        chat.setAssistantName(assistant)
        mid = self._last_message_id(chat)
        if mid is not None:
            chat.chatView().scrollToMessage(mid)
        self._status.setStatus(
            f"名称：用户={chat.userName() or '默认'} / "
            f"助手={chat.assistantName() or '默认'}（已滚动到消息）"
        )

    def _demo_input_dock(self, chat: ElaChatWidget) -> None:
        topic = self._active_page()
        if topic is not None and topic.dock_widget is not None:
            widget = topic.dock_widget
            topic.dock_widget = None
            chat.clearDock()
            if widget is not None:
                widget.deleteLater()
            self._status.setStatus("已恢复输入区（clearDock）")
            return
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        label = ColorText(
            "这是 setDockWidget(replace=True) 替换的输入区；再点「输入区替换」恢复。",
            widget,
        )
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextPixelSize(12)
        label.setWordWrap(True)
        layout.addWidget(label)
        if not chat.setDockWidget(widget, replace=True):
            widget.deleteLater()
            self._status.setStatus("输入区替换失败")
            return
        if topic is not None:
            topic.dock_widget = widget
        self._status.setStatus("已用 setDockWidget 替换输入区")

    def _demo_strict_ids(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        on = not view.strictIds()
        view.setStrictIds(on)
        probe = "传错 id 被静默忽略"
        try:
            view.setMessageTitle(-1, "probe")
        except Exception as exc:  # noqa: BLE001 —— 演示就是要看到严格模式抛错
            probe = f"传错 id 立刻抛 {type(exc).__name__}: {exc}"
        self._status.setStatus(f"严格 ID：{'开启' if on else '关闭'} / {probe}")

    def _demo_virtualization(self, chat: ElaChatWidget) -> None:
        view = chat.chatView()
        step = self._next_cycle("virtualization", 2)
        if step == 0:
            view.setVirtualPartsEnabled(False)
            view.setShellVirtualizationEnabled(False)
            view.setVirtualListEnabled(False)
            view.setViewportSuspension(False)
            view.setResizeReflowDeferred(False)
            text = "全部关闭（当场物化）"
        else:
            view.setVirtualPartsEnabled(True)
            view.setShellVirtualizationEnabled(True, 80)
            view.setVirtualListEnabled(True, 200)
            view.setViewportSuspension(True, 80)
            view.setResizeReflowDeferred(True, 50, 80, 200)
            text = "恢复默认阈值"
        self._status.setStatus(
            f"虚拟化：{text}（parts={view.virtualPartsEnabled()} / "
            f"shell={view.shellVirtualizationEnabled()} / "
            f"suspend={view.viewportSuspension()} / "
            f"reflow={view.resizeReflowDeferred()}）"
        )

    def _demo_materialize(self, chat: ElaChatWidget) -> None:
        self._ensure_turn(chat)
        view = chat.chatView()
        mid = self._last_message_id(chat)
        if mid is None:
            self._status.setStatus("当前没有可物化的消息")
            return
        changed = view.materializeMessage(mid)
        located = view.scrollToMessage(mid)
        self._status.setStatus(
            f"消息 #{mid}：materialize={changed} / scrollToMessage={located}"
        )

    def _demo_journal(self, chat: ElaChatWidget) -> None:
        journal = ElaChatTurnJournal(title="日志恢复演示")
        journal.begin(0)
        journal.beginStep()
        journal.text("这条消息是从 ElaChatTurnJournal 重放出来的。")
        journal.endText()
        journal.end()
        mid = journal.replayInto(chat.chatView())
        self._status.setStatus(
            f"回合日志：{len(journal.events())} 个事件 / "
            f"{len(journal.dumps().splitlines())} 行，重放为消息 #{mid}"
        )

    def _demo_pricing(self, chat: ElaChatWidget) -> None:
        pricing = ModelPricing(
            input_per_m=0.27,
            output_per_m=1.10,
            cache_read_per_m=0.07,
            tiers=(
                (
                    32000,
                    ModelPricing(
                        input_per_m=0.55,
                        output_per_m=2.20,
                        cache_read_per_m=0.14,
                    ),
                ),
            ),
        )
        short = ElaChatStats(
            prompt_tokens=12000,
            completion_tokens=3000,
            cache_read_tokens=4000,
        )
        long = ElaChatStats(prompt_tokens=64000, completion_tokens=3000)
        short_cost = stats_cost(short, pricing)
        long_cost = stats_cost(long, pricing)
        view, mid = self._start_demo(chat, "计价换算")
        view.beginStep(mid)
        view.appendText(
            mid,
            f"短上下文 {formatCost(short_cost)} / 长上下文 {formatCost(long_cost)}",
        )
        view.setStepStats(
            mid,
            ElaChatStats(
                prompt_tokens=64000,
                completion_tokens=3000,
                cost_usd=float(long_cost),
                duration_ms=900,
            ),
        )
        chat.endAssistantMessage()
        self._status.setStatus(
            f"计价：短上下文 {formatCost(short_cost)} / "
            f"长上下文 {formatCost(long_cost)}（已写入统计徽标）"
        )

    def _demo_async_worker(self, chat: ElaChatWidget) -> None:
        dialog = ElaDialogBase(title="真实后端接入", parent=self.window())
        dialog.setWindowTitle("真实后端接入")
        dialog.setAutoFit(False)
        dialog.resize(760, 560)
        dialog.setLeftButtonText("关闭")
        viewer = ElaMarkdownViewer(dialog)
        viewer.setMarkdown(_ASYNC_WORKER_DOC)
        dialog.setParamWidget(viewer)
        dialog.leftButtonClicked.connect(dialog.accept)
        for button in dialog.findChildren(QPushButton):
            if button.text() == "确定":
                button.hide()
                break
        self._dialogs.append(dialog)
        dialog.show()
        self._status.setStatus("真实后端接入说明已打开（ElaChatAsyncWorker）")


__all__ = ["ChatPlaygroundPage"]

"""聊天组件画廊：把可独立使用的块组件摆出来直接操作。"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPalette
from PyQt6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaScrollArea, ElaThemeType, eTheme

from pyqt6_ela_pro import ElaButton, ElaDialogBase, ElaThemeWidget
from pyqt6_ela_pro._internal import connect_theme_signal, safe_connect
from pyqt6_ela_pro._styles import ColorText, setTextBaseColor
from pyqt6_ela_pro.chat import (
    ElaChatFileChanges,
    ElaChatNotice,
    ElaChatOption,
    ElaChatPermission,
    ElaChatPlan,
    ElaChatQueueDock,
    ElaChatQuestion,
    ElaChatRetryCard,
    ElaChatStats,
    ElaChatToolCall,
    ElaChatTurnChanges,
    ElaChatWorkingRow,
    AttachmentStrip,
    PlanPanel,
    StatsBadge,
    ToolCallCard,
    TurnChangesRow,
    chatFilesFromMetadata,
    installBuiltinToolRenderers,
)
from pyqt6_ela_pro.chat.blocks import PermissionCard

_DEMO_FILES = [
    {
        "file": "chat_playground_page.py",
        "patch": (
            "--- a/chat_playground_page.py\n+++ b/chat_playground_page.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def demo():\n"
            "+    return 'gallery'\n"
            "     return None\n"
        ),
        "additions": 1,
        "deletions": 0,
        "status": "modified",
    },
    {
        "file": "chat_gallery.py",
        "patch": (
            "--- a/chat_gallery.py\n+++ b/chat_gallery.py\n"
            "@@ -10,1 +10,2 @@\n"
            "+# 组件画廊\n"
            " class ChatGalleryDialog: ...\n"
        ),
        "additions": 1,
        "deletions": 0,
        "status": "modified",
    },
]

_DEMO_PLAN = """- [x] 拆分示例页
- [x] 补齐宿主信号
- [>] 快速体验场景
- [ ] 回归测试
"""


class ChatGalleryDialog(ElaDialogBase):
    """聊天块组件的非模态画廊；每个交互控件都有独立结果行。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(title="聊天组件画廊", parent=parent)
        self.setWindowTitle("聊天组件画廊")
        self.setAutoFit(False)
        self.resize(1000, 760)
        self.setLeftButtonText("关闭")
        safe_connect(
            self,
            "leftButtonClicked",
            self.accept,
            "gallery.close",
            receiver=self,
        )
        self._widgets: list = []
        self._feedback: list = []
        installBuiltinToolRenderers()

        scroll = ElaScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = self._theme_content()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(10)

        self._add_plan(layout, content)
        self._add_tools(layout, content)
        self._add_permissions(layout, content)
        self._add_changes(layout, content)
        self._add_rows(layout, content)
        self._add_inputs(layout, content)
        layout.addStretch(1)

        scroll.setWidget(content)
        scroll.viewport().setAutoFillBackground(False)
        # ElaScrollArea 的 viewport 默认用白色 Base；不钉主题底色会把整页刷白
        setTextBaseColor(
            scroll,
            eTheme.getThemeColor(
                eTheme.getThemeMode(), ElaThemeType.ThemeColor.DialogBase
            ),
        )
        self._scroll = scroll
        self._content = content
        self.setParamWidget(scroll)
        connect_theme_signal(self)
        for button in self.findChildren(QPushButton):
            if button.text() == "确定":
                button.hide()
                break

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        content = getattr(self, "_content", None)
        scroll = getattr(self, "_scroll", None)
        if content is None or scroll is None:
            return
        self._apply_content_palette(content, mode)
        setTextBaseColor(
            scroll, eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.DialogBase)
        )

    @staticmethod
    def _apply_content_palette(content: QWidget, mode) -> None:
        background = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)
        text = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
        palette = content.palette()
        palette.setColor(QPalette.ColorRole.Window, background)
        palette.setColor(QPalette.ColorRole.Base, background)
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.WindowText, text)
        content.setPalette(palette)

    def _theme_content(self) -> ElaThemeWidget:
        """画廊主体：钉住 Base / Window / Text，避免普通 QWidget 的白底。"""
        content = ElaThemeWidget(self)
        self._apply_content_palette(content, eTheme.getThemeMode())
        content.setAutoFillBackground(True)
        return content

    def _section(self, layout, parent, title: str, hint: str) -> None:
        label = ColorText(title, parent)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextPixelSize(14)
        label.setTextWeight(QFont.Weight.DemiBold)
        layout.addWidget(label)
        note = ColorText(hint, parent)
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setTextPixelSize(12)
        note.setWordWrap(True)
        layout.addWidget(note)

    def _result(self, layout, parent, text: str = "未操作") -> ColorText:
        label = ColorText(text, parent)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextPixelSize(12)
        label.setWordWrap(True)
        layout.addWidget(label)
        self._feedback.append(label)
        return label

    def _own(self, widget):
        self._widgets.append(widget)
        return widget

    def _add_plan(self, layout, parent) -> None:
        self._section(
            layout,
            parent,
            "计划 / 待办",
            "PlanPanel：折叠摘要 + 完整 checklist；点标题行展开 / 收起。",
        )
        panel = self._own(PlanPanel(parent, plan=ElaChatPlan.fromMarkdown(_DEMO_PLAN)))
        panel.setOpenedSilently(True)
        layout.addWidget(panel)

    def _add_tools(self, layout, parent) -> None:
        self._section(
            layout,
            parent,
            "工具卡",
            "ToolCallCard：read 明文结果；edit 走内置渲染器显示真实 diff。",
        )
        read = self._own(
            ToolCallCard(
                parent,
                name="read",
                arguments='{"path": "demo.py"}',
                toolCallId="gallery-read",
                defaultOpen=True,
            )
        )
        read.setResult("class Demo: ...", ok=True, durationMs=120)
        layout.addWidget(read)
        edit = self._own(
            ToolCallCard(
                parent,
                tool_call=ElaChatToolCall(
                    id="gallery-edit",
                    name="edit",
                    arguments='{"path": "chat_gallery.py"}',
                    metadata={"files": _DEMO_FILES},
                ),
                defaultOpen=True,
            )
        )
        edit.setResult("2 个文件已更新", ok=True, durationMs=260)
        layout.addWidget(edit)

    def _add_permissions(self, layout, parent) -> None:
        self._section(
            layout,
            parent,
            "审批 / 提问",
            "PermissionCard：批准型支持允许一次 / 始终允许 / 拒绝；问答型逐题提交。",
        )
        self._add_permission_card(
            layout,
            parent,
            ElaChatPermission(
                request_id="gallery-perm",
                action="edit",
                resources=("example.py",),
                detail="允许修改 example.py？",
            ),
        )
        self._add_permission_card(
            layout,
            parent,
            ElaChatPermission(
                request_id="gallery-q",
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

    def _add_permission_card(self, layout, parent, request: ElaChatPermission) -> None:
        card = self._own(PermissionCard(parent))
        card.setPermission(request)
        result = self._result(layout, parent)

        def settle(reply: str, answer: str, feedback: str) -> None:
            current = card.permission()
            if current is not None:
                card.setPermission(current.withStatus(reply, answer, feedback))
            result.setText(f"回复：{reply} / answer={answer!r} / feedback={feedback!r}")

        safe_connect(card, "replied", settle, "gallery.permission_reply", receiver=card)
        layout.addWidget(card)
        card.show()
        reset = ElaButton("重置", variant="text", size="small", parent=parent)
        reset.setFixedWidth(60)
        safe_connect(
            reset,
            "clicked",
            lambda _=False: card.setPermission(request),
            "gallery.permission_reset",
            receiver=reset,
        )
        layout.addWidget(reset)

    def _add_changes(self, layout, parent) -> None:
        self._section(
            layout,
            parent,
            "文件变更",
            "ElaChatFileChanges：文件行可展开看 diff；TurnChangesRow 是回合汇总入口。",
        )
        files = chatFilesFromMetadata(_DEMO_FILES)
        changes = self._own(ElaChatFileChanges(parent))
        changes.setFiles(files)
        changes.expandAll()
        layout.addWidget(changes)
        summary = self._own(TurnChangesRow(parent))
        summary.setChanges(
            ElaChatTurnChanges(files=tuple(files), additions=2, deletions=0)
        )
        summary.setOpenedSilently(True)
        layout.addWidget(summary)

    def _add_rows(self, layout, parent) -> None:
        self._section(
            layout,
            parent,
            "状态行",
            "StatsBadge（悬浮看详情）/ ElaChatNotice / ElaChatWorkingRow / 重试卡。",
        )
        stats = self._own(StatsBadge(parent))
        stats.setStats(
            ElaChatStats(
                prompt_tokens=1280,
                completion_tokens=640,
                cost_usd=0.0032,
                duration_ms=2400,
            )
        )
        stats.setMessageDuration(2400)
        layout.addWidget(stats)

        notice = self._own(
            ElaChatNotice("model-switched", "已切换模型", "deepseek-v4", parent)
        )
        layout.addWidget(notice)

        working = self._own(ElaChatWorkingRow(parent))
        working.setText("正在探索代码库…")
        layout.addWidget(working)

        retry = self._own(ElaChatRetryCard(parent))
        retry.setRetry(2, "上游限流，稍后自动重试", time.time() + 30)
        retry_result = self._result(layout, parent)
        safe_connect(
            retry,
            "retryRequested",
            lambda: retry_result.setText("已点「立即重试」：真实宿主在这里重发请求"),
            "gallery.retry",
            receiver=retry,
        )
        safe_connect(
            retry,
            "cancelRequested",
            lambda: retry_result.setText("已点「取消」：真实宿主在这里终止重试"),
            "gallery.retry_cancel",
            receiver=retry,
        )
        layout.addWidget(retry)

    def _add_inputs(self, layout, parent) -> None:
        self._section(
            layout,
            parent,
            "附件 / 队列",
            "AttachmentStrip 点击反馈；ElaChatQueueDock 的发送 / 编辑 / 移除 / 排序 / 插话都已接回调。",
        )
        strip = self._own(AttachmentStrip(parent))
        strip.setAttachments(
            [
                {"name": "demo.py", "size": 1024},
                {"name": "笔记.md", "size": 2048},
            ]
        )
        strip_result = self._result(layout, parent)
        safe_connect(
            strip,
            "attachmentClicked",
            lambda path: strip_result.setText(f"点击附件：{path or '(无路径)'}"),
            "gallery.attachment",
            receiver=strip,
        )
        layout.addWidget(strip)

        queue = self._own(ElaChatQueueDock(parent))
        queue.setMessages(
            [
                {"id": "q1", "text": "排队消息 A：先看输入区", "attachments": []},
                {"id": "q2", "text": "排队消息 B：生成中继续追加", "attachments": []},
            ]
        )
        queue_result = self._result(layout, parent)
        safe_connect(
            queue,
            "sendRequested",
            lambda mid: queue_result.setText(f"立即发送：{mid}"),
            "gallery.queue_send",
            receiver=queue,
        )
        safe_connect(
            queue,
            "editRequested",
            lambda mid: queue_result.setText(f"编辑：{mid}"),
            "gallery.queue_edit",
            receiver=queue,
        )
        safe_connect(
            queue,
            "removeRequested",
            lambda mid: queue_result.setText(f"移除：{mid}"),
            "gallery.queue_remove",
            receiver=queue,
        )
        safe_connect(
            queue,
            "reorderRequested",
            lambda mid, index: queue_result.setText(f"排序：{mid} → {index}"),
            "gallery.queue_reorder",
            receiver=queue,
        )
        safe_connect(
            queue,
            "steerRequested",
            lambda mid: queue_result.setText(f"插话：{mid}"),
            "gallery.queue_steer",
            receiver=queue,
        )
        safe_connect(
            queue,
            "undoRequested",
            lambda: queue_result.setText("撤销队列操作"),
            "gallery.queue_undo",
            receiver=queue,
        )
        layout.addWidget(queue)

        queue.setExpanded(True)

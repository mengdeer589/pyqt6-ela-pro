"""文件变更与 diff 示例页。

这一页专门展示 `ElaDiffView` / `ElaChatFileChanges` / 内置工具渲染器：
短 diff、多文件、长 diff（滚动 / 折叠 / 截断）、shell 控制台、write / patch。
"""

from __future__ import annotations

import traceback

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro.chat import (
    ElaChatRoleType,
    ElaChatWidget,
    installBuiltinToolRenderers,
    uninstallBuiltinToolRenderers,
)
from pyqt6_ela_pro._diff import diffLines

from .base_page import ExamplePage
from .chat_demo_kit import note, readonly_chat


class ChatFilesPage(ExamplePage):
    """文件变更 / diff / 内置工具渲染器展示。"""

    PAGE_TITLE = "文件与 Diff"

    def __init__(self, parent=None):
        self._chat: ElaChatWidget | None = None
        self._active_note = None
        self._sections: list = []
        super().__init__(parent)

    # -- 页面 --------------------------------------------------------------

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(
            note(
                self,
                "这一页只回答一个问题：模型改了文件之后，用户看到什么。"
                "每节都用真实公开 API 往下面的会话里追加一条工具调用，"
                "展开工具卡即可看到 ElaChatFileChanges / ElaDiffView 的真实形态。",
            )
        )
        self._chat = readonly_chat(
            self,
            empty_title="文件变更与 diff",
            empty_subtitle="点下面任意一节，往这里追加一条工具调用。",
        )
        self._chat.setFixedHeight(460)
        main_layout.addWidget(self._chat)

        installBuiltinToolRenderers()
        # 预填一条，页面打开就能看到真实的 diff 卡
        self._demo_edit()

        for section in (
            self._section_edit("01. edit：单文件 diff", self._demo_edit),
            self._section_edit("02. 多文件：文件变更列表", self._demo_multi_file),
            self._section_edit("03. 长 diff：滚动 / 折叠 / 截断", self._demo_long_diff),
            self._section_edit("04. shell：ANSI 控制台", self._demo_shell),
            self._section_edit("05. write / patch：文件段", self._demo_write_patch),
        ):
            main_layout.addLayout(section)

        row = QHBoxLayout()
        row.addWidget(self._button("卸载内置渲染器", self._fire(self._demo_uninstall)))
        row.addStretch()
        main_layout.addLayout(row)

    def _section_edit(self, title, method):
        box = QVBoxLayout()
        box.setSpacing(6)
        row = self._createHeaderRow(title, method)
        button = self._button("追加演示", self._fire(method))
        row.addWidget(button)
        box.addLayout(row)
        label = note(self, "点「追加演示」把这一节追加到上面的会话。")
        box.addWidget(label)
        self._active_note = label
        self._sections.append((label, method))
        return box

    # -- 演示 --------------------------------------------------------------

    def _demo_edit(self) -> None:
        """edit：单文件 diff（ElaChatFileChanges 每文件懒建 ElaDiffView）。"""
        view = self._chat.chatView()
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        patch = (
            "--- a/src/chat/blocks.py\n+++ b/src/chat/blocks.py\n"
            "@@ -40,7 +40,8 @@\n"
            " def build_card():\n"
            "-    height = 43\n"
            "+    height = 41\n"
            "+    padding = 3\n"
            "     return Card(height)\n"
        )
        callId = view.addToolCall(
            messageId,
            "edit",
            '{"path": "src/chat/blocks.py"}',
            metadata={
                "files": [
                    {
                        "file": "src/chat/blocks.py",
                        "patch": patch,
                        "additions": 2,
                        "deletions": 1,
                        "status": "modified",
                    }
                ]
            },
        )
        view.setToolCallResult(messageId, callId, "已应用 2 处修改", ok=True)
        view.endMessage(messageId)
        self._open_card(messageId, callId)
        self._note("edit：单文件 diff（行号 / +/- 底色 / 语法着色 / 折叠上下文）")

    def _demo_multi_file(self) -> None:
        """多文件：文件列表 + +N/-N + 显示其余。"""
        view = self._chat.chatView()
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        files = []
        for index in range(12):
            path = f"src/feature/module_{index:02d}.py"
            files.append(
                {
                    "file": path,
                    "patch": (
                        f"--- a/{path}\n+++ b/{path}\n@@ -1,3 +1,4 @@\n"
                        " import os\n-print('old')\n+print('new')\n"
                        "+print('done')\n"
                    ),
                    "additions": 2,
                    "deletions": 1,
                    "status": "modified",
                }
            )
        callId = view.addToolCall(
            messageId,
            "patch",
            '{"files": 12}',
            metadata={"files": files},
        )
        view.setToolCallResult(messageId, callId, "12 files changed", ok=True)
        view.endMessage(messageId)
        self._open_card(messageId, callId)
        self._note(
            "多文件：默认只展开前 8 个，其余折叠成「显示其余 N 个文件」；"
            "每行 +N/-N 与状态都来自主题令牌"
        )

    def _demo_long_diff(self) -> None:
        """长 diff：滚动条、折叠上下文与 4000 行上限。"""
        view = self._chat.chatView()
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        old = "\n".join(f"line {i}" for i in range(5000))
        new = old.replace("line 2500", "line 2500 changed")
        item = diffLines(old, new, "src/generated/large.py")
        callId = view.addToolCall(
            messageId,
            "patch",
            '{"file": "src/generated/large.py"}',
            metadata={
                "files": [
                    {
                        "file": item.path,
                        "before": old,
                        "after": new,
                        "additions": item.additions,
                        "deletions": item.deletions,
                        "status": "modified",
                    }
                ]
            },
        )
        view.setToolCallResult(messageId, callId, "large diff", ok=True)
        view.endMessage(messageId)
        self._open_card(messageId, callId)
        self._note(
            "长 diff：body 内部滚动（ElaScrollBar），未改动段折叠成可点的占位行；"
            "超过 ElaDiffView 上限会显示「已截断」"
        )

    def _demo_shell(self) -> None:
        """shell：ANSI 控制台 + 退出码。"""
        view = self._chat.chatView()
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        output = (
            "\x1b[32mcollected 32 items\x1b[0m\n"
            "tests/ela_chat/test_chat_parts.py ....\n"
            "tests/ela_chat/test_chat_tools.py ....\n"
            "\x1b[31m1 failed\x1b[0m, 31 passed in 2.41s\n"
        )
        callId = view.addToolCall(
            messageId,
            "shell",
            '{"command": "pytest -q"}',
            metadata={
                "status": "exited",
                "exit": 1,
                "command": "pytest -q",
            },
        )
        view.setToolCallResult(messageId, callId, output, ok=True)
        view.endMessage(messageId)
        self._open_card(messageId, callId)
        self._note(
            "shell：复用 ElaTerminalView（ANSI 色彩 / 行数上限 / 右键复制）；退出码在 metadata.exit"
        )

    def _demo_write_patch(self) -> None:
        """write / patch：文件段的追加 / 删除状态。"""
        view = self._chat.chatView()
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        callId = view.addToolCall(
            messageId,
            "write",
            '{"path": "src/new_feature.py"}',
            metadata={
                "files": [
                    {
                        "file": "src/new_feature.py",
                        "before": "",
                        "after": "def run():\n    return 42\n",
                        "additions": 2,
                        "deletions": 0,
                        "status": "added",
                    },
                    {
                        "file": "src/old_feature.py",
                        "before": "def run():\n    return 1\n",
                        "after": "",
                        "additions": 0,
                        "deletions": 2,
                        "status": "deleted",
                    },
                ]
            },
        )
        view.setToolCallResult(messageId, callId, "created + deleted", ok=True)
        view.endMessage(messageId)
        self._open_card(messageId, callId)
        self._note("write / patch：Added / Deleted 文件段与 +N/-N 独立展示")

    def _demo_uninstall(self) -> None:
        removed = uninstallBuiltinToolRenderers()
        self._note("已卸载内置渲染器：" + (", ".join(removed) if removed else "无"))

    # -- 工具 --------------------------------------------------------------

    def _open_card(self, messageId: int, callId: str) -> None:
        view = self._chat.chatView()
        bubble = view.bubble(messageId)
        if bubble is None:
            return
        # 工具卡在「工具调用 (N)」外层折叠面板里，两层都展开才看得到 diff。
        for panel in bubble.toolPanels():
            panel.setOpened(True)
        card = bubble._tool_cards.get(callId)
        if card is not None:
            card.setOpened(True)

    def _fire(self, callback):
        def run():
            try:
                callback()
            except Exception:
                traceback.print_exc()

        return run

    def _button(self, text, callback):
        button = ElaButton(text, variant="outlined", size="small", parent=self)
        button.setFixedWidth(max(110, 13 * len(text) + 26))
        button.clicked.connect(callback)
        return button

    def _note(self, text: str) -> None:
        if self._active_note is not None:
            self._active_note.setText(text)


__all__ = ["ChatFilesPage"]

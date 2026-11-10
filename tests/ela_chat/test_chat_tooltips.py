"""chat 内悬浮提示契约：统一走库内 ElaToolTip，禁止原生 QToolTip。"""

from __future__ import annotations

import ast
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QHelpEvent

from pyqt6_ela_pro import chat as chat_package
from pyqt6_ela_pro.chat.blocks.tool_cards import (
    ContextToolGroupCard,
    ToolCallCard,
    ToolGroupPanel,
)
from pyqt6_ela_pro._diff import ElaDiffFile
from pyqt6_ela_pro.chat.blocks.file_changes import ElaChatFileChanges
from pyqt6_ela_pro.chat.blocks.working import ElaChatWorkingRow
from pyqt6_ela_pro.chat.message import ElaChatToolCall
from pyqt6_ela_pro.chat.selector import ElaChatSelector, ElaChatSelectorItem
from pyqt6_ela_pro.chat.suggestions import ElaChatSuggestion, SuggestionPopup
from pyqt6_ela_pro.tooltip_targets import ACTION_TOOLTIP_PROPERTY
from pyqt6_ela_pro.tooltips import _tooltip_dict


def test_chat_has_no_native_set_tooltip():
    """原生 QToolTip 不跟主题，chat 内一律用 set_tooltip / ElaToolTip。"""
    root = Path(chat_package.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setToolTip"
            ):
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == []


class TestToolCallTooltips:
    def test_group_panel_summary_binds_library_tooltip(self, qapp, make):
        panel = make(ToolGroupPanel)
        panel.show()
        panel.resize(220, 60)
        summary = "shell · " + "very-long-command " * 8
        panel.setCounts(1, 1, summary=summary)
        qapp.processEvents()

        tip = _tooltip_dict.get(panel._header)
        assert tip is not None
        assert tip._text == " ".join(summary.split())
        # 原生属性必须保持为空，防止以后又退回 QToolTip
        assert panel._title_label.toolTip() == ""

        panel.resize(1600, 60)
        qapp.processEvents()
        assert panel._header not in _tooltip_dict

    def test_tool_card_header_tooltip_only_when_elided(self, qapp, make):
        long = "x" * 30
        card = make(
            ToolCallCard,
            None,
            None,
            "shell",
            '{"command": "%s"}' % long,
        )
        card.show()
        card.resize(240, 40)
        qapp.processEvents()

        tip = _tooltip_dict.get(card._header)
        assert tip is not None
        assert "工具调用：shell" in tip._text
        assert long[:40] in tip._text

        card.resize(1600, 40)
        qapp.processEvents()
        assert card._header not in _tooltip_dict

    def test_context_group_row_shows_full_text(self, qapp, make):
        group = make(ContextToolGroupCard)
        group.resize(420, 80)
        call = ElaChatToolCall(
            id="ctx-1",
            name="grep",
            arguments='{"pattern": "%s"}' % ("p" * 100),
        )
        group.addToolCall(call)

        row = group._call_rows["ctx-1"]
        assert row.text().endswith("…")
        tip = _tooltip_dict.get(row)
        assert tip is not None
        assert tip._text.startswith("grep")
        assert "p" * 80 in tip._text

    def test_file_changes_header_shows_full_path(self, qapp, make):
        widget = make(ElaChatFileChanges)
        path = (
            "E:/python_project/elawidgettools/pyqt6_ela_pro/chat/blocks/tool_cards.py"
        )
        widget.setFiles([ElaDiffFile(path=path)])
        tip = _tooltip_dict.get(widget._rows[0]["header"])
        assert tip is not None
        assert tip._text == path

    def test_working_row_is_hoverable_and_binds_tooltip(self, qapp, make):
        row = make(ElaChatWorkingRow)
        row.resize(320, 28)
        row.setText("正在运行一个非常长的命令 " + "y" * 80)

        # 整行不能再鼠标穿透，否则 label 的 tooltip 永远不会触发
        assert (
            row.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False
        )
        tip = _tooltip_dict.get(row._label)
        assert tip is not None
        assert tip._text.startswith("正在运行")


class TestNonWidgetTooltips:
    def test_suggestion_item_uses_library_tooltip(self, qapp, make):
        popup = make(SuggestionPopup)
        popup.open([ElaChatSuggestion(id="a", label="A", description="补全项说明")])
        qapp.processEvents()

        view = popup._view
        index = popup._model.index(0, 0)
        pos = view.visualRect(index).center()
        event = QHelpEvent(QEvent.Type.ToolTip, pos, view.viewport().mapToGlobal(pos))
        adapter = popup._item_tooltip_adapter
        assert adapter.eventFilter(view.viewport(), event) is True
        assert adapter.tooltip()._text == "补全项说明"

    def test_selector_menu_description_kept_out_of_native_tooltip(self, qapp, make):
        selector = make(
            ElaChatSelector,
            "模型",
            [ElaChatSelectorItem(id="a", label="A", description="菜单项说明")],
            "a",
        )
        action = selector._actions["a"]
        assert action.property(ACTION_TOOLTIP_PROPERTY) == "菜单项说明"
        assert "菜单项说明" not in action.toolTip()

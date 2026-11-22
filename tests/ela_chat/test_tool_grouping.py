"""上下文工具分组：宿主工具名、连续性与摘要。"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro.chat import (
    ContextToolGroupCard,
    ElaChatWidget,
    ToolCallCard,
    clearToolRenderers,
    registerContextTool,
    registerToolRenderer,
    resetContextTools,
    toolRendererGroupable,
)
from pyqt6_ela_pro.chat.message import ElaChatToolCall


@pytest.fixture(autouse=True)
def _clean_grouping():
    clearToolRenderers()
    resetContextTools()
    yield
    clearToolRenderers()
    resetContextTools()


def _group_counts(chat: ElaChatWidget, mid: int) -> list[int]:
    return [
        card.count()
        for panel in chat.toolPanels(mid)
        for card in panel.findChildren(ContextToolGroupCard)
    ]


def _tool_card_count(chat: ElaChatWidget, mid: int) -> int:
    return sum(len(panel.findChildren(ToolCallCard)) for panel in chat.toolPanels(mid))


def test_host_groupable_tool_joins_group(make, qapp):
    registerToolRenderer("read_file", lambda ctx: QWidget(), groupable=True)
    chat = make(ElaChatWidget)
    view = chat.chatView()
    mid = chat.beginAssistantMessage()
    view.addToolCall(mid, "read_file", '{"path":"a.py"}')
    view.addToolCall(mid, "read_file", '{"path":"b.py"}')
    assert _group_counts(chat, mid) == [2]
    assert _tool_card_count(chat, mid) == 0


def test_non_context_tool_breaks_group(make, qapp):
    chat = make(ElaChatWidget)
    view = chat.chatView()
    mid = chat.beginAssistantMessage()
    for name in ("read", "bash", "read"):
        view.addToolCall(mid, name, "{}")
    assert _group_counts(chat, mid) == [1, 1]
    assert _tool_card_count(chat, mid) == 1


def test_context_renderer_default_exits_group(make, qapp):
    registerToolRenderer("read", lambda ctx: QWidget())
    chat = make(ElaChatWidget)
    view = chat.chatView()
    mid = chat.beginAssistantMessage()
    view.addToolCall(mid, "read", "{}")
    view.addToolCall(mid, "read", "{}")
    assert _group_counts(chat, mid) == []
    assert _tool_card_count(chat, mid) == 2


def test_begin_step_splits_group(make, qapp):
    chat = make(ElaChatWidget)
    view = chat.chatView()
    mid = chat.beginAssistantMessage()
    view.addToolCall(mid, "read", "{}")
    view.appendText(mid, "step1")
    view.beginStep(mid)
    view.addToolCall(mid, "read", "{}")
    assert _group_counts(chat, mid) == [1, 1]


def test_summary_uses_registered_label(make):
    registerContextTool("read_file", label="个文件")
    card = make(ContextToolGroupCard)
    card.addToolCall(ElaChatToolCall(id="1", name="read_file", arguments="{}"))
    assert card.count() == 1
    assert card.summary() == "1 个文件"


def test_summary_falls_back_to_tool_name(make):
    card = make(ContextToolGroupCard)
    card.addToolCall(ElaChatToolCall(id="1", name="custom_tool", arguments="{}"))
    card.addToolCall(ElaChatToolCall(id="2", name="custom_tool", arguments="{}"))
    assert card.summary() == "custom_tool×2"


def test_unregistered_host_tool_is_not_groupable():
    assert toolRendererGroupable("read_file") is False
    registerContextTool("read_file")
    assert toolRendererGroupable("read_file") is True

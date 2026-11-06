"""回归测试（第七批）：全库审查确认的数据完整性 / 语义修复。

覆盖：journal 复用增量落盘、math_lite 围栏、chat spacer 追加与离屏 id、
diff 非 1 起始 hunk 语法映射、blueprint 连线标签、tool metadata 保留。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro._diff import parseUnifiedDiff
from pyqt6_ela_pro.blueprint import ElaBlueprintCanvas
from pyqt6_ela_pro.blueprint.model import ElaBlueprintGraph, ElaBlueprintNode
from pyqt6_ela_pro.chat import (
    ElaChatMessage,
    ElaChatToolCall,
    ElaChatToolStatusType,
    ElaChatTurnJournal,
    ElaChatView,
)
from pyqt6_ela_pro.chat.blocks import ToolCallCard
from pyqt6_ela_pro.ela_diff_view import ElaDiffView
from pyqt6_ela_pro.math_lite.render import extract_math


def _rows(start: int, count: int):
    return [
        ElaChatMessage(id=start + i, role="user", text=f"m{start + i}").toDict()
        for i in range(count)
    ]


class TestJournalReuse:
    def test_second_turn_still_dumps_new_lines(self):
        journal = ElaChatTurnJournal(messageId=1)
        journal.begin(1).text("first").end()
        first = journal.dumpsNewLines()
        assert first

        journal.begin(1).text("second").end()
        second = journal.dumpsNewLines()
        assert second, "复用 journal 后第二回合增量落盘为空"
        assert "second" in second
        assert "first" not in second


class TestMathFence:
    def test_code_block_macros_are_not_removed(self):
        text = "```python\n\\newcommand{\\R}{\\mathbb{R}}\n$x$ in code\n```\n"
        out, maths = extract_math(text, "@@MATH{}@@")
        assert "\\newcommand" in out
        assert maths == []

    def test_four_backtick_fence_does_not_close_on_three(self):
        text = "````markdown\n```\n$x$\n```\n````\n"
        out, maths = extract_math(text, "@@MATH{}@@")
        assert maths == []
        assert "$x$" in out

    def test_inline_math_outside_fence_still_extracts(self):
        out, maths = extract_math("value $x$", "@@MATH{}@@")
        assert maths and maths[0][0] == "x"
        assert "@@MATH0@@" in out


class TestChatVirtualList:
    def test_append_to_nonempty_view_does_not_enter_spacer(self, qapp):
        view = ElaChatView()
        view.addMessage("user", "old")
        assert view.restoreMessages(_rows(1000, 201))
        assert view.count() == 202
        assert view._virtual_list_mode is False

    def test_offscreen_id_collision_is_rejected(self, qapp):
        view = ElaChatView()
        assert view.restoreMessages(_rows(1, 220))
        target = next(m.id for m in view.messages() if view.bubble(m.id) is None)
        with pytest.raises(ValueError):
            view.addMessage("user", "duplicate", messageId=target)


class TestDiffNonOneHunk:
    def test_syntax_spans_use_absolute_line_numbers(self, qapp):
        diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -100,2 +100,3 @@
-old = 1
+new = 2
+added = 3
 context = 4
"""
        view = ElaDiffView()
        view.setFiles(parseUnifiedDiff(diff))
        assert view._spans_by_block, "非 1 起始 hunk 的语法高亮全部丢失"
        assert all(view._spans_by_block.values())


class TestBlueprintEdgeLabel:
    def _graph(self):
        graph = ElaBlueprintGraph()
        start = ElaBlueprintNode("start", "A", "a")
        start.add_output("out")
        end = ElaBlueprintNode("end", "B", "b")
        end.add_input("in")
        graph.add_node(start)
        graph.add_node(end)
        graph.add_edge("a", "out", "b", "in", label="hello")
        return graph

    def test_graph_roundtrip_keeps_label(self):
        graph = ElaBlueprintGraph.from_dict(self._graph().to_dict())
        assert graph.edges()[0].label == "hello"

    def test_canvas_roundtrip_keeps_label(self, qapp):
        canvas = ElaBlueprintCanvas()
        canvas.from_dict({"graph": self._graph().to_dict()})
        assert canvas.graph.edges()[0].label == "hello"


class TestToolCallMetadata:
    def test_set_status_keeps_metadata(self, qapp):
        call = ElaChatToolCall(
            id="t1",
            name="edit",
            metadata={"files": [{"file": "a.py"}]},
        )
        card = ToolCallCard(tool_call=call)
        card.setStatus(ElaChatToolStatusType.Aborted)
        assert card._renderer_context().metadata == {"files": [{"file": "a.py"}]}
        card.deleteLater()
        qapp.processEvents()

"""历史分段批量物化的性能契约：面板 / 用量徽标只统一显示一次。"""

from __future__ import annotations

import pyqt6_ela_pro.chat.bubble_stats as bubble_stats
import pyqt6_ela_pro.chat.bubble_tools as bubble_tools
from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatStats,
    ElaChatToolCall,
    StatsBadge,
    ToolGroupPanel,
)


class _CountingStatsBadge(StatsBadge):
    show_calls = 0

    def show(self) -> None:
        type(self).show_calls += 1
        super().show()


class _CountingToolGroupPanel(ToolGroupPanel):
    show_calls = 0

    def show(self) -> None:
        type(self).show_calls += 1
        super().show()


def _tool_part(partId: str, name: str = "shell") -> ElaChatPart:
    return ElaChatPart(
        id=partId,
        kind=ElaChatPartKindType.Tool,
        tool_call=ElaChatToolCall(id=partId, name=name, arguments='{"command": "ls"}'),
    )


def _stats_part(partId: str, tokens: int) -> ElaChatPart:
    return ElaChatPart(
        id=partId,
        kind=ElaChatPartKindType.Stats,
        stats=ElaChatStats(total_tokens=tokens),
    )


class TestBulkMaterialize:
    def test_panels_and_badges_show_once(self, qapp, make, monkeypatch):
        _CountingStatsBadge.show_calls = 0
        _CountingToolGroupPanel.show_calls = 0
        monkeypatch.setattr(bubble_stats, "StatsBadge", _CountingStatsBadge)
        monkeypatch.setattr(bubble_tools, "ToolGroupPanel", _CountingToolGroupPanel)

        bubble = make(ElaChatBubble)
        bubble.resize(640, 480)
        bubble.show()
        qapp.processEvents()

        parts = [
            _tool_part("t1"),
            _tool_part("t2"),
            _tool_part("t3"),
            _stats_part("s1", 10),
            _stats_part("s2", 20),
            _stats_part("s3", 30),
        ]
        assert bubble.setParts(parts) is True
        qapp.processEvents()

        # 3 个工具同属一步 -> 1 个面板；footer 模式只显示最后一个用量徽标。
        assert _CountingToolGroupPanel.show_calls == 1
        assert _CountingStatsBadge.show_calls <= 2

        panels = bubble.toolPanels()
        assert len(panels) == 1
        assert panels[0].isVisibleTo(bubble) is True

        last = bubble.statsBadge()
        assert isinstance(last, _CountingStatsBadge)
        assert last.isVisibleTo(bubble) is True
        assert [part.id for part in bubble.parts()] == [
            "t1",
            "t2",
            "t3",
            "s1",
            "s2",
            "s3",
        ]
        assert bubble.stats().total_tokens == 60

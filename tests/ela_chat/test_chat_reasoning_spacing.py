"""折叠思考块（默认形态）显示时裁掉尾部空白，数据保持原样。

`ReasoningBlock` 的正文是 PlainText 标签：模型以若干换行收尾一段思考时，每个换行都真的
画一行，流式期间「最后一句思考」与下面的工具调用卡之间就多出数行空白，收折后又消失
（症状只在实时渲染时可见）。内联形态走 Markdown 导入器，本来就丢尾部空行 —— 这里把两条
形态对齐，并钉住「裁显示不裁数据」。
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from _qthelpers import wait_until as _wait_until
from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatView,
    ReasoningBlock,
)

#: 故意带内部空行：验证「只裁尾部、段间距保留」
BODY = "第一句思考。\n\n第二句思考，长到需要在卡片里折一次行才看得出现在是不是同一行。\n\n第三句思考。"
TAILS = ["", "\n", "\n\n", "\n\n\n\n", "  \t\n\n"]


def _hosted_block(make, qapp):
    """把折叠块放进带拉伸的宿主里（否则宿主把剩余空间灌进被测控件），并等布局跑完。"""
    block = make(ReasoningBlock)
    host = make(QWidget)
    host.resize(460, 600)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.addWidget(block)
    layout.addStretch(1)
    block.setOpened(True)
    host.show()
    qapp.processEvents()
    return block


def _settle(block, qapp) -> None:
    """等自增高布局跑完（``setText`` 只投递 LayoutRequest，一次 processEvents 不够）。"""
    label = block.label()
    assert _wait_until(
        qapp,
        lambda: (
            label.height() > 0 and label.height() == label.heightForWidth(label.width())
        ),
        timeout_ms=5000,
    )


class TestTrailingWhitespaceIsNotDisplayed:
    @pytest.mark.parametrize("tail", TAILS, ids=[repr(t) for t in TAILS])
    def test_label_strips_display_only(self, qapp, make, tail):
        block = _hosted_block(make, qapp)
        block.setText(BODY + tail)
        _settle(block, qapp)

        assert block.label().text() == BODY
        assert block.text() == BODY + tail, (
            "数据必须保真（part.text / journal / 导出口径）"
        )

    def test_stream_append_keeps_blanks_out_of_view(self, qapp, make):
        block = _hosted_block(make, qapp)
        for chunk in ("第一句思考。\n\n", "第三句思考。\n", "\n", "\n"):
            block.appendText(chunk)
            qapp.processEvents()
        _settle(block, qapp)

        assert block.label().text() == "第一句思考。\n\n第三句思考。"
        assert block.text().endswith("\n\n\n")

    def test_height_ignores_trailing_blanks(self, qapp, make):
        """同一段思考，尾部 0 个与 4 个换行的可见高度必须一致（回退即红）。"""
        plain = _hosted_block(make, qapp)
        padded = _hosted_block(make, qapp)
        plain.setText(BODY)
        padded.setText(BODY + "\n\n\n\n")
        _settle(plain, qapp)
        _settle(padded, qapp)

        assert padded.height() == plain.height()
        assert padded.label().height() == plain.label().height()
        # 鉴别力：正文真的折了行（没折行时两条高度天然相等，用例就没有意义）
        assert plain.label().height() > plain.label().fontMetrics().lineSpacing()


class TestViewLevelGap:
    def _streamed_layout(self, qapp, make, tail):
        view = make(ElaChatView)
        view.resize(760, 700)
        view.show()
        qapp.processEvents()

        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginReasoning(mid)
        view.appendReasoning(mid, BODY + tail)
        view.addToolCall(mid, "read", '{"path": "a.py"}')

        def widgets():
            layout = view.bubble(mid)._parts_layout
            return [
                layout.itemAt(i).widget()
                for i in range(layout.count())
                if layout.itemAt(i).widget() is not None
            ]

        # 折叠块按内容撑开 + 工具面板落位，都要等布局跑完
        assert _wait_until(qapp, lambda: len(widgets()) >= 2)
        block, panel = widgets()[0], widgets()[1]
        assert type(block).__name__ == "ReasoningBlock"
        assert type(panel).__name__ == "ToolGroupPanel"
        _settle(block, qapp)
        assert _wait_until(qapp, lambda: panel.y() >= block.y() + block.height())
        return view, block, panel

    def test_tool_panel_sits_right_below_thinking(self, qapp, make):
        """思考卡与工具面板之间的间距不随尾部换行变化（用户报的 3-4 行空白）。"""
        _, plain_block, plain_panel = self._streamed_layout(qapp, make, "")
        _, padded_block, padded_panel = self._streamed_layout(qapp, make, "\n\n\n\n")

        assert padded_block.height() == plain_block.height()
        assert padded_panel.y() == plain_panel.y()
        # 间距就是布局 spacing 本身，没有额外的空白行
        assert plain_panel.y() - (plain_block.y() + plain_block.height()) <= 8
        # 鉴别力：卡里确实画出了折行的正文，而不是空卡
        assert (
            plain_block.label().height()
            > plain_block.label().fontMetrics().lineSpacing()
        )

    def test_data_still_carries_trailing_blanks(self, qapp, make):
        """显示裁掉之后，快照与分段数据仍是原文（重发 / 导出语义不变）。"""
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginReasoning(mid)
        view.appendReasoning(mid, BODY + "\n\n\n")
        view.endReasoning(mid, 800.0)

        raw = BODY + "\n\n\n"
        assert view.message(mid).reasoning == raw
        parts = [
            part
            for part in view.bubble(mid).parts()
            if part.kind == ElaChatPartKindType.Reasoning
        ]
        assert parts[0].text == raw

    def test_restore_path_strips_display(self, qapp, make):
        """整体设置（恢复历史 / ``setReasoning``）同样只裁显示。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setReasoning(BODY + "\n\n\n\n", 900.0)
        assert bubble.reasoningBlock().label().text() == BODY
        assert bubble.reasoningBlock().text() == BODY + "\n\n\n\n"

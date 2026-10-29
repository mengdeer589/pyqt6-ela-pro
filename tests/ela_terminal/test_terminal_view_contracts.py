"""``ElaTerminalView`` 的 view 层契约回归（parser 层测得很足，view 层没测的那块）。

钉的四条：

1. **未被 ``\\n`` 收口的最后一行必须显示 / 计数 / 导出** —— git、ssh、sudo
   的口令提示全是这个形状，而真实终端就把它显示在光标处；
2. 换配色 / 换主题 / 改字号**不得劫持滚动位置**；
3. ``setHighlightColor(None)`` 回到有效色，用户覆盖跨换肤保留；
4. 过滤态下尾行按过滤词判定可见性。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor

from pyqt6_ela_pro.terminal_view import (
    _HIGHLIGHT,
    _HIGHLIGHT_RATIO,
    ElaTerminalView,
    _blend,
)


def _drain(qapp) -> None:
    for _ in range(4):
        qapp.processEvents()


def _scrollbar(view):
    return view._edit.verticalScrollBar()


def _first_fragment_color(view) -> QColor:
    """文档首个片段的前景色（样式是否真的落到屏上，用它断言）。"""
    block = view._edit.document().begin()
    it = block.begin()
    if it.atEnd():
        return QColor()
    return it.fragment().charFormat().foreground().color()


class TestUnterminatedLastLine:
    def test_shown_in_widget(self, make, qapp):
        view = make(ElaTerminalView)
        view.show()
        _drain(qapp)
        view.append("Enter password for repo: ")
        _drain(qapp)
        assert "Enter password for repo: " in view._edit.toPlainText()
        assert view.visibleLineCount() == 1

    def test_included_in_plain_text(self, make, qapp):
        view = make(ElaTerminalView)
        view.append("Password: ")
        _drain(qapp)
        assert view.toPlainText() == "Password: "

    def test_survives_into_save(self, make, qapp, tmp_path):
        view = make(ElaTerminalView)
        view.append("no trailing newline")
        _drain(qapp)
        target = tmp_path / "out.txt"
        assert view.saveTo(str(target)) is True
        assert "no trailing newline" in target.read_text(encoding="utf-8")

    def test_closing_it_makes_exactly_one_line(self, make, qapp):
        # 「Password: 」与「abc」之间没有换行 —— 真实终端里就是**同一行**，
        # 不能因为尾行机制把它拆成两块，也不能重复显示
        view = make(ElaTerminalView)
        view.append("Password: ")
        _drain(qapp)
        view.append("abc\n")
        _drain(qapp)
        text = view._edit.toPlainText()
        assert text.count("Password: ") == 1
        assert text == "Password: abc"
        assert view._edit.document().blockCount() == 1

    def test_tail_then_more_lines(self, make, qapp):
        view = make(ElaTerminalView)
        view.append("first\n")
        view.append("second\n")
        view.append("third")
        _drain(qapp)
        assert view._edit.document().blockCount() == 3
        assert view.visibleLineCount() == 3
        assert view.toPlainText().splitlines() == ["first", "second", "third"]

    def test_cleared_with_clear(self, make, qapp):
        view = make(ElaTerminalView)
        view.append("dangling")
        _drain(qapp)
        view.clear()
        _drain(qapp)
        assert view.toPlainText() == ""
        assert view.visibleLineCount() == 0
        assert view._doc_tail is False

    def test_tail_content_change_repaints(self, make, qapp):
        """回归：``\\r`` 重画当前行时**屏上的文档**必须跟着变。

        原先 ``_flush_render`` 只比较「尾行有无」，内容变了也被当成没变 ——
        进度条 / spinner 冻在第一帧（实测文档停在 ``' 10%'`` 而模型已到
        ``' 90%'``），要到整行收口才跳一次。
        """
        view = make(ElaTerminalView)
        view.show()
        _drain(qapp)
        view.append("\r 10%")
        _drain(qapp)
        assert view._edit.toPlainText() == " 10%"
        view.append("\r 90%")
        _drain(qapp)
        assert view._edit.toPlainText() == " 90%"
        assert view._edit.document().blockCount() == 1
        assert view.toPlainText() == " 90%"

    def test_style_change_on_redraw_still_repaints(self, make, qapp):
        # \r 重画时**文本没变、样式变了**也必须重画：只比较尾行有无 / 文本
        # 会把颜色更新整批跳过（与进度条冻结是同一个根因）
        view = make(ElaTerminalView)
        view.append("\x1b[31mstyled\x1b[0m")
        _drain(qapp)
        assert _first_fragment_color(view).name() == view._palette["red"].name()
        view.append("\r\x1b[32mstyled\x1b[0m")
        _drain(qapp)
        assert view._edit.toPlainText() == "styled"
        assert view.visibleLineCount() == 1
        assert _first_fragment_color(view).name() == view._palette["green"].name()

    def test_filter_hides_tail_without_match(self, make, qapp):
        view = make(ElaTerminalView)
        view.append("keep me\n")
        view.append("drop me")
        _drain(qapp)
        view.setFilter("keep")
        view.applyFilterNow()
        _drain(qapp)
        assert "drop me" not in view._edit.toPlainText()
        # 导出不受过滤影响
        assert "drop me" in view.toPlainText()
        view.setFilter("")
        view.applyFilterNow()
        _drain(qapp)
        assert "drop me" in view._edit.toPlainText()


class TestFilteredTailLiveUpdate:
    """F23 回归：过滤态下「当前行」也随 ``append`` 实时更新。

    旧实现在 ``_filter`` 非空且无完整行时直接 return（不启动任何定时器）：
    包含过滤词的未收口尾行要等下一条完整行（或过滤变更）才会出现，
    ``\\r`` 进度条在过滤态下同样被冻在上一帧。
    """

    def test_matching_tail_appears_live(self, make, qapp):
        view = make(ElaTerminalView)
        view.append("keep me\n")
        _drain(qapp)
        view.setFilter("secret")
        view.applyFilterNow()
        _drain(qapp)

        view.append("secret-code")  # 未收口，且包含过滤词
        _drain(qapp)

        assert "secret-code" in view._edit.toPlainText()

    def test_non_matching_tail_stays_hidden(self, make, qapp):
        view = make(ElaTerminalView)
        view.setFilter("keep")
        view.applyFilterNow()
        _drain(qapp)

        view.append("drop me")
        _drain(qapp)

        assert "drop me" not in view._edit.toPlainText()

    def test_cr_redraw_under_filter_updates(self, make, qapp):
        view = make(ElaTerminalView)
        view.setFilter("progress")
        view.applyFilterNow()
        _drain(qapp)

        view.append("\rprogress  10%")
        _drain(qapp)
        assert "progress  10%" in view._edit.toPlainText()

        view.append("\rprogress  90%")
        _drain(qapp)
        assert "progress  90%" in view._edit.toPlainText()
        assert "10%" not in view._edit.toPlainText()
        assert view._edit.document().blockCount() == 1


class TestTailRedrawDoesNotAccumulateBlocks:
    """``\\r`` 重画（进度条 / spinner）不得让文档块数无界增长。

    尾块被摘空后那个空块本该被下一批内容复用；原先 ``_render_rows`` 只按
    ``_doc_lines`` 决定要不要 ``insertBlock``，于是每次重画都白白多留一个空块
    —— 块数逐帧增长而 ``_doc_lines`` 不动，长任务把文档撑到上万块。
    """

    def test_redraw_keeps_block_count_flat(self, make, qapp):
        view = make(ElaTerminalView, maxLines=0)
        view.resize(640, 320)
        view.show()
        _drain(qapp)

        view.append("line 1\n")
        view.append("line 2\n")
        _drain(qapp)
        assert view._edit.document().blockCount() == view._doc_lines == 2

        # 第一次重画会多出「当前行」那一个块；之后每次重画都只在它里面改写
        view.append("\r  1%")
        _drain(qapp)
        doc = view._edit.document()
        baseline = doc.blockCount()
        assert baseline == view._doc_lines + 1

        for percent in range(2, 40):
            view.append(f"\r  {percent}%")
            _drain(qapp)
            assert doc.blockCount() == baseline, (
                f"第 {percent} 次重画后块数从 {baseline} 涨到 {doc.blockCount()}"
            )

        # 「当前行」仍在屏上，且内容是最新的
        last = doc.findBlockByNumber(doc.blockCount() - 1).text()
        assert last.strip() == "39%"
        assert view._doc_tail is True
        assert doc.blockCount() == view._doc_lines + 1

    def test_tail_commit_does_not_leave_blank_line(self, make, qapp):
        view = make(ElaTerminalView, maxLines=0)
        view.resize(640, 320)
        view.show()
        _drain(qapp)

        view.append("first\n")
        view.append("partial")
        _drain(qapp)
        view.append(" done\n")
        _drain(qapp)

        doc = view._edit.document()
        texts = [doc.findBlockByNumber(i).text() for i in range(doc.blockCount())]
        assert texts == ["first", "partial done"], f"文档内容：{texts}"
        assert view._doc_lines == 2


class TestScrollIsNotHijacked:
    @pytest.fixture
    def scrolled_up(self, make, qapp):
        view = make(ElaTerminalView, maxLines=0)
        view.show()
        _drain(qapp)
        for i in range(400):
            view.append(f"line {i}\n")
        _drain(qapp)
        _scrollbar(view).setValue(0)
        _drain(qapp)
        assert _scrollbar(view).value() == 0
        assert view.isFollowing() is False
        return view

    def test_palette_change_keeps_position(self, scrolled_up, qapp):
        _scrollbar(scrolled_up).setValue(0)
        _drain(qapp)
        scrolled_up.setPaletteName("classic")
        _drain(qapp)
        assert _scrollbar(scrolled_up).value() == 0
        assert scrolled_up.isFollowing() is False

    def test_font_size_change_keeps_position(self, scrolled_up, qapp):
        before = _scrollbar(scrolled_up).value()
        scrolled_up.setFontSize(14)
        _drain(qapp)
        assert _scrollbar(scrolled_up).value() == before

    def test_filter_change_still_goes_to_bottom(self, scrolled_up, qapp):
        # 过滤词变了 = 用户要看新结果，必须回底部（与换配色不同）
        _scrollbar(scrolled_up).setValue(0)
        _drain(qapp)
        scrolled_up.setFilter("line 3")
        scrolled_up.applyFilterNow()
        _drain(qapp)
        assert _scrollbar(scrolled_up).value() == _scrollbar(scrolled_up).maximum()


class TestHighlightColor:
    def test_none_restores_derived_default(self, make):
        view = make(ElaTerminalView)
        derived = _blend(view._palette["background"], _HIGHLIGHT, _HIGHLIGHT_RATIO)
        view.setHighlightColor(QColor("#ff0000"))
        assert view._highlight == QColor("#ff0000")
        view.setHighlightColor(None)
        assert view._highlight.isValid(), (
            "None 不能是 QColor()（非法色会让高亮整块不画）"
        )
        assert view._highlight == derived

    def test_override_survives_palette_change(self, make):
        view = make(ElaTerminalView)
        view.setHighlightColor(QColor("#ff0000"))
        view.setPaletteName("classic")
        assert view._highlight == QColor("#ff0000")
        view.setPaletteName("default")
        assert view._highlight == QColor("#ff0000")

    @pytest.mark.parametrize("bad", ["not-a-color", "#12345", QColor()])
    def test_invalid_color_is_rejected(self, make, bad):
        view = make(ElaTerminalView)
        before = QColor(view._highlight)
        view.setHighlightColor(bad)
        assert view._highlight.isValid()
        if isinstance(bad, QColor) and not bad.isValid():
            assert view._highlight == before

    def test_highlight_is_actually_painted(self, make, qapp):
        """高亮色必须真的落到文档里（非法色时 colorValid=False 且不画）。"""
        view = make(ElaTerminalView)
        view.append("needle here\n")
        _drain(qapp)
        view.setFilter("needle")
        view.applyFilterNow()
        _drain(qapp)
        view.setHighlightColor(None)
        _drain(qapp)
        found = False
        block = view._edit.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fmt = it.fragment().charFormat()
                bg = fmt.background().color()
                if bg.isValid() and bg.name() == view._highlight.name():
                    found = True
                it += 1
            block = block.next()
        assert found, f"文档里找不到用高亮色 {view._highlight.name()} 涂的片段"


class TestGutterWidth:
    def test_gutter_width_follows_font_size(self, make, qapp):
        """行号槽宽按**绘制字体**（_gutter_font）量，不是 gutter 的继承字体。"""
        from PyQt6.QtGui import QFontMetrics

        from pyqt6_ela_pro.terminal_view import _GUTTER_MIN_WIDTH, _GUTTER_PAD

        view = make(ElaTerminalView)
        view.resize(700, 300)
        view.show()
        _drain(qapp)
        narrow = view._gutter.width()

        view.setFontSize(24)
        _drain(qapp)

        digits = len(str(max(1, view.maxLines() or 9999)))
        expected = max(
            _GUTTER_MIN_WIDTH,
            _GUTTER_PAD * 2
            + QFontMetrics(view._gutter_font).horizontalAdvance("8") * digits,
        )
        assert view._gutter.width() == expected
        assert view._gutter.width() > narrow

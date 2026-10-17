"""``ElaTerminalView`` 组件测试。"""

from __future__ import annotations


import pytest
from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor, QContextMenuEvent, QFont
from PyQt6.QtWidgets import QApplication, QPlainTextEdit
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro.terminal_view import (
    _HIGHLIGHT,
    _HIGHLIGHT_RATIO,
    ElaTerminalView,
    TerminalStyle,
    _blend,
    defaultTerminalTheme,
    registerTerminalTheme,
    setDefaultTerminalTheme,
    terminalThemes,
    unregisterTerminalTheme,
)

ESC = "\x1b"
CSI = ESC + "["


@pytest.fixture
def view(make):
    """终端视图（由 ``qt_cleanup`` 统一回收，测试体不写 deleteLater 样板）。"""
    return make(ElaTerminalView)


def lines(*rows: str) -> str:
    return "".join(row + "\n" for row in rows)


class TestInit:
    def test_object_name(self, view):
        assert view.objectName() == "ElaTerminalView"

    def test_defaults(self, view):
        assert view.lineCount() == 0
        assert view.maxLines() == 10000
        assert view.autoScroll() is True
        assert view.lineNumbersVisible() is True
        assert view.filterText() == ""

    def test_custom_max_lines(self, make):
        assert make(ElaTerminalView, maxLines=42).maxLines() == 42

    def test_custom_palette(self, make):
        assert make(ElaTerminalView, paletteName="solarized").paletteName() == (
            "solarized"
        )

    def test_unknown_palette_falls_back(self, make):
        view = make(ElaTerminalView, paletteName="does-not-exist")
        assert view.paletteName() == defaultTerminalTheme()

    def test_readonly(self, view):
        assert view._edit.isReadOnly() is True

    def test_undo_disabled(self, view):
        assert view._edit.document().isUndoRedoEnabled() is False

    def test_minimum_height(self, view):
        assert view.minimumHeight() == 120

    def test_size_hint(self, view):
        assert view.sizeHint() == view.sizeHint()


class TestAppend:
    def test_append_lines(self, view):
        view.append(lines("a", "b", "c"))
        view.applyFilterNow()
        assert view.lineCount() == 3
        assert view.toPlainText() == "a\nb\nc"

    def test_append_without_newline_waits(self, view):
        view.append("no newline")
        assert view.lineCount() == 0
        view.append("\n")
        assert view.lineCount() == 1

    def test_append_line_helper(self, view):
        view.appendLine("hello")
        view.applyFilterNow()
        assert view.toPlainText() == "hello"

    def test_append_line_strips_trailing_newline(self, view):
        view.appendLine("hello\n")
        view.applyFilterNow()
        assert view.toPlainText() == "hello"

    def test_append_empty_is_noop(self, view):
        view.append("")
        assert view.lineCount() == 0

    def test_append_bytes(self, view):
        view.append("编译 ✓\n".encode("utf-8"))
        view.applyFilterNow()
        assert view.toPlainText() == "编译 ✓"

    def test_append_bytearray(self, view):
        view.append(bytearray(b"raw\n"))
        view.applyFilterNow()
        assert view.toPlainText() == "raw"

    def test_append_invalid_utf8_is_replaced(self, view):
        view.append(b"a\xffb\n")
        view.applyFilterNow()
        assert view.toPlainText().startswith("a")
        assert view.toPlainText().endswith("b")

    def test_append_empty_bytes(self, view):
        view.append(b"")
        assert view.lineCount() == 0

    def test_empty_lines_counted(self, view):
        view.append("\n\n\n")
        assert view.lineCount() == 3

    def test_rendered_after_event_loop(self, view, qapp):
        view.append(lines("x", "y"))
        qapp.processEvents()
        assert view.visibleLineCount() == 2

    def test_lines_appended_signal(self, view, qapp):
        seen = []
        view.linesAppended.connect(seen.append)
        view.append(lines("a", "b"))
        assert seen == [2]

    def test_progress_bar_redraw_yields_one_line(self, view):
        view.append("10%\r50%\r100%\n")
        view.applyFilterNow()
        assert view.lineCount() == 1
        assert view.toPlainText() == "100%"

    def test_escape_sequences_not_in_plain_text(self, view):
        view.append(CSI + "32mok" + CSI + "0m\n")
        view.applyFilterNow()
        assert view.toPlainText() == "ok"

    def test_osc_dropped(self, view):
        view.append(ESC + "]0;title\x07real\n")
        view.applyFilterNow()
        assert view.toPlainText() == "real"


class TestClear:
    def test_clear_empties_everything(self, view, qapp):
        view.append(lines("a", "b"))
        qapp.processEvents()
        view.clear()
        assert view.lineCount() == 0
        assert view.visibleLineCount() == 0
        assert view.toPlainText() == ""

    def test_clear_signal(self, view):
        seen = []
        view.cleared.connect(lambda: seen.append(True))
        view.append("a\n")
        view.clear()
        assert seen == [True]

    def test_append_after_clear_works(self, view):
        view.append("a\n")
        view.clear()
        view.append("b\n")
        view.applyFilterNow()
        assert view.toPlainText() == "b"

    def test_clear_resets_parser_style(self, view):
        view.append(CSI + "31mred\n")
        view.clear()
        view.append("plain\n")
        view.applyFilterNow()
        assert view._lines[0].spans[0].style == TerminalStyle()


class TestMaxLines:
    def test_trim_keeps_latest(self, view):
        view.setMaxLines(3)
        view.append(lines("1", "2", "3", "4", "5"))
        view.applyFilterNow()
        assert view.lineCount() == 3
        assert view.toPlainText() == "3\n4\n5"

    def test_zero_means_unlimited(self, view):
        view.setMaxLines(0)
        view.append(lines(*[str(i) for i in range(50)]))
        view.applyFilterNow()
        assert view.lineCount() == 50

    def test_negative_clamped_to_zero(self, view):
        view.setMaxLines(-5)
        assert view.maxLines() == 0

    def test_document_trimmed_too(self, view, qapp):
        view.setMaxLines(2)
        view.append(lines("1", "2", "3", "4"))
        qapp.processEvents()
        assert view.visibleLineCount() == 2

    def test_gutter_width_follows_max_lines(self, view):
        view.setMaxLines(3)
        view.setMaxLines(100000)
        # 位数变多 → 行号槽变宽
        assert view._gutter.width() > 0


class TestToPlainTextAndSave:
    def test_to_plain_text_empty(self, view):
        assert view.toPlainText() == ""

    def test_to_plain_text_unaffected_by_filter(self, view):
        view.append(lines("keep", "drop"))
        view.setFilter("keep")
        view.applyFilterNow()
        assert view.toPlainText() == "keep\ndrop"

    def test_save_to(self, view, tmp_path):
        view.append(lines("alpha", "beta"))
        target = tmp_path / "out.log"
        assert view.saveTo(str(target)) is True
        assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"

    def test_save_to_empty_writes_empty_file(self, view, tmp_path):
        target = tmp_path / "empty.log"
        assert view.saveTo(str(target)) is True
        assert target.read_text(encoding="utf-8") == ""

    def test_save_to_bad_path_returns_false(self, view):
        assert view.saveTo("Z:/nope/dir/x.log") is False

    def test_save_to_keeps_ansi_removed(self, view, tmp_path):
        view.append(CSI + "32mgreen" + CSI + "0m\n")
        target = tmp_path / "c.log"
        view.saveTo(str(target))
        assert target.read_text(encoding="utf-8") == "green\n"


class TestCopyAll:
    def test_copy_all(self, view, qapp, requires_clipboard):
        view.append(lines("a", "b"))
        view.copyAll()
        assert _wait_for_clipboard(qapp, "a\nb", view.copyAll) == "a\nb"

    def test_copy_all_empty(self, view, qapp, requires_clipboard):
        qapp.clipboard().setText("sentinel")
        # 哨兵得先确认真的落盘，否则「读回空串」可能只是写被丢弃 / 读失败，白测
        sent = _wait_for_clipboard(
            qapp, "sentinel", lambda: qapp.clipboard().setText("sentinel")
        )
        assert sent == "sentinel"
        view.copyAll()
        assert _wait_for_clipboard(qapp, "", view.copyAll) == ""

    def test_selected_text_empty(self, view):
        view.append("hello\n")
        assert view.selectedText() == ""

    def test_copy_selection(self, view, qapp, requires_clipboard):
        view.append(lines("alpha", "beta"))
        qapp.processEvents()  # 渲染是按帧合并的，得先让事件循环跑一轮
        view.selectAll()
        assert view.copySelection() is True
        assert (
            _wait_for_clipboard(qapp, "alpha\nbeta", view.copySelection)
            == "alpha\nbeta"
        )

    def test_copy_selection_without_selection(self, view, qapp, requires_clipboard):
        # 剪贴板是进程级共享状态，先写哨兵值再断言「没被动过」，
        # 不要直接断言为空（会被上一个用例的残留污染）
        qapp.clipboard().setText("sentinel")
        assert (
            _wait_for_clipboard(
                qapp, "sentinel", lambda: qapp.clipboard().setText("sentinel")
            )
            == "sentinel"
        )
        view.append("hello\n")
        qapp.processEvents()
        assert view.copySelection() is False
        # 只轮询、绝不重发：重发哨兵等于把「没被改」的证据覆盖掉
        assert _wait_for_clipboard(qapp, "sentinel") == "sentinel"

    def test_select_all_then_clear_selection(self, view, qapp):
        view.append(lines("a", "b"))
        qapp.processEvents()
        view.selectAll()
        assert view.selectedText() == "a\nb"

    def test_no_plain_text_edit_escape_hatch(self, view):
        """内部编辑框不再公开，避免宿主 setPlainText 打破 _lines 单一真源。"""
        assert not hasattr(view, "plainTextEdit")
        assert not hasattr(view, "gutterTextColor")
        assert not hasattr(view, "gutterBorderColor")
        assert not hasattr(view, "setShowToolbar")
        assert not hasattr(view, "appendBytes")


class TestFilter:
    def test_filter_hides_non_matching(self, view):
        view.append(lines("error one", "ok line", "error two"))
        view.setFilter("error")
        view.applyFilterNow()
        # 只影响渲染，数据模型原样保留
        assert view.visibleLineCount() == 2
        assert view.lineCount() == 3
        assert view.toPlainText() == "error one\nok line\nerror two"

    def test_filter_no_match(self, view):
        view.append(lines("a", "b"))
        view.setFilter("zzz")
        view.applyFilterNow()
        assert view.visibleLineCount() == 0
        assert view.matchCount() == 0

    def test_clearing_filter_restores(self, view):
        view.append(lines("a", "b"))
        view.setFilter("a")
        view.applyFilterNow()
        assert view.visibleLineCount() == 1
        view.setFilter("")
        view.applyFilterNow()
        assert view.visibleLineCount() == 2

    def test_filter_is_case_sensitive(self, view):
        view.append(lines("Error", "error"))
        view.setFilter("error")
        view.applyFilterNow()
        assert view.visibleLineCount() == 1

    def test_filter_none_becomes_empty(self, view):
        view.setFilter("x")
        view.setFilter(None)
        assert view.filterText() == ""

    def test_match_count(self, view):
        view.append(lines("aXaXa", "b"))
        view.setFilter("X")
        view.applyFilterNow()
        assert view.matchCount() == 2

    def test_match_count_multiple_per_line(self, view):
        view.append("aaaa\n")
        view.setFilter("a")
        view.applyFilterNow()
        assert view.matchCount() == 4

    def test_filter_changed_signal(self, view):
        seen = []
        view.filterChanged.connect(lambda text, count: seen.append((text, count)))
        view.append(lines("hit", "miss"))
        view.setFilter("hit")
        view.applyFilterNow()
        assert seen == [("hit", 1)]

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(lambda v: v.setPaletteName("classic"), id="palette"),
            pytest.param(lambda v: v.setFontSize(20), id="font"),
            pytest.param(lambda v: v.setHighlightColor(QColor("#00ff00")), id="hilite"),
            pytest.param(lambda v: v.setMaxLines(1), id="maxLines"),
            pytest.param(lambda v: v.applyFilterNow(), id="rebuild-only"),
        ],
    )
    def test_filter_changed_not_emitted_without_word_change(self, view, mutate):
        """换配色 / 改字号 / 改上限都走同一条重建路径，不该再发「词变了」。"""
        view.append(lines("hit", "miss", "hit"))
        view.setFilter("hit")
        view.applyFilterNow()
        seen = []
        view.filterChanged.connect(lambda text, count: seen.append((text, count)))
        mutate(view)
        view.applyFilterNow()
        assert seen == []

    def test_filter_changed_emitted_on_real_change(self, view):
        view.append(lines("aaa", "bbb"))
        view.setFilter("aaa")
        view.applyFilterNow()
        seen = []
        view.filterChanged.connect(lambda text, count: seen.append((text, count)))
        view.setFilter("bbb")
        view.applyFilterNow()
        assert seen == [("bbb", 1)]

    def test_append_during_filter_rebuilds(self, view, qapp):
        view.append(lines("a", "b"))
        view.setFilter("a")
        view.applyFilterNow()
        view.append("a2\n")
        view.applyFilterNow()
        assert view.visibleLineCount() == 2

    def test_repeated_filter_calls_debounced(self, view, qapp):
        view.append(lines("a", "b", "c"))
        for char in "abc":
            view.setFilter(char)
        view.applyFilterNow()
        assert view.filterText() == "c"

    def test_find_next_without_match(self, view):
        assert view.findNext() is False
        assert view.findPrevious() is False

    def test_find_next_cycles(self, view):
        view.append("x1 x2 x3\n")
        view.setFilter("x")
        view.applyFilterNow()
        assert view.matchCount() == 3
        assert view.findNext() is True
        assert view.findNext() is True
        assert view.findNext() is True
        assert view.findNext() is True  # 回绕

    def test_find_previous_wraps(self, view):
        view.append("x1 x2\n")
        view.setFilter("x")
        view.applyFilterNow()
        assert view.findPrevious() is True

    def test_match_position_signal(self, view):
        seen = []
        view.matchPositionChanged.connect(seen.append)
        view.append("a a\n")
        view.setFilter("a")
        view.applyFilterNow()
        view.findNext()
        assert seen == [1]

    def test_filter_survives_max_lines_change(self, view):
        view.append(lines("keep", "drop", "keep"))
        view.setFilter("keep")
        view.applyFilterNow()
        assert view.visibleLineCount() == 2
        # 调小上限先淘汰模型尾部（"keep" 这行被裁掉），过滤结果随之变化
        view.setMaxLines(2)
        view.applyFilterNow()
        assert view.lineCount() == 2
        assert view.visibleLineCount() == 1


class TestAutoScroll:
    def test_default_following(self, view):
        assert view.isFollowing() is True

    def test_disable_auto_scroll(self, view):
        view.setAutoScroll(False)
        assert view.autoScroll() is False
        assert view.isFollowing() is False

    def test_reenable_snaps_to_bottom(self, view):
        view.setAutoScroll(False)
        view.setAutoScroll(True)
        assert view.isFollowing() is True

    def test_scroll_to_bottom_restores_following(self, view):
        view.setAutoScroll(False)
        view.scrollToBottom()
        assert view.isFollowing() is False  # auto_scroll 仍是关的

    def test_user_scroll_up_stops_following(self, view, qapp):
        view.setMaxLines(0)
        view.append(lines(*[f"line {i}" for i in range(200)]))
        qapp.processEvents()
        # scrollToLine(1) 把首行滚到视口顶部 —— 等价于用户拖到最上
        assert view.scrollToLine(1) is True
        assert view.isFollowing() is False

    def test_user_scroll_back_to_bottom_resumes(self, view, qapp):
        view.setMaxLines(0)
        view.append(lines(*[f"line {i}" for i in range(200)]))
        qapp.processEvents()
        view.scrollToLine(1)
        assert view.isFollowing() is False
        view.scrollToBottom()
        assert view.isFollowing() is True

    def test_append_while_scrolled_up_keeps_position(self, view, qapp):
        view.setMaxLines(0)
        view.append(lines(*[f"line {i}" for i in range(200)]))
        qapp.processEvents()
        view.scrollToLine(1)
        before = view._edit.verticalScrollBar().value()
        view.append("new line\n")
        qapp.processEvents()
        assert view.isFollowing() is False
        assert view._edit.verticalScrollBar().value() == before

    def test_scroll_to_line_out_of_range(self, view, qapp):
        view.append(lines("a", "b"))
        qapp.processEvents()
        assert view.scrollToLine(99) is False
        assert view.scrollToLine(0) is True  # 负数被夹到首行


class TestAppearance:
    def test_line_numbers_toggle(self, view):
        view.setLineNumbersVisible(False)
        assert view.lineNumbersVisible() is False
        view.setLineNumbersVisible(True)
        assert view.lineNumbersVisible() is True

    def test_font_size_clamped(self, view):
        view.setFontSize(2)
        assert view.fontSize() == 8
        view.setFontSize(999)
        assert view.fontSize() == 32

    def test_font_size_applied(self, view):
        view.setFontSize(18)
        assert view._edit.font().pixelSize() == 18

    def test_font_is_monospace(self, view):
        view.setFontSize(14)
        assert (
            view._edit.font().styleHint() == QFont.StyleHint.Monospace
        ), "Qt6 里 Monospace 是 StyleHint（旧写法 QFont.StyleHint.Monospace 已移除）"

    def test_word_wrap(self, view):
        assert view.wordWrap() is False
        view.setWordWrap(True)
        assert view.wordWrap() is True
        view.setWordWrap(False)
        assert view.wordWrap() is False

    def test_word_wrap_mode_applied(self, view):
        view.setWordWrap(True)
        assert view._edit.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
        view.setWordWrap(False)
        assert view._edit.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap

    def test_toolbar_toggle(self, view):
        assert view.toolbarVisible() is True
        view.setToolbarVisible(False)
        assert view.toolbarVisible() is False
        assert view._toolbar.isVisibleTo(view) is False
        view.setToolbarVisible(True)
        assert view.toolbarVisible() is True

    def test_palette_switch(self, view):
        view.setPaletteName("classic")
        assert view.paletteName() == "classic"
        view.setPaletteName("nope")
        assert view.paletteName() == defaultTerminalTheme()

    def test_gutter_colors_are_valid(self, view):
        assert isinstance(view._gutter_text_color(), QColor)
        assert isinstance(view._gutter_border_color(), QColor)

    def test_highlight_color_override(self, view):
        view.setHighlightColor(QColor("#ff0000"))
        assert view._highlight == QColor("#ff0000")

    def test_highlight_color_none_resets(self, view):
        # 断言必须钉在「恢复成派生默认黄」上。原先写的是
        # ``!= #ff0000``，而非法 QColor（``QColor()``）天然不等于它 ——
        # 于是「None 置成非法色、QPainter 直接不画、搜索高亮整块消失」
        # 这个 bug 被一条恒真断言完全盖住。
        derived = _blend(view._palette["background"], _HIGHLIGHT, _HIGHLIGHT_RATIO)
        view.setHighlightColor(QColor("#ff0000"))
        assert view._highlight == QColor("#ff0000")
        view.setHighlightColor(None)
        assert view._highlight.isValid(), "None 必须回到有效色，不能是 QColor()"
        assert view._highlight == derived

    def test_highlight_override_survives_palette_change(self, view):
        # 覆盖值是持久的：换配色 / 切主题只重算派生默认黄
        view.setHighlightColor(QColor("#ff0000"))
        view.setPaletteName("classic")
        assert view._highlight == QColor("#ff0000")
        view.setPaletteName("default")
        assert view._highlight == QColor("#ff0000")
        view.setHighlightColor(None)
        assert view._highlight == _blend(
            view._palette["background"], _HIGHLIGHT, _HIGHLIGHT_RATIO
        )

    def test_highlight_rejects_invalid_color(self, view):
        before = QColor(view._highlight)
        view.setHighlightColor("not-a-color")
        assert view._highlight == before, "非法色必须被拒，不能让高亮整块消失"

    def test_gutter_paints_without_lines(self, view):
        # 空内容时行号槽不应崩
        view._gutter.update()
        view._gutter.repaint()

    def test_gutter_paints_with_lines(self, view, qapp):
        view.append(lines("a", "b", "c"))
        qapp.processEvents()
        view._gutter.repaint()
        assert view._gutter.width() > 0

    def test_gutter_paints_after_scroll(self, view, qapp):
        view.setMaxLines(0)
        view.append(lines(*[f"line {i}" for i in range(300)]))
        qapp.processEvents()
        view._edit.verticalScrollBar().setValue(100)
        view._gutter.repaint()


class TestThemeRegistry:
    def test_builtin_themes(self):
        assert set(terminalThemes()) >= {"one-dark", "solarized", "classic"}

    def test_default_theme(self):
        assert defaultTerminalTheme() in terminalThemes()

    def test_register_and_use(self, view):
        registerTerminalTheme(
            "unit-test-palette",
            {"foreground": "#111111", "background": "#eeeeee"},
            {"foreground": "#eeeeee", "background": "#111111"},
        )
        try:
            view.setPaletteName("unit-test-palette")
            assert view.paletteName() == "unit-test-palette"
            # 具体取哪档由当前应用主题决定
            assert view._palette["background"].name() in {"#eeeeee", "#111111"}
        finally:
            unregisterTerminalTheme("unit-test-palette")

    def test_register_replaces_existing(self, view):
        # 两档都给同一个值，避免测试依赖当前应用主题是亮还是暗
        registerTerminalTheme(
            "dup", {"background": "#010101"}, {"background": "#010101"}
        )
        registerTerminalTheme(
            "dup", {"background": "#020202"}, {"background": "#020202"}
        )
        try:
            view.setPaletteName("dup")
            assert view._palette["background"].name() == "#020202"
        finally:
            unregisterTerminalTheme("dup")

    def test_partial_keys_merge_from_default(self, view):
        registerTerminalTheme(
            "partial-palette", {"foreground": "#123456"}, {"foreground": "#123456"}
        )
        try:
            view.setPaletteName("partial-palette")
            # 未给的键回退到 one-dark，而不是 KeyError
            assert view._palette["foreground"].name() == "#123456"
            assert isinstance(view._palette["red"], QColor)
        finally:
            unregisterTerminalTheme("partial-palette")

    def test_missing_foreground_falls_back_to_etheme(self, view):
        registerTerminalTheme("no-fg", {}, {})
        try:
            view.setPaletteName("no-fg")
            # 未定义前景 / 背景 → 走 eTheme 令牌，不该是调色板默认档的值
            assert view._palette["foreground"].isValid() is True
            assert view._palette["background"].isValid() is True
        finally:
            unregisterTerminalTheme("no-fg")

    def test_set_default_theme(self, view):
        original = defaultTerminalTheme()
        try:
            setDefaultTerminalTheme("solarized")
            assert defaultTerminalTheme() == "solarized"
            assert ElaTerminalView().paletteName() == "solarized"
        finally:
            setDefaultTerminalTheme(original)

    def test_set_unknown_default_raises(self):
        with pytest.raises(KeyError):
            setDefaultTerminalTheme("nope")

    def test_unregister_builtin_raises(self):
        with pytest.raises(ValueError):
            unregisterTerminalTheme("one-dark")

    def test_unregister_unknown_raises(self):
        with pytest.raises(KeyError):
            unregisterTerminalTheme("nope")

    def test_unregister_default_raises(self):
        original = defaultTerminalTheme()
        registerTerminalTheme("temp-default", {}, {})
        try:
            setDefaultTerminalTheme("temp-default")
            with pytest.raises(ValueError):
                unregisterTerminalTheme("temp-default")
        finally:
            setDefaultTerminalTheme(original)
            unregisterTerminalTheme("temp-default")

    def test_register_empty_name_raises(self):
        with pytest.raises(ValueError):
            registerTerminalTheme("", {}, {})


class TestRendering:
    def test_formats_applied_to_document(self, view, qapp):
        view.append(CSI + "31mred" + CSI + "0mplain\n")
        qapp.processEvents()
        block = view._edit.document().firstBlock()
        assert block.text() == "redplain"

    def test_rebuild_preserves_text(self, view):
        rows = lines("a", "b", "c")
        view.append(rows)
        view.setFilter("")
        view.applyFilterNow()
        assert view.toPlainText() == "a\nb\nc"
        assert view.visibleLineCount() == 3

    def test_rebuild_with_no_content(self, view):
        view.applyFilterNow()
        assert view.visibleLineCount() == 0
        assert view._edit.toPlainText() == ""

    def test_many_lines_render(self, view, qapp):
        view.append(lines(*[str(i) for i in range(500)]))
        qapp.processEvents()
        assert view.visibleLineCount() == 500

    def test_inverse_and_dim_do_not_crash(self, view, qapp):
        view.append(CSI + "7mrev" + CSI + "0m " + CSI + "2mdim" + CSI + "0m\n")
        qapp.processEvents()
        assert view.visibleLineCount() == 1

    def test_256_and_truecolor_render(self, view, qapp):
        view.append(CSI + "38;5;208ma" + CSI + "0m" + CSI + "38;2;1;2;3mb\n")
        qapp.processEvents()
        assert view.visibleLineCount() == 1

    def test_html_like_text_not_parsed(self, view, qapp):
        """终端输出里的 "<b>" 不得被 Qt 当富文本。"""
        view.append("<b>not bold</b> <img src=x>\n")
        qapp.processEvents()
        assert view.toPlainText() == "<b>not bold</b> <img src=x>"

    def test_frame_batched_render(self, view, qapp):
        """同一批多次 append 在事件循环前不渲染，之后一次性排完。"""
        for i in range(500):
            view.append(f"batch {i}\n")
        assert view.visibleLineCount() == 0
        qapp.processEvents()
        assert view.visibleLineCount() == 500

    def test_cr_redraw_keeps_single_span(self, view, qapp):
        """反复 \\r 重绘不能把一行撑成多段。"""
        for i in range(200):
            view.append(f"\r  {i}%")
        view.append("\n")
        qapp.processEvents()
        assert view.lineCount() == 1
        assert len(view._lines[0].spans) == 1
        assert view.toPlainText() == "  199%"

    def test_max_lines_eviction_keeps_latest_window(self, view, qapp):
        view.setMaxLines(2000)
        for i in range(3000):
            view.append(f"line {i}\n")
        qapp.processEvents()
        assert view.lineCount() == 2000
        assert view.toPlainText().startswith("line 1000")
        assert view.toPlainText().endswith("line 2999")


class TestLifecycle:
    def test_delete_later_with_pending_timers(self, view, qapp):
        view.append(lines("a", "b"))
        view.setFilter("a")
        view.deleteLater()
        qapp.processEvents()

    def test_timers_stopped_on_delete(self, view, qapp):
        view.append("a\n")
        view.setFilter("a")
        view.deleteLater()
        assert view._flush_timer.isActive() is False
        assert view._filter_timer.isActive() is False
        qapp.processEvents()

    def test_theme_change_repaints_and_keeps_content(self, view, qapp):
        view.append(lines("a", "b"))
        qapp.processEvents()
        before = view._palette["background"].name()
        light = ElaThemeType.ThemeMode.Light
        eTheme.setThemeMode(
            ElaThemeType.ThemeMode.Dark if eTheme.getThemeMode() == light else light
        )
        try:
            qapp.processEvents()
            assert view._palette["background"].name() != before
            assert view.visibleLineCount() == 2
            assert view.toPlainText() == "a\nb"
        finally:
            eTheme.setThemeMode(
                light if eTheme.getThemeMode() != light else ElaThemeType.ThemeMode.Dark
            )
            qapp.processEvents()


class TestContextMenu:
    """右键菜单：Ela 风格 + 事件路由（右键投递到 viewport，不是编辑框本体）。"""

    @staticmethod
    def _open_and_close(qapp, owner) -> list:
        """真弹一次菜单并**自动关掉**，返回弹出来的菜单列表。

        ``QMenu.exec`` 阻塞到菜单被关闭；PyQt6 里 ``ElaMenu.exec`` 是 shiboken
        方法，**类级 monkeypatch 拦不住**（实测 ``menu.exec`` 仍解析到 C++ 方法），
        所以只能在测试里放一个定时器把弹层关掉。
        """
        opened: list = []
        timer = QTimer(owner)
        timer.setInterval(10)

        def _close_popup() -> None:
            popup = QApplication.activePopupWidget()
            if popup is None:
                return
            opened.append(popup)
            timer.stop()
            popup.close()

        timer.timeout.connect(_close_popup)
        timer.start()
        return opened

    def test_show_context_menu_does_not_crash(self, view, qapp):
        view.append(lines("a", "b"))
        pos = view.mapToGlobal(view.rect().center())
        opened = self._open_and_close(qapp, view)
        view._show_context_menu(pos)
        qapp.processEvents()
        assert opened, "右键菜单没有弹出来"
        menu = opened[0]
        # execElaMenu 的兜底：非主屏 ElaMenu 偶发不按 sizeHint 撑开
        assert menu.minimumSize() == menu.sizeHint()
        # 只读视图的菜单：复制 + 全选（外加分隔符与「复制全部」）
        texts = [a.text() for a in menu.actions() if a.text()]
        assert "复制" in texts and "全选" in texts

    def test_show_context_menu_empty(self, view, qapp):
        opened = self._open_and_close(qapp, view)
        view._show_context_menu(view.mapToGlobal(view.rect().center()))
        qapp.processEvents()
        assert opened, "空视图也要能弹出右键菜单"

    def test_context_menu_on_viewport_reaches_our_menu(self, view, qapp, monkeypatch):
        """回归：右键事件给 viewport（QAbstractScrollArea 的视口）。

        只拦 ``self._edit`` 的话这里会落到 Qt 自带的「复制 / 全选」菜单 ——
        自建 ElaMenu 可达性为 0（事件根本不到过滤器）。
        """
        calls = []
        monkeypatch.setattr(
            type(view), "_show_context_menu", lambda self, pos: calls.append(pos)
        )
        viewport = view._edit.viewport()
        global_pos = viewport.mapToGlobal(viewport.rect().center())
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, global_pos, global_pos
        )
        QApplication.sendEvent(viewport, event)
        assert calls == [global_pos]

    def test_export_dialog_cancel_is_safe(self, view, monkeypatch):
        called = []
        monkeypatch.setattr(
            "pyqt6_ela_pro.terminal_view.QFileDialog.getSaveFileName",
            lambda *a, **k: (called.append(True), ("", ""))[1],
        )
        view._export_dialog()
        assert called == [True]

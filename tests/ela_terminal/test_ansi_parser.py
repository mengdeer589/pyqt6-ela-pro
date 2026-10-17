"""``AnsiParser`` 单测（纯字符串处理，不需要 QApplication）。"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.terminal_view import (
    AnsiColor,
    AnsiParser,
    TerminalLine,
    TerminalStyle,
)

ESC = "\x1b"
CSI = ESC + "["


def feed_all(parser: AnsiParser, *chunks: str) -> list:
    """喂入若干分片并收尾，返回全部行。"""
    out: list = []
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    out.extend(parser.flush())
    return out


def texts(lines: list) -> list:
    return [line.text for line in lines]


class TestPlainText:
    def test_single_line(self):
        parser = AnsiParser()
        assert texts(parser.feed("hello\n")) == ["hello"]

    def test_multiple_lines_in_one_chunk(self):
        parser = AnsiParser()
        assert texts(parser.feed("a\nb\nc\n")) == ["a", "b", "c"]

    def test_no_trailing_newline_waits_for_flush(self):
        parser = AnsiParser()
        assert parser.feed("tail") == []
        assert texts(parser.flush()) == ["tail"]

    def test_flush_on_empty_parser(self):
        assert AnsiParser().flush() == []

    def test_blank_lines_preserved(self):
        parser = AnsiParser()
        assert texts(parser.feed("a\n\nb\n")) == ["a", "", "b"]

    def test_empty_chunk_is_noop(self):
        parser = AnsiParser()
        assert parser.feed("") == []

    def test_utf8_preserved(self):
        parser = AnsiParser()
        assert texts(parser.feed("编译完成 ✓\n")) == ["编译完成 ✓"]

    def test_line_exposes_cached_text(self):
        line = TerminalLine([])
        assert line.text == ""
        assert repr(line) == "TerminalLine('')"


class TestCarriageReturn:
    def test_cr_redraws_whole_line(self):
        """进度条：整行重绘后只保留最后一份内容。"""
        parser = AnsiParser()
        lines = parser.feed(" 10%\r 20%\r 50%\n")
        assert texts(lines) == [" 50%"]

    def test_cr_with_ansi(self):
        parser = AnsiParser()
        lines = parser.feed(
            CSI + "32m10%" + CSI + "0m\r" + CSI + "32m99%" + CSI + "0m\n"
        )
        assert texts(lines) == ["99%"]
        assert lines[0].spans[0].style.fg == AnsiColor("basic", 2)

    def test_crlf_keeps_content(self):
        """CRLF 是一次正常换行，不能把内容清掉。"""
        parser = AnsiParser()
        assert texts(parser.feed("line\r\nnext\r\n")) == ["line", "next"]

    def test_cr_at_end_of_stream_flushes(self):
        parser = AnsiParser()
        parser.feed("progress 50%\r")
        assert texts(parser.flush()) == ["progress 50%"]

    def test_cr_then_nothing_written_does_not_erase(self):
        """只有 \\r 没有后续写入时，内容保留到 flush。"""
        parser = AnsiParser()
        parser.feed("abc\r")
        assert texts(parser.flush()) == ["abc"]


class TestTabAndBackspace:
    def test_tab_expands_to_eight_columns(self):
        parser = AnsiParser()
        assert texts(parser.feed("a\tb\n")) == ["a" + " " * 7 + "b"]

    def test_tab_at_column_zero(self):
        parser = AnsiParser()
        assert texts(parser.feed("\tx\n")) == [" " * 8 + "x"]

    def test_backspace_overwrites_in_place(self):
        """\\b 把笔左移后写入是逐格覆盖，后面的内容不受影响。"""
        parser = AnsiParser()
        assert texts(parser.feed("abc\b\bX\n")) == ["aXc"]


class TestSgrColors:
    def test_basic_foreground(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "31mred" + CSI + "0m" + "plain\n")[0]
        assert line.spans[0].style.fg == AnsiColor("basic", 1)
        assert line.spans[1].style.fg is None

    def test_bright_foreground(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "91mbright\n")[0]
        assert line.spans[0].style.fg == AnsiColor("basic", 9)

    def test_background_colors(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "41ma" + CSI + "104mb\n")[0]
        assert line.spans[0].style.bg == AnsiColor("basic", 1)
        assert line.spans[1].style.bg == AnsiColor("basic", 12)

    def test_default_foreground_resets_only_fg(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "31;42" + "m" + "x" + CSI + "39" + "my\n")[0]
        assert line.spans[0].style.fg == AnsiColor("basic", 1)
        assert line.spans[1].style.fg is None
        assert line.spans[1].style.bg == AnsiColor("basic", 2)

    def test_attributes(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "1;3;4;7;9mall\n")[0]
        style = line.spans[0].style
        assert style.bold and style.italic
        assert style.underline and style.inverse and style.strike

    def test_attribute_turn_off(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "1m" + "a" + CSI + "22m" + "b\n")[0]
        assert line.spans[0].style.bold is True
        assert line.spans[1].style.bold is False

    def test_dim_turned_off_by_22(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "2ma" + CSI + "22mb\n")[0]
        assert line.spans[0].style.dim is True
        assert line.spans[1].style.dim is False

    def test_underline_off_by_24(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "4ma" + CSI + "24mb\n")[0]
        assert line.spans[0].style.underline is True
        assert line.spans[1].style.underline is False

    def test_reset_clears_everything(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "1;31;44m" + "a" + CSI + "0m" + "b\n")[0]
        assert line.spans[1].style == TerminalStyle()

    def test_256_color(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "38;5;208mx\n")[0]
        assert line.spans[0].style.fg == AnsiColor("indexed", 208)

    def test_256_background(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "48;5;17mx\n")[0]
        assert line.spans[0].style.bg == AnsiColor("indexed", 17)

    def test_truecolor(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "38;2;18;52;86mx\n")[0]
        assert line.spans[0].style.fg == AnsiColor("rgb", 0x123456)

    def test_truecolor_background(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "48;2;255;0;0mx\n")[0]
        assert line.spans[0].style.bg == AnsiColor("rgb", 0xFF0000)

    def test_truecolor_clamps_out_of_range(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "38;2;300;0;0mx\n")[0]
        assert line.spans[0].style.fg == AnsiColor("rgb", 0xFF0000)

    def test_extended_color_followed_by_another(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "38;5;1mx" + CSI + "1my\n")[0]
        assert line.spans[0].style.fg == AnsiColor("indexed", 1)
        assert line.spans[1].style.bold is True
        assert line.spans[1].style.fg == AnsiColor("indexed", 1)

    def test_malformed_extended_color_does_not_crash(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "38mx\n")[0]
        assert line.spans[0].text == "x"
        assert line.spans[0].style.fg is None

    def test_empty_sgr_is_reset(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "31m" + CSI + "m" + "x\n")[0]
        assert line.spans[0].style == TerminalStyle()

    def test_double_semicolon_is_zero(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "31;;1mx\n")[0]
        assert line.spans[0].style.bold is True
        assert line.spans[0].style.fg is None

    def test_style_persists_across_chunks(self):
        parser = AnsiParser()
        assert parser.feed(CSI + "32mgre")[0:0] == []
        lines = parser.feed("en\n")
        assert lines[0].spans[0].style.fg == AnsiColor("basic", 2)

    def test_current_style(self):
        parser = AnsiParser()
        parser.feed(CSI + "31m")
        assert parser.currentStyle().fg == AnsiColor("basic", 1)


class TestErase:
    def test_erase_to_end_of_line(self):
        """K 0 清掉光标到行尾，之后写入不残留旧内容。"""
        parser = AnsiParser()
        line = parser.feed("abcdef" + CSI + "3G" + CSI + "K" + "xy\n")[0]
        assert line.text == "abxy"

    def test_erase_whole_line(self):
        parser = AnsiParser()
        line = parser.feed("garbage" + CSI + "2K" + "ok\n")[0]
        assert line.text == "ok"

    def test_erase_to_start_of_line(self):
        parser = AnsiParser()
        line = parser.feed("abcdef" + CSI + "3G" + CSI + "1K" + "X\n")[0]
        assert line.text == "  Xdef"

    def test_erase_display_clears_all(self):
        parser = AnsiParser()
        parser.feed("old content\n")
        assert parser.takeClear() is False
        parser.feed(CSI + "2J")
        assert parser.takeClear() is True
        # 标记只取一次
        assert parser.takeClear() is False

    def test_erase_display_zero_is_noop(self):
        """滚动缓冲下「清到末尾」后面本来就没有内容。"""
        parser = AnsiParser()
        parser.feed("text\n" + CSI + "0J")
        assert parser.takeClear() is False

    def test_erase_display_three_clears(self):
        parser = AnsiParser()
        parser.feed(CSI + "3J")
        assert parser.takeClear() is True


class TestCursorMoves:
    def test_cursor_forward(self):
        """右移 3 列后写入，中间补空格。"""
        parser = AnsiParser()
        line = parser.feed("ab" + CSI + "3C" + "X\n")[0]
        assert line.text == "ab   X"

    def test_cursor_back(self):
        """左移后写入是逐格覆盖：笔落在第 4 列，写 2 格只改写 ef。"""
        parser = AnsiParser()
        line = parser.feed("abcdef" + CSI + "2D" + "XY\n")[0]
        assert line.text == "abcdXY"

    def test_cursor_back_partial_overwrite_keeps_tail(self):
        parser = AnsiParser()
        line = parser.feed("abcdef" + CSI + "2D" + "X\n")[0]
        assert line.text == "abcdXf"

    def test_cursor_absolute_column(self):
        parser = AnsiParser()
        line = parser.feed("abcde" + CSI + "2G" + "X\n")[0]
        assert line.text == "aXcde"

    def test_cursor_back_clamps_at_zero(self):
        parser = AnsiParser()
        line = parser.feed("a" + CSI + "9D" + "X\n")[0]
        assert line.text == "X"

    def test_cursor_forward_defaults_to_one(self):
        parser = AnsiParser()
        line = parser.feed("a" + CSI + "C" + "X\n")[0]
        assert line.text == "a X"

    def test_hpa_backtick_column(self):
        parser = AnsiParser()
        line = parser.feed("abcde" + CSI + "3`" + "X\n")[0]
        assert line.text == "abXde"


class TestSplitSafety:
    def test_escape_sequence_split_across_chunks(self):
        """进程输出按 read() 分片，转义序列必被切开。"""
        parser = AnsiParser()
        assert parser.feed(CSI + "3") == []
        assert parser.feed("1mred") == []
        lines = parser.feed("\n")
        assert lines[0].spans[0].style.fg == AnsiColor("basic", 1)
        assert lines[0].text == "red"

    def test_split_right_after_esc(self):
        parser = AnsiParser()
        assert parser.feed(ESC) == []
        lines = parser.feed(CSI + "0mx\n")
        assert texts(lines) == ["x"]

    def test_osc_split_across_chunks(self):
        parser = AnsiParser()
        assert parser.feed(ESC + "]0;ti") == []
        lines = parser.feed("tle\x07after\n")
        assert texts(lines) == ["after"]

    def test_dcs_split_across_chunks(self):
        parser = AnsiParser()
        assert parser.feed(ESC + "P1$tx") == []
        lines = parser.feed(ESC + "\\done\n")
        assert texts(lines) == ["done"]

    def test_charset_select_split(self):
        parser = AnsiParser()
        assert parser.feed(ESC + "(") == []
        assert texts(parser.feed("Bok\n")) == ["ok"]

    def test_overlong_pending_is_dropped(self):
        """脏数据：残缺序列超长时整段当普通文本吐掉，不吞掉后续内容。"""
        parser = AnsiParser()
        first = parser.feed(CSI + "1" * 200)
        assert first == []  # 还没换行
        assert texts(parser.feed("tail\n")) == ["[" + "1" * 200 + "tail"]

    def test_trailing_complete_sequence_is_applied_immediately(self):
        """chunk 末尾的完整序列不能被当成残缺序列压到下一片。"""
        parser = AnsiParser()
        parser.feed("x" + CSI + "0m")
        assert parser.currentStyle() == TerminalStyle()


class TestDiscardedSequences:
    def test_bel_dropped(self):
        parser = AnsiParser()
        assert texts(parser.feed("a\x07b\n")) == ["ab"]

    def test_osc_dropped(self):
        parser = AnsiParser()
        assert texts(parser.feed(ESC + "]0;window title\x07real\n")) == ["real"]

    def test_osc_with_st_terminator(self):
        parser = AnsiParser()
        assert texts(parser.feed(ESC + "]8;;http://x" + ESC + "\\link\n")) == ["link"]

    def test_charset_select_dropped(self):
        parser = AnsiParser()
        assert texts(parser.feed(ESC + "(Btext\n")) == ["text"]

    def test_unknown_csi_dropped(self):
        parser = AnsiParser()
        assert texts(parser.feed("a" + CSI + "6n" + "b\n")) == ["ab"]

    def test_lone_esc_dropped(self):
        parser = AnsiParser()
        assert texts(feed_all(parser, ESC, "x\n")) == ["x"]

    def test_private_csi_prefix_handled(self):
        parser = AnsiParser()
        assert texts(parser.feed(CSI + "?25lhidden" + CSI + "?25h\n")) == ["hidden"]

    def test_intermediates_ignored(self):
        parser = AnsiParser()
        assert texts(parser.feed(CSI + "1 K" + "x\n")) == ["x"]


class TestSpans:
    def test_adjacent_same_style_merges_into_one_span(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "31maaa\n")[0]
        assert len(line.spans) == 1
        assert line.spans[0].text == "aaa"

    def test_style_change_splits_span(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "31mred" + CSI + "0mplain\n")[0]
        assert len(line.spans) == 2
        assert [s.text for s in line.spans] == ["red", "plain"]

    def test_crlf_does_not_double_span(self):
        parser = AnsiParser()
        line = parser.feed(CSI + "31mred\r\n")[0]
        assert len(line.spans) == 1

    def test_redraw_does_not_grow_spans(self):
        """反复进度条重绘不能把一行撑成上百个 span。"""
        parser = AnsiParser()
        for i in range(50):
            parser.feed(f"  {i}%\r")
        line = parser.flush()[0]
        assert len(line.spans) == 1
        assert line.text == "  49%"

    def test_line_text_is_cached(self):
        line = TerminalLine([type("S", (), {"text": "ab"})()])
        assert line.text == "ab"
        assert line.text is line.text


class TestReset:
    def test_reset_clears_pending_and_style(self):
        parser = AnsiParser()
        parser.feed(CSI + "31mhalf")
        parser.reset()
        assert parser.currentStyle() == TerminalStyle()
        assert parser.feed("clean\n")[0].spans[0].style == TerminalStyle()

    def test_reset_clears_clear_flag(self):
        parser = AnsiParser()
        parser.feed(CSI + "2J")
        parser.reset()
        assert parser.takeClear() is False

    def test_parser_is_reusable_after_flush(self):
        parser = AnsiParser()
        assert texts(parser.feed("one\n")) == ["one"]
        assert texts(parser.feed("two\n")) == ["two"]


@pytest.mark.parametrize(
    "chunk",
    [
        ESC,
        CSI,
        CSI + "3",
        CSI + "38;2;",
        CSI + "38;5;",
        ESC + "]",
        ESC + "P",
        "\x1b[?",
        "\x1b]0;unterminated",
    ],
)
def test_no_crash_on_truncated_sequences(chunk: str):
    """残缺序列不能让解析器崩（Qt 回调里异常 = 进程 abort）。"""
    parser = AnsiParser()
    for _ in range(3):
        parser.feed(chunk)
    assert isinstance(parser.flush(), list)

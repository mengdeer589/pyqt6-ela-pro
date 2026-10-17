from __future__ import annotations

import pytest

from pyqt6_ela_pro.terminal_view import AnsiParser

ESC = "\x1b"


def run(*chunks: str) -> list[str]:
    parser = AnsiParser()
    out: list = []
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    out.extend(parser.flush())
    return [line.text for line in out]


class TestCursorMoveAfterCarriageReturn:
    """核心：\\r + 挪光标 + 写 = 逐格覆盖，不是抹掉整行。"""

    def test_forward_c_overwrites_in_place(self):
        assert run("PROGRESS 50%", "\r", ESC + "[2C", "DONE") == ["PRDONESS 50%"]

    def test_forward_c_by_four(self):
        assert run("abcdefgh", "\r", ESC + "[4C", "XY") == ["abcdXYgh"]

    def test_two_forward_c(self):
        assert run("abcdefgh", "\r", ESC + "[1C", ESC + "[1C", "X") == ["abXdefgh"]

    def test_absolute_column(self):
        # CSI 10G = 第 10 列（1-based）-> 索引 9
        assert run("PROGRESS 50%", "\r", ESC + "[10G", "DONE") == ["PROGRESS DONE"]

    def test_backward_c_at_column_zero_is_noop(self):
        # \r 已把光标归零，再退 3 步退不动
        assert run("abcdefgh", "\r", ESC + "[3D", "ZZ") == ["ZZcdefgh"]

    def test_backspace_after_cr(self):
        assert run("abc", "\r", "\b", "Z") == ["Zbc"]

    def test_cursor_moves_without_cr(self):
        # 光标本就在行尾 6，CSI 4C -> 10，超出部分按「行尾不足则补空格」
        assert run("abcdef", ESC + "[4C", "X") == ["abcdef    X"]


class TestCarriageReturnRedrawUnchanged:
    """回归：这些路径不能被改坏。"""

    def test_cr_alone_is_full_redraw(self):
        assert run("PROGRESS 50%", "\r", "DONE") == ["DONE"]

    def test_sgr_does_not_clear_cr(self):
        # SGR 只改属性不动光标，清掉标记会让「\r + 颜色码 + 文本」失效
        assert run("PROGRESS 50%", "\r", ESC + "[31m", "DONE") == ["DONE"]

    def test_crlf_keeps_content(self):
        assert run("PROGRESS 50%\r\n", "next") == ["PROGRESS 50%", "next"]

    def test_erase_in_line_path(self):
        assert run("PROGRESS 50%", "\r", ESC + "[2K", ESC + "[10C", "DONE") == [
            "          DONE"
        ]

    def test_erase_in_display_path(self):
        assert run("PROGRESS 50%", "\r", ESC + "[2J", "DONE") == ["DONE"]

    def test_full_redraw_truncates(self):
        """整行重绘是「截断」而非「保留尾部」—— spinner 刻意不留残影。

        这是 :meth:`AnsiParser` 文档写明的契约（pip / git clone / docker pull
        的进度条都是整行重画），别把它当bug 修成「保留尾部」。
        """
        assert run("loading...", "\r", "done.") == ["done."]

    def test_progress_bar_rewrite_keeps_trailing(self):
        """逐格覆盖时未被覆盖的尾部必须留着（与整行重绘不同）。"""
        assert run("PROGRESS 50%", "\r", ESC + "[9C", "OK") == ["PROGRESS OK%"]


@pytest.mark.parametrize(
    ("chunks", "want"),
    [
        (("abc\n", "def\n"), ["abc", "def"]),
        (("",), []),
        (("no newline",), ["no newline"]),
        (("\r\n",), [""]),
    ],
)
def test_unrelated_shapes_unchanged(chunks, want):
    assert run(*chunks) == want

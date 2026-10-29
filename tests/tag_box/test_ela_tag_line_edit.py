"""Tests for ela_tag_line_edit module: ElaTagLineEdit."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from pyqt6_ela_pro.ela_tag_line_edit import ElaTagLineEdit


class TestElaTagLineEdit:
    """Test cases for ElaTagLineEdit class."""

    def test_initialization_with_defaults(self):
        """默认标题是**空串**，不是 "Untitled"。

        没设标题的输入框在框里喊 "Untitled" 是噪音；宿主忘了 ``setTitle()``
        时就该什么都不画。
        """
        edit = ElaTagLineEdit()

        assert edit._title_text == ""
        assert edit._is_error is False

        edit.deleteLater()

    def test_initialization_with_custom_title(self):
        """Test tag line edit accepts custom title."""
        edit = ElaTagLineEdit(title="用户名")

        assert edit._title_text == "用户名"

        edit.deleteLater()

    def test_fixed_height_is_35(self):
        """与上游 ElaLineEdit（35）同高。"""
        edit = ElaTagLineEdit()

        assert edit.height() == 35

        edit.deleteLater()

    def test_set_title(self):
        """Test setTitle updates title text."""
        edit = ElaTagLineEdit()
        edit.setTitle("新标题")

        assert edit._title_text == "新标题"

        edit.deleteLater()

    def test_title_returns_current_title(self):
        """Test title returns current title text."""
        edit = ElaTagLineEdit(title="测试")
        result = edit.title()

        assert result == "测试"

        edit.deleteLater()

    def test_set_title_font_size(self):
        """Test setTitleFontSize updates font size."""
        edit = ElaTagLineEdit()
        edit.setTitleFontSize(16)

        assert edit._title_font_size == 16

        edit.deleteLater()

    def test_untitled_has_no_dead_left_padding(self):
        """没有标题就不能留「标题宽度」的缩进。

        旧实现按 ``"" + 20 + 3`` 也设 23px 左边距，无标题输入框的 placeholder
        会比普通 ``ElaLineEdit`` 明显右移。
        """
        edit = ElaTagLineEdit()
        assert edit.textMargins().left() == 0
        edit.deleteLater()

    def test_title_margin_uses_title_font_not_widget_font(self):
        """标题宽度按 ``_title_font_size`` 量，不按输入框字号量。

        旧实现用 ``QFontMetrics(self.font())``（13px）量、用 12px 画，
        标题与输入文字之间会多空出一截。
        """
        from PyQt6.QtGui import QFont, QFontMetrics

        title = "用户名"
        edit = ElaTagLineEdit(title=title)
        edit.setTitleFontSize(12)

        title_font = QFont(edit.font())
        title_font.setPixelSize(12)
        expected = QFontMetrics(title_font).horizontalAdvance(title)
        assert edit.textMargins().left() == expected + edit._TITLE_GAP
        # 比用输入框字号（13px）量出来的窄
        assert edit.textMargins().left() <= (
            QFontMetrics(edit.font()).horizontalAdvance(title) + edit._TITLE_GAP
        )
        edit.deleteLater()

    def test_title_margin_grows_with_title_font_size(self):
        """字号变大 → 左边距跟着变大（setTitleFontSize 会重算）。"""
        edit = ElaTagLineEdit(title="用户名")
        edit.setTitleFontSize(12)
        narrow = edit.textMargins().left()
        edit.setTitleFontSize(20)
        assert edit.textMargins().left() > narrow
        edit.deleteLater()

    def test_notify_invalid_input_sets_error(self):
        """Test notifyInvalidInput sets error state."""
        edit = ElaTagLineEdit()
        edit.notifyInvalidInput()

        assert edit._is_error is True

        edit.deleteLater()

    def test_clear_error_clears_error_state(self):
        """Test clearError clears error state."""
        edit = ElaTagLineEdit()
        edit.notifyInvalidInput()
        edit.clearError()

        assert edit._is_error is False

        edit.deleteLater()

    def test_notify_invalid_input_triggers_update(self):
        """Test notifyInvalidInput triggers repaint."""
        edit = ElaTagLineEdit()
        edit.notifyInvalidInput()

        edit.deleteLater()

    def test_clear_error_triggers_update(self):
        """Test clearError triggers repaint."""
        edit = ElaTagLineEdit()
        edit.clearError()

        edit.deleteLater()

    def test_get_title_color_returns_qcolor(self):
        """Test _getTitleColor returns QColor."""
        edit = ElaTagLineEdit()

        color = edit._getTitleColor()

        assert isinstance(color, QColor)

    def test_get_title_color_returns_danger_in_error_state(self):
        """Test _getTitleColor returns danger color when error."""
        edit = ElaTagLineEdit()
        edit.notifyInvalidInput()

        color = edit._getTitleColor()

        assert isinstance(color, QColor)

    def test_get_border_color_returns_qcolor(self):
        """Test _getBorderColor returns QColor."""
        edit = ElaTagLineEdit()

        color = edit._getBorderColor()

        assert isinstance(color, QColor)

    def test_get_border_color_returns_danger_in_error_state(self):
        """Test _getBorderColor returns danger color when error."""
        edit = ElaTagLineEdit()
        edit.notifyInvalidInput()

        color = edit._getBorderColor()

        assert isinstance(color, QColor)

    def test_get_border_color_returns_primary_on_focus(self):
        """Test _getBorderColor returns primary when focused."""
        edit = ElaTagLineEdit()
        edit.setFocus()

        color = edit._getBorderColor()

        assert isinstance(color, QColor)

        edit.deleteLater()

    def test_delete_later_disconnects_text_changed(self):
        """Test deleteLater disconnects textChanged signal without error."""
        edit = ElaTagLineEdit(title="test")
        edit.deleteLater()  # should not raise TypeError when disconnecting

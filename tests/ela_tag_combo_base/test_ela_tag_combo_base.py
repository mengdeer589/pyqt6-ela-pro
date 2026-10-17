from __future__ import annotations

from unittest.mock import MagicMock, patch
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QPainter, QFont
from PyQt6.QtWidgets import QComboBox
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_tag_combo_base import (
    _TagBoxThemeMixin,
    _TagBoxAnimMixin,
    _pre_init_popup,
    _get_target_mark_width,
    _draw_tag_background,
    _draw_tag_title,
    _draw_tag_arrow,
    _draw_tag_mark,
    _draw_single_value_text,
    _draw_multi_value_text,
)


# ── Mock widget for mixin testing ────────────────────────────────


class MockThemeWidget:
    def __init__(self):
        self._theme_mode = ElaThemeType.ThemeMode.Light
        self._enabled = True
        self._has_focus = False
        self._under_mouse = False

    def isEnabled(self):
        return self._enabled

    def hasFocus(self):
        return self._has_focus

    def underMouse(self):
        return self._under_mouse


class TestTagBoxThemeMixin:
    def test_get_title_color_default(self):
        w = MockThemeWidget()
        mixin = _TagBoxThemeMixin()
        mixin._theme_mode = ElaThemeType.ThemeMode.Light
        color = mixin._getTitleColor.__get__(w, type(w))()
        assert isinstance(color, QColor)
        assert color.isValid()

    def test_get_title_color_disabled(self):
        w = MockThemeWidget()
        w._enabled = False
        mixin = _TagBoxThemeMixin()
        mixin._theme_mode = ElaThemeType.ThemeMode.Light
        color = mixin._getTitleColor.__get__(w, type(w))()
        assert isinstance(color, QColor)

    def test_get_background_color_default(self):
        w = MockThemeWidget()
        mixin = _TagBoxThemeMixin()
        mixin._theme_mode = ElaThemeType.ThemeMode.Light
        color = mixin._getBackgroundColor.__get__(w, type(w))()
        assert isinstance(color, QColor)

    def test_get_background_color_focused(self):
        w = MockThemeWidget()
        w._has_focus = True
        mixin = _TagBoxThemeMixin()
        mixin._theme_mode = ElaThemeType.ThemeMode.Light
        color = mixin._getBackgroundColor.__get__(w, type(w))()
        assert isinstance(color, QColor)

    def test_get_border_color_default(self):
        w = MockThemeWidget()
        mixin = _TagBoxThemeMixin()
        mixin._theme_mode = ElaThemeType.ThemeMode.Light
        color = mixin._getBorderColor.__get__(w, type(w))()
        assert isinstance(color, QColor)

    def test_get_border_color_focused(self):
        w = MockThemeWidget()
        w._has_focus = True
        mixin = _TagBoxThemeMixin()
        mixin._theme_mode = ElaThemeType.ThemeMode.Light
        color = mixin._getBorderColor.__get__(w, type(w))()
        assert isinstance(color, QColor)


# ── AnimMixin test helper ───────────────────────────────────────


class AnimMixinHost(_TagBoxAnimMixin, QComboBox):
    def __init__(self):
        QComboBox.__init__(self)
        _TagBoxAnimMixin.__init__(self)


class TestTagBoxAnimMixin:
    def test_init_sets_defaults(self):
        host = AnimMixinHost()
        host._tag_box_init("测试标题")
        assert host._title_text == "测试标题"
        assert host._title_font_size == 13
        assert host._expand_mark_width == 0.0
        assert host._expand_icon_rotate == 0.0
        assert host.height() == 30
        host.deleteLater()

    def test_set_title(self):
        host = AnimMixinHost()
        host._tag_box_init()
        host.setTitle("新标题")
        assert host.title() == "新标题"
        host.deleteLater()

    def test_expand_mark_width_property(self):
        host = AnimMixinHost()
        host._tag_box_init()
        assert host.expandMarkWidth == 0.0
        host.expandMarkWidth = 50.0
        assert host.expandMarkWidth == 50.0
        host.deleteLater()

    def test_expand_icon_rotate_property(self):
        host = AnimMixinHost()
        host._tag_box_init()
        assert host.expandIconRotate == 0.0
        host.expandIconRotate = -90.0
        assert host.expandIconRotate == -90.0
        host.deleteLater()

    def test_animate_popup_open_does_nothing_when_empty(self):
        host = AnimMixinHost()
        host._tag_box_init()
        host._animate_popup_open()
        assert host._expand_mark_width == 0.0
        host.deleteLater()

    def test_tag_box_theme_cleanup(self):
        host = AnimMixinHost()
        host._tag_box_init()
        host._theme_cleanup()
        host.deleteLater()


# ── Standalone function tests ────────────────────────────────────


class TestPreInitPopup:
    def test_pre_init_popup_sets_min_height(self):
        combo = QComboBox()
        with patch.object(combo, "view", return_value=MagicMock()) as mock_view:
            _pre_init_popup(combo)
            mock_view.return_value.setMinimumHeight.assert_called_once_with(200)
        combo.deleteLater()


class TestGetTargetMarkWidth:
    def test_get_target_mark_width_zero_count(self):
        combo = QComboBox()
        combo.width = MagicMock(return_value=200)
        combo.getCurrentSelection = MagicMock(return_value=[])
        combo.count = MagicMock(return_value=0)
        result = _get_target_mark_width(combo)
        assert result == 0.0
        combo.deleteLater()

    def test_get_target_mark_width_some_selected(self):
        combo = QComboBox()
        combo.width = MagicMock(return_value=200)
        combo.getCurrentSelection = MagicMock(return_value=["a", "b"])
        combo.count = MagicMock(return_value=4)
        result = _get_target_mark_width(combo)
        expected = (200 / 2 - 9) * 2 / 4
        assert result == expected
        combo.deleteLater()


class TestDrawTagBackground:
    def test_draw_tag_background_returns_tuple(self):
        widget = MagicMock()
        widget.width.return_value = 100
        widget.height.return_value = 30
        widget._getBackgroundColor.return_value = QColor(255, 255, 255)
        widget._getTitleColor.return_value = QColor(0, 0, 0)
        widget._getBorderColor.return_value = QColor(200, 200, 200)
        painter = QPainter()
        result = _draw_tag_background(painter, widget, face_inset=1)
        assert len(result) == 3
        content_rect, text_color, border_color = result
        assert isinstance(content_rect, QRect)
        assert isinstance(text_color, QColor)
        assert isinstance(border_color, QColor)


class TestDrawTagTitle:
    def test_draw_tag_title_returns_qrect(self):
        painter = QPainter()
        font = QFont()
        content_rect = QRect(3, 3, 94, 32)
        result = _draw_tag_title(
            painter,
            content_rect,
            "测试",
            13,
            QColor(0, 0, 0),
            font,
        )
        assert isinstance(result, QRect)
        assert result.left() == content_rect.left()
        assert result.top() == content_rect.top()


class TestDrawTagArrow:
    def test_draw_tag_arrow_runs_without_error(self):
        painter = QPainter()
        content_rect = QRect(3, 3, 94, 32)
        _draw_tag_arrow(painter, content_rect, QColor(0, 0, 0), 0.0)


class TestDrawTagMark:
    def test_draw_tag_mark_zero_width(self):
        widget = MagicMock()
        widget.width.return_value = 100
        widget.height.return_value = 30
        painter = QPainter()
        _draw_tag_mark(painter, widget, 0.0)

    def test_draw_tag_mark_positive_width(self):
        widget = MagicMock()
        widget.width.return_value = 100
        widget.height.return_value = 30
        painter = QPainter()
        _draw_tag_mark(painter, widget, 20.0)


class TestDrawSingleValueText:
    def test_draw_single_value_text_empty(self):
        painter = QPainter()
        content_rect = QRect(3, 3, 94, 32)
        title_rect = QRect(3, 3, 50, 32)
        _draw_single_value_text(painter, content_rect, title_rect, "")

    def test_draw_single_value_text_with_text(self):
        painter = QPainter()
        content_rect = QRect(3, 3, 94, 32)
        title_rect = QRect(3, 3, 50, 32)
        _draw_single_value_text(painter, content_rect, title_rect, "选中项")


class TestDrawMultiValueText:
    def test_draw_multi_value_text_empty(self):
        painter = QPainter()
        content_rect = QRect(3, 3, 94, 32)
        title_rect = QRect(3, 3, 50, 32)
        _draw_multi_value_text(painter, content_rect, title_rect, [])

    def test_draw_multi_value_text_with_selections(self):
        painter = QPainter()
        content_rect = QRect(3, 3, 94, 32)
        title_rect = QRect(3, 3, 50, 32)
        _draw_multi_value_text(
            painter, content_rect, title_rect, ["A", "B", "C", "D"], max_show=3
        )

    def test_draw_multi_value_text_fewer_than_max(self):
        painter = QPainter()
        content_rect = QRect(3, 3, 94, 32)
        title_rect = QRect(3, 3, 50, 32)
        _draw_multi_value_text(
            painter, content_rect, title_rect, ["A", "B"], max_show=3
        )

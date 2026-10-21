"""``ElaGroupBox`` 测试：初值 / 标题 / 圆角 / sizeHint / 主题。"""

from __future__ import annotations

import pytest
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_group_box import ElaGroupBox


@pytest.fixture
def gb(make):
    return make(ElaGroupBox)


class TestElaGroupBoxInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_title", ""),
            ("_border_radius", 6),
        ],
    )
    def test_initialization_with_defaults(self, gb, attr, expected):
        assert getattr(gb, attr) == expected

    def test_initialization_with_title(self, make):
        assert make(ElaGroupBox, title="基本信息").title() == "基本信息"

    def test_initialization_with_custom_radius(self, make):
        assert make(ElaGroupBox, border_radius=12).borderRadius() == 12


class TestElaGroupBoxTitle:
    @pytest.mark.parametrize(
        ("initial", "new", "expected"),
        [("", "高级设置", "高级设置"), ("旧标题", "", "")],
        ids=["set-new", "clear"],
    )
    def test_set_title(self, make, initial, new, expected):
        gb = make(ElaGroupBox, title=initial)
        gb.setTitle(new)
        assert gb.title() == expected


class TestElaGroupBoxBorderRadius:
    def test_border_radius_default(self, gb):
        assert gb.borderRadius() == 6

    def test_set_border_radius(self, gb):
        gb.setBorderRadius(16)
        assert gb.borderRadius() == 16


class TestElaGroupBoxSizeHint:
    def test_size_hint(self, gb):
        sz = gb.sizeHint()
        assert sz.width() == 160
        assert sz.height() > 0


class TestElaGroupBoxTheme:
    def test_on_theme_changed_updates_mode(self, gb):
        gb._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert gb._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaGroupBoxDeleteLater:
    def test_delete_later_cleans_up(self, gb):
        gb.deleteLater()

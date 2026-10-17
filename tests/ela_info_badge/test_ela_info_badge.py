"""``ElaInfoBadge`` 测试：初值 / 枚举 / 模式 / 数值 / 图标 / 严重级别 / 挂载。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaIconType, ElaThemeType

from pyqt6_ela_pro.ela_info_badge import ElaInfoBadge


@pytest.fixture
def badge(make):
    return make(ElaInfoBadge)


@pytest.fixture
def target(make):
    return make(QWidget)


class TestElaInfoBadgeInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_badge_mode", ElaInfoBadge.ElaBadgeModeType.Dot),
            ("_severity", ElaInfoBadge.ElaSeverityType.Attention),
            ("_value", 0),
            ("_max_value", 99),
            ("_target", None),
        ],
    )
    def test_initialization_with_defaults(self, badge, attr, expected):
        assert getattr(badge, attr) == expected

    def test_transparent_for_mouse_events(self, badge):
        assert badge.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def test_initialization_with_value(self, make):
        badge = make(ElaInfoBadge, value=5)
        assert badge._badge_mode == ElaInfoBadge.ElaBadgeModeType.Value
        assert badge._value == 5

    def test_initialization_with_icon(self, make):
        badge = make(ElaInfoBadge, icon=ElaIconType.IconName.Gear)
        assert badge._badge_mode == ElaInfoBadge.ElaBadgeModeType.Icon
        assert badge._icon == ElaIconType.IconName.Gear


class TestElaInfoBadgeEnums:
    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            (ElaInfoBadge.ElaBadgeModeType.Dot, 0),
            (ElaInfoBadge.ElaBadgeModeType.Value, 1),
            (ElaInfoBadge.ElaBadgeModeType.Icon, 2),
        ],
    )
    def test_badge_mode_values(self, member, expected):
        assert member == expected

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            (ElaInfoBadge.ElaSeverityType.Attention, 0),
            (ElaInfoBadge.ElaSeverityType.Informational, 1),
            (ElaInfoBadge.ElaSeverityType.Success, 2),
            (ElaInfoBadge.ElaSeverityType.Caution, 3),
            (ElaInfoBadge.ElaSeverityType.Critical, 4),
        ],
    )
    def test_severity_values(self, member, expected):
        assert member == expected


class TestElaInfoBadgeMode:
    def test_badge_mode_default(self, badge):
        assert badge.badgeMode() == ElaInfoBadge.ElaBadgeModeType.Dot

    def test_set_badge_mode(self, badge):
        badge.setBadgeMode(ElaInfoBadge.ElaBadgeModeType.Value)
        assert badge.badgeMode() == ElaInfoBadge.ElaBadgeModeType.Value


class TestElaInfoBadgeValue:
    def test_value_default(self, badge):
        assert badge.value() == 0

    @pytest.mark.parametrize("value", [42, 0], ids=["42", "0"])
    def test_set_value(self, badge, value):
        badge.setValue(value)
        assert badge.value() == value


class TestElaInfoBadgeMaxValue:
    def test_max_value_default(self, badge):
        assert badge.maxValue() == 99

    def test_set_max_value(self, badge):
        badge.setMaxValue(999)
        assert badge.maxValue() == 999

    def test_max_value_overflow_displays_plus(self, badge):
        badge.setBadgeMode(ElaInfoBadge.ElaBadgeModeType.Value)
        badge.setValue(150)
        badge.setMaxValue(99)
        text = (
            str(badge._value)
            if badge._value <= badge._max_value
            else f"{badge._max_value}+"
        )
        assert text == "99+"


class TestElaInfoBadgeIcon:
    def test_ela_icon_default(self, badge):
        assert badge.elaIcon() == ElaIconType.IconName.None_

    def test_set_ela_icon(self, badge):
        badge.setElaIcon(ElaIconType.IconName.Check)
        assert badge.elaIcon() == ElaIconType.IconName.Check


class TestElaInfoBadgeSeverity:
    def test_severity_default(self, badge):
        assert badge.severity() == ElaInfoBadge.ElaSeverityType.Attention

    def test_set_severity(self, badge):
        badge.setSeverity(ElaInfoBadge.ElaSeverityType.Success)
        assert badge.severity() == ElaInfoBadge.ElaSeverityType.Success

    def test_set_severity_all_values(self, badge):
        for s in ElaInfoBadge.ElaSeverityType:
            badge.setSeverity(s)
            assert badge.severity() == s


class TestElaInfoBadgeAttachDetach:
    def test_attach_to_sets_target(self, badge, target):
        badge.attachTo(target)
        assert badge._target is target
        assert badge.parent() is target

    def test_detach_clears_target(self, badge, target):
        badge.attachTo(target)
        badge.detach()
        assert badge._target is None
        assert badge.isVisible() is False


class TestElaInfoBadgeSeverityColor:
    def test_get_severity_color_returns_qcolor(self, badge):
        assert isinstance(badge._getSeverityColor(), QColor)


class TestElaInfoBadgeSizeHint:
    def test_size_hint_dot_mode(self, badge):
        assert badge.sizeHint() == QSize(10, 10)

    def test_size_hint_value_mode(self, make):
        sz = make(ElaInfoBadge, value=5).sizeHint()
        assert sz.width() >= 16
        assert sz.height() == 16

    def test_size_hint_icon_mode(self, make):
        sz = make(ElaInfoBadge, icon=ElaIconType.IconName.Gear).sizeHint()
        assert sz == QSize(16, 16)


class TestElaInfoBadgeTheme:
    def test_on_theme_changed_updates_mode(self, badge):
        badge._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert badge._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaInfoBadgeDeleteLater:
    def test_delete_later_removes_event_filter(self, make):
        """``deleteLater()`` 必须摘掉 target 上的事件过滤器，否则析构后回调野指针。"""
        badge = make(ElaInfoBadge)
        target = make(QWidget)
        badge.attachTo(target)
        badge.deleteLater()
        target.deleteLater()

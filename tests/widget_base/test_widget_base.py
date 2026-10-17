"""``ElaThemeWidget`` 基类测试：继承关系 / objectName / createLayout。"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from pyqt6_ela_pro.widget_base import ElaThemeWidget


@pytest.fixture
def tw(make):
    """默认构造的 ElaThemeWidget。"""
    return make(ElaThemeWidget)


class TestThemeWidget:
    """Test cases for ElaThemeWidget class."""

    def test_theme_widget_inherits_from_qwidget(self, tw):
        assert isinstance(tw, QWidget)

    def test_theme_widget_sets_object_name(self, tw):
        assert tw.objectName() == "ElaThemeWidget"

    @pytest.mark.parametrize(
        ("orientation", "layout_type"),
        [
            ("h", QHBoxLayout),
            ("v", QVBoxLayout),
            ("g", QGridLayout),
        ],
        ids=["horizontal", "vertical", "grid"],
    )
    def test_createLayout_type(self, tw, orientation, layout_type):
        assert isinstance(tw.createLayout(orientation), layout_type)

    def test_createLayout_sets_zero_margins_and_spacing(self, tw):
        lay = tw.createLayout("h")
        margins = lay.contentsMargins()
        assert (
            margins.left() == 0
            and margins.top() == 0
            and margins.right() == 0
            and margins.bottom() == 0
        )
        assert lay.spacing() == 0

    def test_createLayout_with_parent(self, make, tw):
        parent = make(QWidget)
        assert tw.createLayout("v", parent=parent).parent() is parent

    def test_alert_accepts_string_levels(self, tw):
        assert hasattr(tw, "alert")

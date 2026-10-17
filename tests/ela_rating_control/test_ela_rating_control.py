"""``ElaRatingControl`` 测试：初值 / 评分夹取 / 星级 / 只读 / hover / 主题。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_rating_control import ElaRatingControl


@pytest.fixture
def r(make):
    return make(ElaRatingControl)


class TestElaRatingControlInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_max_rating", 5),
            ("_rating", 0.0),
            ("_star_size", 24),
            ("_spacing", 4),
            ("_is_read_only", False),
            ("_hovered_star", -1.0),
        ],
    )
    def test_initialization_with_defaults(self, r, attr, expected):
        assert getattr(r, attr) == expected

    def test_has_rating_changed_signal(self, r):
        assert hasattr(r, "ratingChanged")
        assert callable(r.ratingChanged)

    def test_mouse_tracking_enabled(self, r):
        assert r.hasMouseTracking() is True


class TestElaRatingControlRating:
    def test_rating_default(self, r):
        assert r.rating() == 0.0

    def test_set_rating(self, r):
        r.setRating(3.5)
        assert r.rating() == 3.5

    def test_set_rating_emits_signal(self, r):
        received = []
        r.ratingChanged.connect(lambda v: received.append(v))
        r.setRating(4.0)
        assert 4.0 in received

    def test_set_rating_same_value_no_emit(self, r):
        r.setRating(3.0)
        received = []
        r.ratingChanged.connect(lambda v: received.append(v))
        r.setRating(3.0)
        assert len(received) == 0

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [
            (-1.0, 0.0),
            (10.0, 5.0),
            (3.7, 3.5),
            (3.3, 3.5),
        ],
        ids=["below-min", "above-max", "round-down", "round-up"],
    )
    def test_set_rating_clamps_and_rounds(self, r, requested, expected):
        """越界夹到 0 / max，其余四舍五入到 0.5 粒度。"""
        r.setRating(requested)
        assert r.rating() == expected


class TestElaRatingControlMaxRating:
    def test_max_rating_default(self, r):
        assert r.maxRating() == 5

    def test_set_max_rating(self, r):
        r.setMaxRating(10)
        assert r.maxRating() == 10

    def test_set_max_rating_updates_geometry(self, r):
        r.setMaxRating(3)
        old_w = r.width()
        r.setMaxRating(10)
        assert r.width() >= old_w


class TestElaRatingControlStarSize:
    def test_star_size_default(self, r):
        assert r.starSize() == 24

    def test_set_star_size(self, r):
        r.setStarSize(32)
        assert r.starSize() == 32

    def test_set_star_size_updates_height(self, r):
        r.setStarSize(40)
        assert r.height() >= 40


class TestElaRatingControlSpacing:
    def test_spacing_default(self, r):
        assert r.spacing() == 4

    def test_set_spacing(self, r):
        r.setSpacing(8)
        assert r.spacing() == 8


class TestElaRatingControlReadOnly:
    def test_read_only_default(self, r):
        assert r.isReadOnly() is False

    def test_set_read_only(self, r):
        r.setReadOnly(True)
        assert r.isReadOnly() is True

    def test_read_only_prevents_rating_change(self, r):
        r.setReadOnly(True)
        r._hovered_star = 3.0

        r.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(QPoint(50, 12)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert r.rating() == 0.0


class TestElaRatingControlHover:
    def test_hover_initially_negative(self, r):
        assert r._hovered_star == -1.0

    def test_leave_event_resets_hover(self, r):
        r._hovered_star = 3.0
        r.leaveEvent(QEvent(QEvent.Type.Leave))
        assert r._hovered_star == -1.0


class TestElaRatingControlTheme:
    def test_on_theme_changed_updates_mode(self, r):
        r._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert r._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaRatingControlDeleteLater:
    def test_delete_later_cleans_up(self, r):
        r.deleteLater()

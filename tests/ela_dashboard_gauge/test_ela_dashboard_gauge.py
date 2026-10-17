"""``ElaDashboardGauge`` 测试：初值 / 值域夹取 / 刻度下限 / 角度 / 元数据 / 阈值。"""

from __future__ import annotations

import pytest
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_dashboard_gauge import ElaDashboardGauge


@pytest.fixture
def g(make):
    return make(ElaDashboardGauge)


class TestElaDashboardGaugeInit:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("minimum", 0.0),
            ("maximum", 100.0),
            ("value", 0.0),
            ("majorTickCount", 10),
            ("minorTickCount", 5),
            ("startAngle", 225),
            ("spanAngle", 270),
            ("arcWidth", 12),
            ("valuePixelSize", 22),
            ("isAnimated", True),
            ("decimals", 0),
            ("title", ""),
            ("unit", ""),
            ("dangerPercent", 0.85),
            ("warningPercent", 0.65),
            ("tickWarningPercent", 0.7),
        ],
    )
    def test_initialization_with_defaults(self, g, name, expected):
        assert getattr(g, name)() == expected

    def test_size_hint(self, g):
        sz = g.sizeHint()
        assert sz.width() == 260
        assert sz.height() == 260

    def test_has_value_changed_signal(self, g):
        assert hasattr(g, "valueChanged")
        assert callable(g.valueChanged)


class TestElaDashboardGaugeRange:
    @pytest.mark.parametrize(
        ("setter", "getter", "value"),
        [("setMinimum", "minimum", 20), ("setMaximum", "maximum", 200)],
        ids=["minimum", "maximum"],
    )
    def test_set_range_bound(self, g, setter, getter, value):
        getattr(g, setter)(value)
        assert getattr(g, getter)() == value

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [(150, 100.0), (-10, 0.0)],
        ids=["above-max", "below-min"],
    )
    def test_value_clamped(self, g, requested, expected):
        g.setValue(requested)
        assert g.value() == expected


class TestElaDashboardGaugeValue:
    def test_set_value(self, g):
        g.setIsAnimated(False)
        g.setValue(75)
        assert g.value() == 75.0

    def test_set_value_emits_signal(self, g):
        g.setIsAnimated(False)
        received = []
        g.valueChanged.connect(lambda v: received.append(v))
        g.setValue(50)
        assert 50.0 in received

    def test_set_value_same_no_emit(self, g):
        g.setIsAnimated(False)
        g.setValue(50)
        received = []
        g.valueChanged.connect(lambda v: received.append(v))
        g.setValue(50)
        assert len(received) == 0


class TestElaDashboardGaugeTicks:
    @pytest.mark.parametrize(
        ("setter", "getter", "requested", "floor"),
        [
            ("setMajorTickCount", "majorTickCount", 1, 2),
            ("setMinorTickCount", "minorTickCount", 0, 1),
        ],
        ids=["major-min-2", "minor-min-1"],
    )
    def test_tick_count_floor(self, g, setter, getter, requested, floor):
        getattr(g, setter)(requested)
        assert getattr(g, getter)() >= floor


class TestElaDashboardGaugeAngles:
    @pytest.mark.parametrize(
        ("requested", "expected"),
        [(5, 10), (400, 360)],
        ids=["below-min", "above-max"],
    )
    def test_span_angle_clamped(self, g, requested, expected):
        g.setSpanAngle(requested)
        assert g.spanAngle() == expected


class TestElaDashboardGaugeMetadata:
    @pytest.mark.parametrize(
        ("setter", "getter", "value"),
        [
            ("setTitle", "title", "速度"),
            ("setUnit", "unit", "km/h"),
            ("setDecimals", "decimals", 2),
        ],
        ids=["title", "unit", "decimals"],
    )
    def test_setter_roundtrip(self, g, setter, getter, value):
        getattr(g, setter)(value)
        assert getattr(g, getter)() == value


class TestElaDashboardGaugeThresholds:
    @pytest.mark.parametrize(
        ("setter", "getter", "requested", "expected"),
        [
            ("setDangerPercent", "dangerPercent", 1.5, 1.0),
            ("setDangerPercent", "dangerPercent", -0.5, 0.0),
            ("setWarningPercent", "warningPercent", 0.5, 0.5),
            ("setTickWarningPercent", "tickWarningPercent", 0.6, 0.6),
        ],
        ids=["danger-above-1", "danger-below-0", "warning", "tick-warning"],
    )
    def test_threshold_roundtrip(self, g, setter, getter, requested, expected):
        getattr(g, setter)(requested)
        assert getattr(g, getter)() == expected


class TestElaDashboardGaugeTheme:
    def test_on_theme_changed_updates_mode(self, g):
        g._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert g._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaDashboardGaugeDeleteLater:
    def test_delete_later_cleans_up(self, g):
        g.deleteLater()

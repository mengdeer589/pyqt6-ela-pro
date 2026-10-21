"""Tests for the interaction switches (setInteractive / per-feature)."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget


def _interact_option():
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"top": "top"},
        "xAxis": {"type": "category", "data": ["一", "二", "三", "四", "五", "六"]},
        "yAxis": {},
        "series": [
            {"type": "bar", "name": "A", "data": [1, 2, 3, 4, 5, 6]},
            {"type": "line", "name": "B", "data": [3, 2, 4, 1, 5, 2]},
        ],
        "dataZoom": [{"type": "slider"}, {"type": "inside"}],
        "toolbox": {"feature": ["restore", "dataZoom"]},
        "timeline": {"data": ["2024", "2025"]},
    }


def _make_chart(option=None):
    chart = ElaChartWidget()
    chart.resize(600, 400)
    chart.setOption(option or _interact_option())
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _component(chart, key: str):
    return next(c for c in chart.components if getattr(c, "optionKey", "") == key)


def _press(chart, pos: QPointF):
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()


def _move(chart, pos: QPointF):
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()


def _release(chart, pos: QPointF):
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()


def _wheel(chart, pos: QPointF):
    event = QWheelEvent(
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()
    return event


class TestInteractionSwitches:
    def test_master_switch_blocks_wheel_zoom(self):
        chart = _make_chart()
        dz = _component(chart, "dataZoom")
        plot = chart.primaryCoord().plot

        chart.setInteractive(False)
        _wheel(chart, plot.center())
        assert dz.end == 100.0

        chart.setInteractive(True)
        _wheel(chart, plot.center())
        assert dz.end < 100.0
        chart.deleteLater()

    def test_master_switch_blocks_tooltip(self):
        chart = _make_chart()
        plot = chart.primaryCoord().plot

        _move(chart, plot.center())
        assert chart.tooltip.active
        chart.setInteractive(False)
        assert not chart.tooltip.active
        _move(chart, plot.center())
        assert not chart.tooltip.active
        chart.deleteLater()

    def test_tooltip_feature_toggle(self):
        chart = _make_chart()
        plot = chart.primaryCoord().plot

        chart.setInteractionEnabled("tooltip", False)
        _move(chart, plot.center())
        assert not chart.tooltip.active

        chart.setInteractionEnabled("tooltip", True)
        _move(chart, plot.center())
        assert chart.tooltip.active
        chart.deleteLater()

    def test_legend_toggle_blocked(self):
        chart = _make_chart()
        rect = chart.legend._item_rects[0]
        name = chart.legend._items[0][0]

        chart.setInteractionEnabled("legend", False)
        _press(chart, rect.center())
        assert chart._seriesVisible(name)

        chart.setInteractionEnabled("legend", True)
        _press(chart, rect.center())
        assert not chart._seriesVisible(name)
        chart.deleteLater()

    def test_datazoom_feature_blocks_wheel_and_drag(self):
        option = _interact_option()
        option.pop("timeline", None)
        chart = _make_chart(option)
        dz = _component(chart, "dataZoom")
        plot = chart.primaryCoord().plot

        chart.setInteractionEnabled("dataZoom", False)
        _wheel(chart, plot.center())
        assert dz.end == 100.0
        _press(chart, dz._h_start.center())
        _move(chart, QPointF(dz._h_start.center().x() + 60, dz._h_start.center().y()))
        _release(
            chart, QPointF(dz._h_start.center().x() + 60, dz._h_start.center().y())
        )
        assert dz.start == 0.0

        chart.setInteractionEnabled("dataZoom", True)
        _wheel(chart, plot.center())
        assert dz.end < 100.0
        chart.deleteLater()

    def test_master_switch_on_resets_features(self):
        """总开关**打开 = 全开**：逐功能开关的覆盖被清空（不是保留上轮关掉的）。"""

        chart = _make_chart(_interact_option())
        chart.setInteractionEnabled("tooltip", False)
        chart.setInteractionEnabled("dataZoom", False)
        assert chart.isInteractionEnabled("tooltip") is False

        chart.setInteractive(False)
        chart.setInteractive(True)
        assert chart.isInteractionEnabled("tooltip") is True, "总开关打开应恢复全开"
        assert chart.isInteractionEnabled("dataZoom") is True

        # 行为也要真的回来（不只是标志位）
        plot = chart.primaryCoord().plot
        _wheel(chart, plot.center())
        assert _component(chart, "dataZoom").end < 100.0
        chart.deleteLater()

    def test_master_switch_off_keeps_feature_flags(self):
        """总开关关闭期间逐功能覆盖保留（重新打开时由「全开」统一复位）。"""

        chart = _make_chart(_interact_option())
        chart.setInteractionEnabled("legend", False)
        chart.setInteractive(False)
        assert chart.isInteractionEnabled("legend") is False
        chart.deleteLater()

    def test_timeline_feature_blocks_play_button(self):
        option = _interact_option()
        option.pop("dataZoom", None)
        chart = _make_chart(option)
        timeline = _component(chart, "timeline")

        chart.setInteractionEnabled("timeline", False)
        _press(chart, timeline._play_rect.center())
        assert not timeline.playing

        chart.setInteractionEnabled("timeline", True)
        _press(chart, timeline._play_rect.center())
        assert timeline.playing
        timeline._timer.stop()  # 停止自动播放，避免测试间残留定时器
        chart.deleteLater()

    def test_toolbox_feature_blocks_buttons(self):
        option = _interact_option()
        option.pop("timeline", None)
        chart = _make_chart(option)
        toolbox = _component(chart, "toolbox")
        button = toolbox.buttonWidget("dataZoom")
        assert button is not None

        chart.setInteractionEnabled("toolbox", False)
        assert button.isEnabled() is False, "工具条开关关闭后按钮应禁用"
        button.click()
        assert getattr(chart, "_dataZoomEnabled", True) is True

        chart.setInteractionEnabled("toolbox", True)
        assert button.isEnabled() is True
        button.click()
        assert chart._dataZoomEnabled is False
        chart.deleteLater()

    def test_unknown_feature_raises(self):
        chart = _make_chart()
        with pytest.raises(ValueError):
            chart.setInteractionEnabled("zoom", False)
        chart.deleteLater()

    def test_switches_survive_option_update(self):
        chart = _make_chart()
        chart.setInteractionEnabled("tooltip", False)
        chart.setOption(_interact_option())
        chart._layout_all(force=True)
        plot = chart.primaryCoord().plot
        _move(chart, plot.center())
        assert not chart.tooltip.active
        assert chart.isInteractionEnabled("tooltip") is False
        chart.deleteLater()
